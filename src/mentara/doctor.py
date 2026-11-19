"""Cross-platform environment and Mental Omega overlay diagnostics."""

import os
import shutil
from configparser import ConfigParser
from configparser import Error as ConfigParserError
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from mentara.config import BackendKind, PlatformKind, ResolvedProfile
from mentara.errors import OverlayError
from mentara.overlay import plan_profile
from mentara.planner import EntryOrigin, OverlayPlan
from mentara.runner import extract_command_binaries

__all__ = [
    "Diagnostic",
    "DoctorReport",
    "Severity",
    "run_doctor",
]

_CORE_FILES: tuple[str, ...] = (
    "gamemd.exe",
    "Syringe.exe",
    "MentalOmegaClient.exe",
    "Ares.dll",
    "BINKW32.DLL",
    "Blowfish.dll",
    "ra2.mix",
    "ra2md.mix",
    "language.mix",
    "langmd.mix",
)
_CLIENT_DEFINITIONS_PATH = Path("Resources/ClientDefinitions.ini")
_CLIENT_EXE_FOLDED = "mentalomegaclient.exe"


class Severity(StrEnum):
    """Diagnostic outcome level."""

    OK = "ok"
    WARN = "warn"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Single health check result."""

    check: str
    severity: Severity
    message: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Aggregated diagnostic results for a launcher profile."""

    profile_name: str
    diagnostics: tuple[Diagnostic, ...]

    @property
    def has_errors(self) -> bool:
        """Return whether any diagnostic emitted `Severity.ERROR`."""
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def has_warnings(self) -> bool:
        """Return whether any diagnostic emitted `Severity.WARN`."""
        return any(item.severity is Severity.WARN for item in self.diagnostics)


def run_doctor(profile: ResolvedProfile) -> DoctorReport:
    """Inspect host tools, directories, and Mental Omega overlay rules.

    Args:
        profile: Resolved launcher profile to diagnose.

    Returns:
        A `DoctorReport` containing all check results.
    """
    diagnostics: list[Diagnostic] = []

    _check_base_dir(profile, diagnostics)
    _check_layers(profile, diagnostics)
    _check_backend(profile, diagnostics)
    _check_runner(profile, diagnostics)

    try:
        plan = plan_profile(profile)
    except OverlayError as exc:
        diagnostics.append(Diagnostic("overlay-plan", Severity.ERROR, str(exc)))
        return DoctorReport(
            profile_name=profile.name,
            diagnostics=tuple(diagnostics),
        )

    _check_core_files(plan, diagnostics)
    _check_target_executable(profile, plan, diagnostics)
    _check_case_collisions(plan, diagnostics)
    _check_forbidden_files(profile, plan, diagnostics)
    _check_syringeex_client_defs(profile, plan, diagnostics)

    return DoctorReport(
        profile_name=profile.name,
        diagnostics=tuple(diagnostics),
    )


def _check_base_dir(
    profile: ResolvedProfile,
    diagnostics: list[Diagnostic],
) -> None:
    if profile.base_dir.is_dir():
        diagnostics.append(
            Diagnostic(
                "base-dir",
                Severity.OK,
                f"Base game directory found: {profile.base_dir}",
            ),
        )
    else:
        diagnostics.append(
            Diagnostic(
                "base-dir",
                Severity.ERROR,
                f"Base game directory missing: {profile.base_dir}",
            ),
        )


def _check_layers(
    profile: ResolvedProfile,
    diagnostics: list[Diagnostic],
) -> None:
    if not profile.layers:
        diagnostics.append(
            Diagnostic(
                "layers",
                Severity.OK,
                "No overlay layers configured (vanilla base view).",
            ),
        )
        return

    for idx, layer in enumerate(profile.layers, start=1):
        if layer.is_dir():
            diagnostics.append(
                Diagnostic(
                    f"layer-{idx}",
                    Severity.OK,
                    f"Overlay layer found: {layer}",
                ),
            )
        else:
            diagnostics.append(
                Diagnostic(
                    f"layer-{idx}",
                    Severity.ERROR,
                    f"Overlay layer directory missing: {layer}",
                ),
            )


