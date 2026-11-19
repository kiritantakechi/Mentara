"""Command assembly and cross-platform subprocess execution."""

import logging
import os
import shutil
import signal
import subprocess
import threading
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Final
lazy from collections.abc import Callable, Generator, Mapping, Sequence
lazy from types import FrameType

from mentara.config import PlatformKind
from mentara.errors import RunnerError
lazy from mentara.config import ResolvedProfile
lazy from mentara.overlay import MountedWorkspace

__all__ = [
    "LaunchResult",
    "LaunchSpec",
    "build_launch_spec",
    "execute_launch",
    "extract_command_binaries",
    "resolve_command_binary",
]

_LOGGER: Final = logging.getLogger(__name__)
_TERMINATE_TIMEOUT_SECONDS: Final[float] = 5.0

type _SignalHandler = Callable[[int, FrameType | None], object] | int | None


@dataclass(frozen=True, slots=True)
class LaunchSpec:
    """Concrete command vector, working directory, and environment."""

    argv: tuple[str, ...]
    cwd: Path
    env: frozendict[str, str]
    executable_path: Path
    required_binaries: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LaunchResult:
    """Outcome of executing a `LaunchSpec`."""

    spec: LaunchSpec
    returncode: int


def extract_command_binaries(command: Sequence[str]) -> tuple[str, ...]:
    """Extract every executable token from a wrapper command chain.

    The leading token and any token immediately following a `--`
    separator (such as `wrapper-a ... -- wrapper-b`) are treated as
    executables that must exist on the host.

    Args:
        command: Configured runner prefix command tokens.

    Returns:
        Ordered tuple of executable tokens in `command`.
    """
    binaries: list[str] = []
    expect_binary = True
    for arg in command:
        if arg == "--":
            expect_binary = True
            continue
        if expect_binary:
            binaries.append(arg)
            expect_binary = False
    return tuple(binaries)


def resolve_command_binary(
    program: str,
    *,
    path_env: str | None = None,
) -> str | None:
    """Resolve an executable name or explicit path to a host binary.

    Args:
        program: Binary name (searched on `PATH`) or explicit file path.
        path_env: Optional `PATH` override for `shutil.which`.

    Returns:
        Resolved binary path string if found, otherwise `None`.
    """
    if "/" in program or "\\" in program or Path(program).drive != "":
        return program if Path(program).exists() else None
    return shutil.which(program, path=path_env)


def build_launch_spec(
    profile: ResolvedProfile,
    workspace: MountedWorkspace,
    *,
    base_env: Mapping[str, str] | None = None,
) -> LaunchSpec:
    """Construct the command and environment for launching a profile.

    Args:
        profile: Resolved launcher profile.
        workspace: Active virtual workspace providing `merged_dir`.
        base_env: Base process environment; defaults to `os.environ`.

    Returns:
        An immutable `LaunchSpec` for dry-run inspection or execution.
    """
    executable_path = workspace.merged_dir / profile.runner.executable
    substitutions = {
        "MERGED_DIR": str(workspace.merged_dir),
        "BASE_DIR": str(profile.base_dir),
        "STATE_DIR": str(profile.state_dir),
        "PROFILE": profile.name,
    }

    env = dict(os.environ if base_env is None else base_env)
    for key, raw_value in profile.runner.env.items():
        env[key] = _expand_env_value(raw_value, substitutions)

    env["MENTARA_PROFILE"] = profile.name
    env["MENTARA_MERGED_DIR"] = str(workspace.merged_dir)
    env["MENTARA_BASE_DIR"] = str(profile.base_dir)

    argv = (
        *profile.runner.command,
        str(executable_path),
        *profile.runner.args,
    )
    return LaunchSpec(
        argv=argv,
        cwd=workspace.merged_dir,
        env=frozendict(env),
        executable_path=executable_path,
        required_binaries=extract_command_binaries(profile.runner.command),
    )


def execute_launch(spec: LaunchSpec) -> LaunchResult:
    """Run the configured game process and wait for exit.

    Installs a temporary `SIGTERM` handler on the main thread so clean
    termination unwinds callers (such as FUSE unmounts) after stopping
    the child process tree.

    Args:
        spec: Fully prepared `LaunchSpec`.

    Returns:
        `LaunchResult` carrying the child process exit status.

    Raises:
        RunnerError: If a wrapper binary or target executable is missing
            or cannot be spawned.
    """
    if not spec.executable_path.exists():
        raise RunnerError.missing_executable(spec.executable_path)

    path_env = spec.env.get("PATH")
    for program in spec.required_binaries:
        if resolve_command_binary(program, path_env=path_env) is None:
            raise RunnerError.missing_runner(program)
    _LOGGER.info("Launching %s in %s", spec.argv, spec.cwd)

    is_posix = PlatformKind.current().is_posix
    try:
        # User-configured command vector run directly without a shell.
        process = subprocess.Popen(  # noqa: S603 - argv assembled from validated config
            spec.argv,
            cwd=spec.cwd,
            env=dict(spec.env),
            start_new_session=is_posix,
        )
    except OSError as exc:
        raise RunnerError.spawn_failed(spec.argv, str(exc)) from exc

    try:
        with _sigterm_as_interrupt():
            returncode = process.wait()
    except KeyboardInterrupt:
        _terminate_process(process)
        raise

    return LaunchResult(spec=spec, returncode=returncode)


def _expand_env_value(raw: str, substitutions: Mapping[str, str]) -> str:
    expanded = Template(raw).safe_substitute(substitutions)
    if expanded.startswith(("~/", "~\\")) or expanded == "~":
        return str(Path(expanded).expanduser())
    return expanded


@contextmanager
def _sigterm_as_interrupt() -> Generator[None]:
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def _handle_sigterm(_signum: int, _frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    previous: _SignalHandler = signal.signal(
        signal.SIGTERM,
        _handle_sigterm,
    )
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    _LOGGER.warning("Interrupted; terminating child process %s", process.pid)
    is_posix = PlatformKind.current().is_posix
    killpg = getattr(os, "killpg", None)
    if is_posix and callable(killpg):
        with suppress(ProcessLookupError, OSError):
            killpg(process.pid, signal.SIGTERM)
    else:
        with suppress(OSError):
            process.terminate()

    try:
        process.wait(timeout=_TERMINATE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _LOGGER.warning("Child process %s did not exit; killing", process.pid)
        sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
        if is_posix and callable(killpg):
            with suppress(ProcessLookupError, OSError):
                killpg(process.pid, sigkill)
        else:
            with suppress(OSError):
                process.kill()
        process.wait()
