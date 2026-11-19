"""Command-line interface for the Mentara Mental Omega launcher."""

import argparse
import json
import logging
import shlex
import sys
from pathlib import Path
from typing import TextIO
lazy from collections.abc import Sequence

from mentara.config import (
    BackendKind,
    MentaraConfig,
    PlatformKind,
    ProfileOverrides,
    ResolvedProfile,
    find_config_path,
    load_config,
    resolve_profile,
)
from mentara.doctor import run_doctor
from mentara.errors import ConfigError, MentaraError
from mentara.overlay import (
    MountedWorkspace,
    activate_workspace,
    get_backend,
    plan_profile,
)
from mentara.planner import matches_any_pattern
from mentara.runner import build_launch_spec, execute_launch

__all__ = ["build_parser", "main"]

_EXIT_OK = 0
_EXIT_ERROR = 1
_EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level CLI argument parser.

    Returns:
        Configured `argparse.ArgumentParser` instance.
    """
    parser = argparse.ArgumentParser(
        prog="mentara",
        description=(
            "Cross-platform virtual overlay launcher for Mental Omega "
            "decoupling base game files from custom INI/DLL layers."
        ),
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help="Path to mentara.toml (auto-discovered upwards by default).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging on stderr.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    launch_parser = subparsers.add_parser(
        "launch",
        help="Mount the virtual workspace, run Mental Omega, then clean up.",
    )
    _add_profile_flags(launch_parser)
    launch_parser.add_argument(
        "--exe",
        default=None,
        help="Override target executable (e.g. Syringe.exe).",
    )
    launch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show resolved paths, layers, and command without launching.",
    )
    launch_parser.add_argument(
        "extra_args",
        nargs=argparse.REMAINDER,
        help="Additional arguments forwarded after '--'.",
    )

    mount_parser = subparsers.add_parser(
        "mount",
        help="Mount or stage the virtual workspace without launching.",
    )
    _add_profile_flags(mount_parser)

    unmount_parser = subparsers.add_parser(
        "unmount",
        help="Unmount or tear down an active virtual workspace.",
    )
    _add_profile_flags(unmount_parser)
    unmount_parser.add_argument(
        "--lazy",
        action="store_true",
        help="Use lazy FUSE unmount (fusermount3 -uz) if busy.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect resolved overlay files, shadows, and collisions.",
    )
    _add_profile_flags(inspect_parser)
    inspect_parser.add_argument(
        "-f",
        "--filter",
        action="append",
        default=[],
        dest="filters",
        help="Glob filter (repeatable, e.g. -f '*.ini' -f '*.dll').",
    )
    inspect_parser.add_argument(
        "--all",
        action="store_true",
        dest="show_all",
        help="Show base files as well as overlay/state overrides.",
    )
    inspect_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON output.",
    )

    subparsers.add_parser(
        "profiles",
        help="List all configured profiles in mentara.toml.",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check host tools, base files, layers, and MO pitfalls.",
    )
    _add_profile_flags(doctor_parser)

    init_layer_parser = subparsers.add_parser(
        "init-layer",
        help="Create a new overlay layer folder scaffold.",
    )
    init_layer_parser.add_argument(
        "name",
        help="Layer directory name (e.g. 'phobos' or 'balance-patch').",
    )
    init_layer_parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        dest="parent_dir",
        help="Parent directory for layers (defaults to <config_dir>/overlays).",
    )

    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the Mentara CLI and return a process exit code.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.
        stdout: Output stream; defaults to `sys.stdout`.
        stderr: Error and log stream; defaults to `sys.stderr`.

    Returns:
        Zero on success, non-zero on failure or interruption.
    """
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    _configure_logging(verbose=bool(args.verbose), stream=err)

    try:
        return _dispatch(args, stdout=out, stderr=err)
    except MentaraError as exc:
        err.write(f"error: {exc}\n")
        return _EXIT_ERROR
    except KeyboardInterrupt:
        err.write("Interrupted.\n")
        return _EXIT_INTERRUPTED


def _add_profile_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-p",
        "--profile",
        default=None,
        help="Profile name from mentara.toml.",
    )
    parser.add_argument(
        "-b",
        "--backend",
        type=BackendKind,
        choices=tuple(BackendKind),
        default=None,
        help="Override overlay backend.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Enable debug logging on stderr.",
    )


