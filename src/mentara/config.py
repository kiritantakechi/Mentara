"""Configuration schema, TOML loading, and cross-platform resolution."""

import os
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Self
lazy from collections.abc import Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from mentara.errors import ConfigError

__all__ = [
    "DEFAULT_CONFIG_FILENAME",
    "DEFAULT_COPY_PATTERNS",
    "DEFAULT_EXCLUDE",
    "BackendKind",
    "MentaraConfig",
    "PlatformConfig",
    "PlatformKind",
    "ProfileConfig",
    "ProfileOverrides",
    "ResolvedProfile",
    "ResolvedRunner",
    "RunnerConfig",
    "RunnerOverrideConfig",
    "find_config_path",
    "load_config",
    "resolve_profile",
]

DEFAULT_CONFIG_FILENAME = "mentara.toml"
DEFAULT_EXCLUDE: tuple[str, ...] = ("Mentara", ".git", ".gitkeep")
DEFAULT_COPY_PATTERNS: tuple[str, ...] = (
    "*.ini",
    "*.cfg",
    "*.log",
    "*.sav",
    "*.key",
)


class PlatformKind(StrEnum):
    """Supported host operating system families."""

    LINUX = "linux"
    WINDOWS = "windows"

    @classmethod
    def current(cls) -> PlatformKind:
        """Detect the active host platform family.

        Returns:
            `PlatformKind.WINDOWS` on Windows NT, otherwise `LINUX`.
        """
        return cls.WINDOWS if os.name.startswith("nt") else cls.LINUX


class BackendKind(StrEnum):
    """Supported virtual workspace materialisation backends."""

    FUSE_OVERLAYFS = "fuse-overlayfs"
    SYMLINK = "symlink"


class RunnerConfig(BaseModel):
    """Base launcher runtime command and environment settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: tuple[str, ...] = ()
    executable: str = "MentalOmegaClient.exe"
    args: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_executable(self) -> Self:
        if not self.executable.strip():
            msg = "runner.executable must not be empty"
            raise ValueError(msg)
        return self


class RunnerOverrideConfig(BaseModel):
    """Partial overrides applied on top of a base `RunnerConfig`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: tuple[str, ...] | None = None
    executable: str | None = None
    args: tuple[str, ...] | None = None
    env: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_executable(self) -> Self:
        if self.executable is not None and not self.executable.strip():
            msg = "runner.executable override must not be empty"
            raise ValueError(msg)
        return self


class PlatformConfig(BaseModel):
    """Symmetric platform overrides for `[linux]` and `[windows]`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: BackendKind | None = None
    runtime_dir: str | None = None
    state_dir: str | None = None
    runner: RunnerOverrideConfig | None = None


class ProfileConfig(BaseModel):
    """Declarative overlay profile for layers and runtime options."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str = ""
    layers: tuple[str, ...] = ()
    backend: BackendKind | None = None
    runtime_dir: str | None = None
    state_dir: str | None = None
    persist_state: bool = True
    copy_patterns: tuple[str, ...] | None = None
    runner: RunnerOverrideConfig | None = None
    linux: PlatformConfig | None = None
    windows: PlatformConfig | None = None

    def for_platform(self, platform: PlatformKind) -> PlatformConfig | None:
        """Return the platform-specific section for `platform`.

        Args:
            platform: Target host platform.

        Returns:
            Matching `PlatformConfig`, or `None`.
        """
        match platform:
            case PlatformKind.LINUX:
                return self.linux
            case PlatformKind.WINDOWS:
                return self.windows