def _check_backend(
    profile: ResolvedProfile,
    diagnostics: list[Diagnostic],
) -> None:
    if profile.backend is BackendKind.SYMLINK:
        diagnostics.append(
            Diagnostic(
                "backend",
                Severity.OK,
                "Using symlink/hardlink staging backend (cross-platform).",
            ),
        )
        return

    if profile.platform is not PlatformKind.LINUX:
        diagnostics.append(
            Diagnostic(
                "backend",
                Severity.ERROR,
                f"Backend {profile.backend.value!r} requires Linux FUSE; "
                f"use backend = 'symlink' on {profile.platform.value}.",
            ),
        )
        return

    fuse_bin = shutil.which("fuse-overlayfs")
    unmount_bin = shutil.which("fusermount3") or shutil.which("fusermount")
    fuse_device = Path("/dev/fuse")

    if fuse_bin is None:
        diagnostics.append(
            Diagnostic(
                "backend",
                Severity.ERROR,
                "fuse-overlayfs not found on PATH; install it or use "
                "backend = 'symlink'.",
            ),
        )
        return
    if unmount_bin is None:
        diagnostics.append(
            Diagnostic(
                "backend",
                Severity.ERROR,
                "fusermount3/fusermount not found on PATH.",
            ),
        )
        return
    if not fuse_device.exists():
        diagnostics.append(
            Diagnostic(
                "backend",
                Severity.WARN,
                "/dev/fuse is not visible in this environment.",
            ),
        )
        return

    diagnostics.append(
        Diagnostic(
            "backend",
            Severity.OK,
            f"fuse-overlayfs ready ({fuse_bin}, unmount via {unmount_bin}).",
        ),
    )


def _check_runner(
    profile: ResolvedProfile,
    diagnostics: list[Diagnostic],
) -> None:
    binaries = extract_command_binaries(profile.runner.command)
    if not binaries:
        diagnostics.append(
            Diagnostic(
                "runner",
                Severity.OK,
                "Direct native execution configured.",
            ),
        )
        return

    path_env = profile.runner.env.get("PATH") or os.environ.get("PATH")
    resolved_bins: list[str] = []
    for program in binaries:
        is_path = "/" in program or "\\" in program or Path(program).drive != ""
        resolved = (
            program
            if is_path and Path(program).exists()
            else shutil.which(program, path=path_env)
        )
        if resolved is None:
            diagnostics.append(
                Diagnostic(
                    "runner",
                    Severity.ERROR,
                    f"Runner executable not found: {program}",
                ),
            )
            return
        resolved_bins.append(resolved)

    chain = " -> ".join(resolved_bins)
    diagnostics.append(
        Diagnostic(
            "runner",
            Severity.OK,
            f"Runner chain ready: {chain}",
        ),
    )


def _check_core_files(
    plan: OverlayPlan,
    diagnostics: list[Diagnostic],
) -> None:
    missing = [
        name for name in _CORE_FILES if plan.lookup_case_insensitive(Path(name)) is None
    ]
    if missing:
        diagnostics.append(
            Diagnostic(
                "core-files",
                Severity.WARN,
                f"Missing expected Mental Omega files: {', '.join(missing)}",
            ),
        )
    else:
        diagnostics.append(
            Diagnostic(
                "core-files",
                Severity.OK,
                f"All {len(_CORE_FILES)} core Mental Omega files resolved.",
            ),
        )


def _check_target_executable(
    profile: ResolvedProfile,
    plan: OverlayPlan,
    diagnostics: list[Diagnostic],
) -> None:
    entry = plan.lookup_case_insensitive(Path(profile.runner.executable))
    if entry is None:
        diagnostics.append(
            Diagnostic(
                "executable",
                Severity.ERROR,
                f"Configured executable {profile.runner.executable!r} "
                "is absent from the merged overlay.",
            ),
        )
    else:
        diagnostics.append(
            Diagnostic(
                "executable",
                Severity.OK,
                f"Target executable resolved: {entry.relative_path} "
                f"({entry.layer_label}).",
            ),
        )


