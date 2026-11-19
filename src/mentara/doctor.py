"""Cross-platform host environment and virtual overlay diagnostics."""

import os
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import assert_never

from mentara.config import BackendKind, PlatformKind, ResolvedProfile
from mentara.errors import OverlayError
from mentara.overlay import plan_profile
from mentara.planner import OverlayPlan, validate_synthesized_entry
from mentara.runner import (
    extract_command_binaries,
    resolve_command_binary,
)

__all__ = [
    "Diagnostic",
    "DoctorReport",
    "Severity",
    "run_doctor",
]


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
    """Inspect host tools, directories, and virtual overlay integrity.

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

    _check_target_executable(profile, plan, diagnostics)
    _check_case_collisions(plan, diagnostics)
    _check_synthesized_entries(plan, diagnostics)

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
                f"Base directory found: {profile.base_dir}",
            ),
        )
    else:
        diagnostics.append(
            Diagnostic(
                "base-dir",
                Severity.ERROR,
                f"Base directory missing: {profile.base_dir}",
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
                "No overlay layers configured (base view only).",
            ),
        )
        return

    for index, layer in enumerate(profile.layers, start=1):
        if layer.is_dir():
            diagnostics.append(
                Diagnostic(
                    f"layer-{index}",
                    Severity.OK,
                    f"Overlay layer found: {layer}",
                ),
            )
        else:
            diagnostics.append(
                Diagnostic(
                    f"layer-{index}",
                    Severity.ERROR,
                    f"Overlay layer directory missing: {layer}",
                ),
            )


def _check_backend(
    profile: ResolvedProfile,
    diagnostics: list[Diagnostic],
) -> None:
    match profile.backend:
        case BackendKind.SYMLINK:
            diagnostics.append(
                Diagnostic(
                    "backend",
                    Severity.OK,
                    "Using symlink/hardlink staging backend (cross-platform).",
                ),
            )
            return
        case BackendKind.FUSE_OVERLAYFS:
            pass
        case _:
            assert_never(profile.backend)

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
        resolved = resolve_command_binary(program, path_env=path_env)
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


def _check_target_executable(
    profile: ResolvedProfile,
    plan: OverlayPlan,
    diagnostics: list[Diagnostic],
) -> None:
    if not profile.runner.executable:
        diagnostics.append(
            Diagnostic(
                "executable",
                Severity.ERROR,
                "No target executable configured for runner.",
            ),
        )
        return

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
                "No case-only path collisions detected.",
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


def _check_synthesized_entries(
    plan: OverlayPlan,
    diagnostics: list[Diagnostic],
) -> None:
    synthesized = plan.synthesized_entries()
    if not synthesized:
        return

    had_error = False
    for entry in synthesized:
        try:
            validate_synthesized_entry(entry, context=plan.mix_context)
        except OverlayError as exc:
            had_error = True
            diagnostics.append(
                Diagnostic(
                    "patches",
                    Severity.ERROR,
                    str(exc),
                ),
            )

    if not had_error:
        message = (
            f"All {len(synthesized)} synthesized/patched file(s) validated cleanly."
        )
        diagnostics.append(Diagnostic("patches", Severity.OK, message))
