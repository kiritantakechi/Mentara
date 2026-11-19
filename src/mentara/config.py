"""Configuration schema, TOML loading, and profile resolution."""

import os
import tempfile
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Self

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


class BackendKind(StrEnum):
    """Supported virtual workspace materialisation backends."""

    FUSE_OVERLAYFS = "fuse-overlayfs"
    SYMLINK = "symlink"


class RunnerConfig(BaseModel):
    """Default launcher runtime command and environment settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: tuple[str, ...] = ("umu-run",)
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
    """Per-profile overrides applied on top of global `RunnerConfig`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: tuple[str, ...] | None = None
    executable: str | None = None
    args: tuple[str, ...] | None = None
    env: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_executable(self) -> Self:
        if self.executable is not None and not self.executable.strip():
            msg = "profile runner.executable must not be empty"
            raise ValueError(msg)
        return self


class ProfileConfig(BaseModel):
    """Declarative overlay profile for layers and runtime options."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str = ""
    layers: tuple[str, ...] = ()
    backend: BackendKind | None = None
    persist_state: bool = True
    copy_patterns: tuple[str, ...] | None = None
    runner: RunnerOverrideConfig | None = None


class MentaraConfig(BaseModel):
    """Top-level `mentara.toml` schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_dir: str = ".."
    runtime_dir: str | None = None
    state_dir: str | None = None
    default_profile: str = "default"
    backend: BackendKind = BackendKind.FUSE_OVERLAYFS
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE
    copy_patterns: tuple[str, ...] = DEFAULT_COPY_PATTERNS
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    profiles: dict[str, ProfileConfig] = Field(
        default_factory=lambda: {"default": ProfileConfig()},
    )

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
    overrides: ProfileOverrides | None = None,
) -> ResolvedProfile:
    """Resolve a named profile into concrete, validated paths.

    Args:
        config: Validated top-level configuration.
        config_dir: Directory containing `mentara.toml`.
        profile_name: Profile name; defaults to `default_profile`.
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

    applied = ProfileOverrides() if overrides is None else overrides
    resolved_config_dir = config_dir.expanduser().resolve()
    base_dir = _resolve_path(config.base_dir, anchor=resolved_config_dir)
    layers = _resolve_layers(
        profile.layers,
        anchor=resolved_config_dir,
        base_dir=base_dir,
    )

    runtime_root = (
        _resolve_path(config.runtime_dir, anchor=resolved_config_dir)
        if config.runtime_dir is not None and config.runtime_dir != ""
        else _default_runtime_root()
    )
    state_root = (
        _resolve_path(config.state_dir, anchor=resolved_config_dir)
        if config.state_dir is not None and config.state_dir != ""
        else _default_state_root()
    )
    runtime_dir = runtime_root / chosen_name
    state_dir = state_root / chosen_name

    _ensure_disjoint_workspace(
        runtime_dir=runtime_dir,
        state_dir=state_dir,
        base_dir=base_dir,
        layers=layers,
    )

    runner = _merge_runner(
        base=config.runner,
        override=profile.runner,
        executable_override=applied.executable,
        extra_args=applied.extra_args,
    )
    backend = applied.backend or profile.backend or config.backend
    copy_patterns = (
        profile.copy_patterns
        if profile.copy_patterns is not None
        else config.copy_patterns
    )

    return ResolvedProfile(
        name=chosen_name,
        description=profile.description,
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
    raw_layers: tuple[str, ...],
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


def _default_runtime_root() -> Path:
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime is not None and xdg_runtime != "":
        return (Path(xdg_runtime).expanduser() / "mentara").resolve()
    return (Path(tempfile.gettempdir()) / f"mentara-{os.getuid()}").resolve()


def _default_state_root() -> Path:
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state is not None and xdg_state != "":
        return (Path(xdg_state).expanduser() / "mentara").resolve()
    return (Path.home() / ".local" / "state" / "mentara").resolve()


def _ensure_disjoint_workspace(
    *,
    runtime_dir: Path,
    state_dir: Path,
    base_dir: Path,
    layers: tuple[Path, ...],
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


def _merge_runner(
    *,
    base: RunnerConfig,
    override: RunnerOverrideConfig | None,
    executable_override: str | None,
    extra_args: tuple[str, ...],
) -> ResolvedRunner:
    command = base.command
    executable = base.executable
    args = base.args
    merged_env = dict(base.env)

    if override is not None:
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