def _configure_logging(*, verbose: bool, stream: TextIO) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger("mentara")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def _dispatch(
    args: argparse.Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    subcommand = str(args.subcommand)
    config_path = find_config_path(args.config)
    config = load_config(config_path)
    config_dir = config_path.parent

    match subcommand:
        case "profiles":
            exit_code = _cmd_profiles(config, config_dir=config_dir, stdout=stdout)
        case "init-layer":
            exit_code = _cmd_init_layer(
                name=str(args.name),
                parent_dir=args.parent_dir or (config_dir / "overlays"),
                stdout=stdout,
            )
        case "launch":
            extra = _strip_leading_dash_dash(tuple(args.extra_args))
            profile = resolve_profile(
                config,
                config_dir=config_dir,
                profile_name=args.profile,
                overrides=ProfileOverrides(
                    backend=args.backend,
                    executable=args.exe,
                    extra_args=extra,
                ),
            )
            exit_code = _cmd_launch(
                profile,
                dry_run=bool(args.dry_run),
                stdout=stdout,
            )
        case "mount":
            profile = _resolve_from_args(config, config_dir, args)
            exit_code = _cmd_mount(profile, stdout=stdout)
        case "unmount":
            profile = _resolve_from_args(config, config_dir, args)
            exit_code = _cmd_unmount(
                profile,
                lazy=bool(args.lazy),
                stdout=stdout,
            )
        case "inspect":
            profile = _resolve_from_args(config, config_dir, args)
            exit_code = _cmd_inspect(
                profile,
                filters=tuple(args.filters),
                show_all=bool(args.show_all),
                as_json=bool(args.as_json),
                stdout=stdout,
            )
        case "doctor":
            profile = _resolve_from_args(config, config_dir, args)
            exit_code = _cmd_doctor(profile, stdout=stdout, stderr=stderr)
        case _:
            stderr.write(f"error: unknown subcommand {subcommand!r}\n")
            exit_code = _EXIT_ERROR
    return exit_code


def _resolve_from_args(
    config: MentaraConfig,
    config_dir: Path,
    args: argparse.Namespace,
) -> ResolvedProfile:
    return resolve_profile(
        config,
        config_dir=config_dir,
        profile_name=args.profile,
        overrides=ProfileOverrides(backend=args.backend),
    )


def _strip_leading_dash_dash(args: tuple[str, ...]) -> tuple[str, ...]:
    if args and args[0] == "--":
        return args[1:]
    return args


def _cmd_profiles(
    config: MentaraConfig,
    *,
    config_dir: Path,
    stdout: TextIO,
) -> int:
    platform = PlatformKind.current()
    lines: list[str] = []
    for name in sorted(config.profiles):
        resolved = resolve_profile(
            config,
            config_dir=config_dir,
            profile_name=name,
            platform=platform,
        )
        raw_profile = config.profiles[name]
        marker = "*" if name == config.default_profile else " "
        layers = ", ".join(raw_profile.layers) if raw_profile.layers else "(vanilla)"
        desc = f" — {resolved.description}" if resolved.description else ""
        lines.append(
            f"{marker} {name} [{resolved.platform.value}:{resolved.backend.value}] "
            f"exe={resolved.runner.executable} layers=[{layers}]{desc}\n"
        )
    stdout.write("".join(lines))
    return _EXIT_OK


def _cmd_init_layer(
    *,
    name: str,
    parent_dir: Path,
    stdout: TextIO,
) -> int:
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ConfigError.invalid_layer_name(name)

    target = parent_dir.expanduser().resolve() / name
    target.mkdir(parents=True, exist_ok=True)
    (target / ".gitkeep").touch(exist_ok=True)

    stdout.write(f"Created overlay layer directory: {target}\n")
    return _EXIT_OK


def _cmd_launch(
    profile: ResolvedProfile,
    *,
    dry_run: bool,
    stdout: TextIO,
) -> int:
    if dry_run:
        plan = plan_profile(profile)
        preview_workspace = MountedWorkspace(
            profile_name=profile.name,
            backend=profile.backend,
            merged_dir=profile.runtime_dir / "merged",
            upper_dir=(profile.state_dir / "upper" if profile.persist_state else None),
            base_dir=profile.base_dir,
            layers=profile.layers,
        )
        spec = build_launch_spec(profile, preview_workspace)
        overrides = plan.overrides()
        env_lines = [
            f"  {key}={value}" for key, value in sorted(profile.runner.env.items())
        ]
        layer_lines = (
            [f"  {layer}" for layer in profile.layers]
            if profile.layers
            else ["  (none)"]
        )
        persist_label = "yes" if profile.persist_state else "no"
        summary = [
            f"Profile:    {profile.name}",
            f"Platform:   {profile.platform.value}",
            f"Backend:    {profile.backend.value}",
            f"Base dir:   {profile.base_dir}",
            f"Merged dir: {preview_workspace.merged_dir}",
            f"State dir:  {profile.state_dir} (persist={persist_label})",
            f"Overrides:  {len(overrides)} files ({len(plan.entries)} total)",
            "Layers (low -> high):",
            *layer_lines,
            "Runner env overrides:",
            *(env_lines or ["  (none)"]),
            f"Command:    {shlex.join(spec.argv)}",
        ]
        stdout.write("\n".join(summary) + "\n")
        return _EXIT_OK

    with activate_workspace(profile) as workspace:
        spec = build_launch_spec(profile, workspace)
        result = execute_launch(spec)
    return result.returncode


def _cmd_mount(profile: ResolvedProfile, *, stdout: TextIO) -> int:
    backend = get_backend(profile.backend)
    workspace = backend.mount(profile)
    stdout.write(f"Mounted [{profile.backend.value}] {workspace.merged_dir}\n")
    return _EXIT_OK


def _cmd_unmount(
    profile: ResolvedProfile,
    *,
    lazy: bool,
    stdout: TextIO,
) -> int:
    backend = get_backend(profile.backend)
    backend.unmount(profile, lazy=lazy)
    stdout.write(
        f"Unmounted [{profile.backend.value}] {profile.runtime_dir / 'merged'}\n"
    )
    return _EXIT_OK


def _cmd_inspect(
    profile: ResolvedProfile,
    *,
    filters: tuple[str, ...],
    show_all: bool,
    as_json: bool,
    stdout: TextIO,
) -> int:
    plan = plan_profile(profile)
    selected = plan.entries if show_all else plan.overrides()
    if filters:
        selected = tuple(
            entry
            for entry in selected
            if matches_any_pattern(entry.relative_path, filters)
        )

    if as_json:
        payload = {
            "profile": profile.name,
            "platform": profile.platform.value,
            "backend": profile.backend.value,
            "base_dir": str(profile.base_dir),
            "layers": [str(layer) for layer in profile.layers],
            "total_files": len(plan.entries),
            "override_count": len(plan.overrides()),
            "entries": [
                {
                    "path": entry.relative_path.as_posix(),
                    "origin": entry.origin.value,
                    "layer": entry.layer_label,
                    "materialization": entry.materialization.value,
                    "shadowed_from": list(entry.shadowed_from),
                }
                for entry in selected
            ],
            "case_collisions": [
                {
                    "folded_path": collision.folded_path,
                    "variants": [
                        {"path": path.as_posix(), "layer": label}
                        for path, label in collision.variants
                    ],
                }
                for collision in plan.case_collisions
            ],
        }
        stdout.write(json.dumps(payload, indent=2) + "\n")
        return _EXIT_OK

    lines = [
        f"Profile: {profile.name} ({profile.platform.value}:{profile.backend.value})",
        f"Files:   {len(selected)} shown / {len(plan.entries)} total",
    ]
    for entry in selected:
        shadow = (
            f" (shadows {', '.join(entry.shadowed_from)})"
            if entry.shadowed_from
            else ""
        )
        lines.append(
            f"  [{entry.layer_label}] [{entry.materialization.value}] "
            f"{entry.relative_path.as_posix()}{shadow}"
        )
    if plan.case_collisions:
        lines.append("Case collisions:")
        for collision in plan.case_collisions:
            variants = ", ".join(
                f"{path.as_posix()} ({label})" for path, label in collision.variants
            )
            lines.append(f"  ! {variants}")
    stdout.write("\n".join(lines) + "\n")
    return _EXIT_OK


def _cmd_doctor(
    profile: ResolvedProfile,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    report = run_doctor(profile)
    header = (
        f"Doctor report for profile '{report.profile_name}' ({profile.platform.value}):"
    )
    lines = [header]
    for item in report.diagnostics:
        tag = item.severity.value.upper()
        lines.append(f"  [{tag:5}] {item.check}: {item.message}")
    stdout.write("\n".join(lines) + "\n")
    if report.has_errors:
        stderr.write("Doctor detected errors that block launching.\n")
        return _EXIT_ERROR
    return _EXIT_OK