class MentaraConfig(BaseModel):
    """Top-level `mentara.toml` schema supporting Linux and Windows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_dir: str = ".."
    runtime_dir: str | None = None
    state_dir: str | None = None
    default_profile: str = "default"
    backend: BackendKind | None = None
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE
    copy_patterns: tuple[str, ...] = DEFAULT_COPY_PATTERNS
    runner: RunnerOverrideConfig | None = None
    linux: PlatformConfig = Field(default_factory=PlatformConfig)
    windows: PlatformConfig = Field(default_factory=PlatformConfig)
    profiles: dict[str, ProfileConfig] = Field(
        default_factory=lambda: {"default": ProfileConfig()},
    )

    def for_platform(self, platform: PlatformKind) -> PlatformConfig:
        """Return the top-level platform table for `platform`.

        Args:
            platform: Target host platform.

        Returns:
            The `linux` or `windows` `PlatformConfig`.
        """
        match platform:
            case PlatformKind.LINUX:
                return self.linux
            case PlatformKind.WINDOWS:
                return self.windows

    @model_validator(mode="after")
    def _validate_profiles(self) -> Self:
        if not self.profiles:
            msg = "profiles must define at least one profile"
            raise ValueError(msg)
        for name in self.profiles:
            _validate_slug(name)
        if self.default_profile not in self.profiles:
            msg = (
                f"default_profile {self.default_profile!r} is not "
                "defined under [profiles]"
            )
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class ProfileOverrides:
    """Optional CLI overrides applied when resolving a profile."""

    backend: BackendKind | None = None
    executable: str | None = None
    extra_args: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedRunner:
    """Fully resolved, immutable runner command and environment."""

    command: tuple[str, ...]
    executable: str
    args: tuple[str, ...]
    env: frozendict[str, str]


@dataclass(frozen=True, slots=True)
class ResolvedProfile:
    """Fully resolved profile with concrete paths and merged options."""

    name: str
    description: str
    platform: PlatformKind
    config_dir: Path
    base_dir: Path
    layers: tuple[Path, ...]
    backend: BackendKind
    persist_state: bool
    runtime_dir: Path
    state_dir: Path
    exclude: tuple[str, ...]
    copy_patterns: tuple[str, ...]
    runner: ResolvedRunner

    @property
    def merged_dir(self) -> Path:
        """Target virtual workspace directory for this profile."""
        return self.runtime_dir / "merged"

    @property
    def upper_dir(self) -> Path | None:
        """Persistent writable layer directory, or `None`."""
        return self.state_dir / "upper" if self.persist_state else None


def find_config_path(
    explicit: Path | None = None,
    *,
    cwd: Path | None = None,
) -> Path:
    """Locate `mentara.toml` explicitly or by searching parent dirs.

    Args:
        explicit: User-supplied configuration file path, if any.
        cwd: Working directory to start searching from.

    Returns:
        Resolved path to the configuration file.

    Raises:
        ConfigError: If the configuration file cannot be found.
    """
    if explicit is not None:
        resolved = explicit.expanduser().resolve()
        if not resolved.is_file():
            raise ConfigError.missing_file(resolved)
        return resolved

    start = (cwd or Path.cwd()).resolve()
    for directory in (start, *start.parents):
        candidate = directory / DEFAULT_CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    raise ConfigError.missing_file(start / DEFAULT_CONFIG_FILENAME)


def load_config(path: Path) -> MentaraConfig:
    """Read and validate a `mentara.toml` configuration file.

    Args:
        path: Path to the TOML configuration file.

    Returns:
        Validated `MentaraConfig` instance.

    Raises:
        ConfigError: If reading, TOML parsing, or validation fails.
    """
    if not path.is_file():
        raise ConfigError.missing_file(path)

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError.unreadable_file(path, str(exc)) from exc

    try:
        payload = tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError.invalid_toml(path, str(exc)) from exc

    try:
        return MentaraConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError.validation_failed(path, str(exc)) from exc


def resolve_profile(
    config: MentaraConfig,
    *,
    config_dir: Path,
    profile_name: str | None = None,
    platform: PlatformKind | None = None,
    overrides: ProfileOverrides | None = None,
) -> ResolvedProfile:
    """Resolve a profile into concrete paths for a target platform.

    Resolution precedence (lowest to highest):
    1. Built-in defaults for `platform`.
    2. Top-level `config` and `config.<platform>`.
    3. `profile` and `profile.<platform>`.
    4. Command-line `overrides`.

    Args:
        config: Validated top-level configuration.
        config_dir: Directory containing `mentara.toml`.
        profile_name: Profile name; defaults to `default_profile`.
        platform: Host platform; defaults to `PlatformKind.current()`.
        overrides: Optional CLI overrides for backend or runner.

    Returns:
        An immutable `ResolvedProfile`.

    Raises:
        ConfigError: If the profile is unknown or paths overlap.
    """
    chosen_name = profile_name or config.default_profile
    profile = config.profiles.get(chosen_name)
    if profile is None:
        raise ConfigError.unknown_profile(chosen_name, tuple(config.profiles))

    active_platform = PlatformKind.current() if platform is None else platform
    global_plat = config.for_platform(active_platform)
    profile_plat = profile.for_platform(active_platform)
    applied = ProfileOverrides() if overrides is None else overrides

    resolved_config_dir = config_dir.expanduser().resolve()
    base_dir = _resolve_path(config.base_dir, anchor=resolved_config_dir)
    layers = _resolve_layers(
        profile.layers,
        anchor=resolved_config_dir,
        base_dir=base_dir,
    )

    raw_runtime = _first_non_empty(
        (
            profile_plat.runtime_dir if profile_plat is not None else None,
            profile.runtime_dir,
            global_plat.runtime_dir,
            config.runtime_dir,
        )
    )
    raw_state = _first_non_empty(
        (
            profile_plat.state_dir if profile_plat is not None else None,
            profile.state_dir,
            global_plat.state_dir,
            config.state_dir,
        )
    )
    runtime_root = (
        _resolve_path(raw_runtime, anchor=resolved_config_dir)
        if raw_runtime is not None
        else _default_runtime_root(active_platform)
    )
    state_root = (
        _resolve_path(raw_state, anchor=resolved_config_dir)
        if raw_state is not None
        else _default_state_root(active_platform)
    )
    runtime_dir = runtime_root / chosen_name
    state_dir = state_root / chosen_name

    _ensure_disjoint_workspace(
        runtime_dir=runtime_dir,
        state_dir=state_dir,
        base_dir=base_dir,
        layers=layers,
    )

    runner = _merge_runner_chain(
        base=_default_runner_for(active_platform),
        overrides=(
            config.runner,
            global_plat.runner,
            profile.runner,
            profile_plat.runner if profile_plat is not None else None,
        ),
        executable_override=applied.executable,
        extra_args=applied.extra_args,
    )
    backend = (
        applied.backend
        or (profile_plat.backend if profile_plat is not None else None)
        or profile.backend
        or global_plat.backend
        or config.backend
        or _default_backend_for(active_platform)
    )
    copy_patterns = (
        profile.copy_patterns
        if profile.copy_patterns is not None
        else config.copy_patterns
    )

    return ResolvedProfile(
        name=chosen_name,
        description=profile.description,
        platform=active_platform,
        config_dir=resolved_config_dir,
        base_dir=base_dir,
        layers=layers,
        backend=backend,
        persist_state=profile.persist_state,
        runtime_dir=runtime_dir,
        state_dir=state_dir,
        exclude=config.exclude,
        copy_patterns=copy_patterns,
        runner=runner,
    )


def _default_backend_for(platform: PlatformKind) -> BackendKind:
    match platform:
        case PlatformKind.LINUX:
            return BackendKind.FUSE_OVERLAYFS
        case PlatformKind.WINDOWS:
            return BackendKind.SYMLINK


def _default_runner_for(platform: PlatformKind) -> RunnerConfig:
    match platform:
        case PlatformKind.LINUX:
            return RunnerConfig(
                command=("umu-run",),
                executable="MentalOmegaClient.exe",
            )
        case PlatformKind.WINDOWS:
            return RunnerConfig(
                command=(),
                executable="MentalOmegaClient.exe",
            )


def _first_non_empty(candidates: Sequence[str | None]) -> str | None:
    for item in candidates:
        if item is not None and item != "":
            return item
    return None


def _validate_slug(name: str) -> None:
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        msg = f"Profile name {name!r} must be a non-empty single path segment"
        raise ValueError(msg)


def _resolve_path(raw: str, *, anchor: Path) -> Path:
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (anchor / candidate).resolve()


def _resolve_layers(
    raw_layers: Sequence[str],
    *,
    anchor: Path,
    base_dir: Path,
) -> tuple[Path, ...]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for raw in raw_layers:
        layer = _resolve_path(raw, anchor=anchor)
        if layer == base_dir:
            raise ConfigError.layer_equals_base(layer)
        if layer in seen:
            raise ConfigError.duplicate_layer(layer)
        seen.add(layer)
        resolved.append(layer)
    return tuple(resolved)


def _env_path(var_name: str) -> Path | None:
    raw = os.environ.get(var_name)
    return Path(raw).expanduser() if raw is not None and raw != "" else None


def _windows_app_data_root() -> Path:
    base = _env_path("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    return (base / "mentara").resolve()


def _default_runtime_root(platform: PlatformKind) -> Path:
    match platform:
        case PlatformKind.WINDOWS:
            return _windows_app_data_root() / "runtime"
        case PlatformKind.LINUX:
            base = _env_path("XDG_CACHE_HOME") or (Path.home() / ".cache")
            return (base / "mentara" / "runtime").resolve()


def _default_state_root(platform: PlatformKind) -> Path:
    match platform:
        case PlatformKind.WINDOWS:
            return _windows_app_data_root() / "state"
        case PlatformKind.LINUX:
            base = _env_path("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
            return (base / "mentara").resolve()


def _ensure_disjoint_workspace(
    *,
    runtime_dir: Path,
    state_dir: Path,
    base_dir: Path,
    layers: Sequence[Path],
) -> None:
    if _paths_overlap(runtime_dir, state_dir):
        runtime_role = "runtime_dir"
        state_role = "state_dir"
        raise ConfigError.overlapping_paths(
            runtime_role,
            runtime_dir,
            state_role,
            state_dir,
        )

    sources: list[tuple[str, Path]] = [("base_dir", base_dir)]
    sources.extend((f"layer {idx + 1}", layer) for idx, layer in enumerate(layers))

    for role, workspace_path in (
        ("runtime_dir", runtime_dir),
        ("state_dir", state_dir),
    ):
        for source_role, source_path in sources:
            if _paths_overlap(workspace_path, source_path):
                raise ConfigError.overlapping_paths(
                    role,
                    workspace_path,
                    source_role,
                    source_path,
                )


def _paths_overlap(first: Path, second: Path) -> bool:
    return first.is_relative_to(second) or second.is_relative_to(first)


def _merge_runner_chain(
    *,
    base: RunnerConfig,
    overrides: Sequence[RunnerOverrideConfig | None],
    executable_override: str | None,
    extra_args: Sequence[str],
) -> ResolvedRunner:
    command = base.command
    executable = base.executable
    args = base.args
    merged_env = dict(base.env)

    for override in overrides:
        if override is None:
            continue
        if override.command is not None:
            command = override.command
        if override.executable is not None:
            executable = override.executable
        if override.args is not None:
            args = override.args
        merged_env.update(override.env)

    if executable_override is not None:
        executable = executable_override

    return ResolvedRunner(
        command=command,
        executable=executable,
        args=(*args, *extra_args),
        env=frozendict(merged_env),
    )
