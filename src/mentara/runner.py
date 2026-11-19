"""Command assembly and subprocess execution for game runners."""

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
lazy from collections.abc import Callable, Generator, Mapping
lazy from types import FrameType

from mentara.errors import RunnerError
lazy from mentara.config import ResolvedProfile
lazy from mentara.overlay import MountedWorkspace

__all__ = [
    "LaunchResult",
    "LaunchSpec",
    "build_launch_spec",
    "execute_launch",
]

_LOGGER = logging.getLogger(__name__)
_TERMINATE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class LaunchSpec:
    """Concrete command vector, working directory, and environment."""

    argv: tuple[str, ...]
    cwd: Path
    env: frozendict[str, str]
    executable_path: Path


@dataclass(frozen=True, slots=True)
class LaunchResult:
    """Outcome of executing a `LaunchSpec`."""

    spec: LaunchSpec
    returncode: int


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
    )


def execute_launch(spec: LaunchSpec) -> LaunchResult:
    """Run the configured game process and wait for exit.

    Installs a temporary `SIGTERM` handler on the main thread so clean
    termination unwinds callers (such as FUSE unmounts) after stopping
    the child process group.

    Args:
        spec: Fully prepared `LaunchSpec`.

    Returns:
        `LaunchResult` carrying the child process exit status.

    Raises:
        RunnerError: If the runner or target executable is missing or
            cannot be spawned.
    """
    if not spec.executable_path.exists():
        raise RunnerError.missing_executable(spec.executable_path)

    _ensure_runner_exists(spec.argv[0], path_env=spec.env.get("PATH"))
    _LOGGER.info("Launching %s in %s", spec.argv, spec.cwd)

    try:
        # User-configured command vector run directly without a shell.
        process = subprocess.Popen(  # noqa: S603
            spec.argv,
            cwd=spec.cwd,
            env=dict(spec.env),
            start_new_session=True,
        )
    except OSError as exc:
        raise RunnerError.spawn_failed(spec.argv, str(exc)) from exc

    try:
        with _sigterm_as_interrupt():
            returncode = process.wait()
    except KeyboardInterrupt:
        _terminate_process_group(process)
        raise

    return LaunchResult(spec=spec, returncode=returncode)


def _expand_env_value(raw: str, substitutions: Mapping[str, str]) -> str:
    expanded = Template(raw).safe_substitute(substitutions)
    if expanded.startswith("~/") or expanded == "~":
        return str(Path(expanded).expanduser())
    return expanded


def _ensure_runner_exists(program: str, *, path_env: str | None) -> None:
    if "/" in program:
        if not Path(program).exists():
            raise RunnerError.missing_runner(program)
        return
    if shutil.which(program, path=path_env) is None:
        raise RunnerError.missing_runner(program)


@contextmanager
def _sigterm_as_interrupt() -> Generator[None]:
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def _handle_sigterm(_signum: int, _frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    previous: Callable[[int, FrameType | None], object] | int | None = signal.signal(
        signal.SIGTERM,
        _handle_sigterm,
    )
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    _LOGGER.warning("Interrupted; terminating process group %s", process.pid)
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=_TERMINATE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _LOGGER.warning(
            "Process group %s did not exit; sending SIGKILL",
            process.pid,
        )
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