def _check_case_collisions(
    plan: OverlayPlan,
    diagnostics: list[Diagnostic],
) -> None:
    if not plan.case_collisions:
        diagnostics.append(
            Diagnostic(
                "case-collisions",
                Severity.OK,
                "No Windows case-only path collisions detected.",
            ),
        )
        return

    for collision in plan.case_collisions:
        variants = ", ".join(
            f"{path.as_posix()} ({label})" for path, label in collision.variants
        )
        diagnostics.append(
            Diagnostic(
                "case-collisions",
                Severity.WARN,
                f"Case-only path collision across layers: {variants}",
            ),
        )


def _check_forbidden_files(
    profile: ResolvedProfile,
    plan: OverlayPlan,
    diagnostics: list[Diagnostic],
) -> None:
    if Path(profile.runner.executable).name.casefold() != _CLIENT_EXE_FOLDED:
        return

    client_defs = plan.lookup_case_insensitive(_CLIENT_DEFINITIONS_PATH)
    if client_defs is None:
        return

    forbidden = _read_forbidden_files(client_defs.source_path)
    if not forbidden:
        return

    flagged: list[str] = []
    for entry in plan.overrides():
        if entry.origin is not EntryOrigin.LAYER:
            continue
        if entry.relative_path.as_posix().casefold() in forbidden:
            flagged.append(entry.relative_path.as_posix())

    if flagged:
        names = ", ".join(sorted(flagged))
        diagnostics.append(
            Diagnostic(
                "forbidden-files",
                Severity.WARN,
                f"Overlay provides files blocked by ClientDefinitions.ini "
                f"ForbiddenFiles ({names}). Override "
                f"Resources/ClientDefinitions.ini or launch via Syringe.exe.",
            ),
        )


def _check_syringeex_client_defs(
    profile: ResolvedProfile,
    plan: OverlayPlan,
    diagnostics: list[Diagnostic],
) -> None:
    if Path(profile.runner.executable).name.casefold() != _CLIENT_EXE_FOLDED:
        return

    syringe = plan.lookup_case_insensitive(Path("Syringe.exe"))
    client_defs = plan.lookup_case_insensitive(_CLIENT_DEFINITIONS_PATH)
    if syringe is None or client_defs is None:
        return
    if not _is_syringeex_binary(syringe.source_path):
        return

    parser = _parse_ini(client_defs.source_path)
    if parser is None:
        return

    launcher_exe = parser.get(
        "Settings",
        "GameLauncherExecutableName",
        fallback="",
    ).strip()
    extra_params = parser.get(
        "Settings",
        "ExtraCommandLineParams",
        fallback="",
    )
    if launcher_exe or "--args=" not in extra_params:
        diagnostics.append(
            Diagnostic(
                "syringeex-client-defs",
                Severity.WARN,
                "SyringeEx detected, but Resources/ClientDefinitions.ini "
                "still uses legacy Syringe syntax. Set "
                "GameExecutableNames=Syringe.exe, clear "
                "GameLauncherExecutableName, and wrap -SPAWN in "
                'ExtraCommandLineParams=gamemd.exe --args="-SPAWN ...".',
            ),
        )
        return

    diagnostics.append(
        Diagnostic(
            "syringeex-client-defs",
            Severity.OK,
            "Resources/ClientDefinitions.ini is migrated for SyringeEx.",
        ),
    )


def _is_syringeex_binary(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return b"SyringeEx" in data


def _read_forbidden_files(path: Path) -> frozenset[str]:
    parser = _parse_ini(path)
    if parser is None:
        return frozenset()
    raw = parser.get("Settings", "ForbiddenFiles", fallback="")
    return frozenset(item.strip().casefold() for item in raw.split(",") if item.strip())


def _parse_ini(path: Path) -> ConfigParser | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    parser = ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(text)
    except ConfigParserError:
        return None
    return parser
