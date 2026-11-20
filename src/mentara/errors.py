"""Structured exception hierarchy for Mentara."""

from typing import Self
lazy from collections.abc import Sequence
lazy from pathlib import Path

__all__ = [
    "AssetError",
    "ConfigError",
    "MentaraError",
    "MountError",
    "OverlayError",
    "RunnerError",
]


class MentaraError(Exception):
    """Base exception for all Mentara launcher failures."""


class ConfigError(MentaraError):
    """Raised when launcher configuration cannot be loaded or used."""

    @classmethod
    def missing_file(cls, path: Path) -> Self:
        """Build an error for a missing configuration file.

        Args:
            path: Expected path to the configuration file.

        Returns:
            A `ConfigError` describing the missing file.
        """
        return cls(f"Configuration file not found: {path}")

    @classmethod
    def unreadable_file(cls, path: Path, detail: str) -> Self:
        """Build an error for an unreadable configuration file.

        Args:
            path: Path that could not be read.
            detail: Underlying OS or decode error detail.

        Returns:
            A `ConfigError` describing the read failure.
        """
        return cls(f"Failed to read configuration {path}: {detail}")

    @classmethod
    def invalid_toml(cls, path: Path, detail: str) -> Self:
        """Build an error for malformed TOML syntax.

        Args:
            path: Configuration file containing invalid TOML.
            detail: Parser failure detail.

        Returns:
            A `ConfigError` describing the syntax error.
        """
        return cls(f"Invalid TOML in {path}: {detail}")

    @classmethod
    def validation_failed(cls, path: Path, detail: str) -> Self:
        """Build an error for schema validation failure.

        Args:
            path: Configuration file that failed schema validation.
            detail: Formatted validation error summary.

        Returns:
            A `ConfigError` describing the invalid schema.
        """
        return cls(f"Invalid configuration in {path}:\n{detail}")

    @classmethod
    def unknown_profile(cls, name: str, available: Sequence[str]) -> Self:
        """Build an error when a requested profile does not exist.

        Args:
            name: Profile name requested by the caller.
            available: Configured profile names.

        Returns:
            A `ConfigError` listing available profiles.
        """
        options = ", ".join(sorted(available)) or "(none)"
        return cls(f"Unknown profile {name!r}. Available profiles: {options}")

    @classmethod
    def overlapping_paths(
        cls,
        role: str,
        target: Path,
        other_role: str,
        other: Path,
    ) -> Self:
        """Build an error when runtime or state paths overlap sources.

        Args:
            role: Label for the runtime or state directory.
            target: Resolved path of the runtime or state directory.
            other_role: Label for the conflicting directory.
            other: Resolved path of the conflicting directory.

        Returns:
            A `ConfigError` describing the forbidden overlap.
        """
        return cls(f"{role} ({target}) must not overlap with {other_role} ({other})")

    @classmethod
    def duplicate_layer(cls, layer: Path) -> Self:
        """Build an error when a profile lists the same layer twice.

        Args:
            layer: Resolved duplicate layer path.

        Returns:
            A `ConfigError` naming the duplicated layer.
        """
        return cls(f"Profile lists duplicate overlay layer: {layer}")

    @classmethod
    def layer_equals_base(cls, layer: Path) -> Self:
        """Build an error when a layer points directly at `base_dir`.

        Args:
            layer: Resolved path identical to `base_dir`.

        Returns:
            A `ConfigError` rejecting the redundant layer.
        """
        return cls(f"Overlay layer must not equal base_dir: {layer}")


class OverlayError(MentaraError):
    """Raised when resolving or materialising an overlay fails."""

    @classmethod
    def missing_directory(cls, role: str, path: Path) -> Self:
        """Build an error when a required source directory is absent.

        Args:
            role: Human label such as `base_dir` or `overlay layer`.
            path: Missing or non-directory path.

        Returns:
            An `OverlayError` naming the missing directory.
        """
        return cls(f"Missing {role} directory: {path}")

    @classmethod
    def missing_file(cls, role: str, path: Path) -> Self:
        """Build an error when a required source file is absent.

        Args:
            role: Human label such as `MIX archive` or `overlay file`.
            path: Missing or non-file path.

        Returns:
            An `OverlayError` naming the missing file.
        """
        return cls(f"Missing {role} file: {path}")

    @classmethod
    def unreadable_file(cls, path: Path, detail: str) -> Self:
        """Build an error when an overlay source file cannot be read.

        Args:
            path: File path that could not be opened or read.
            detail: Underlying OS error detail.

        Returns:
            An `OverlayError` describing the read failure.
        """
        return cls(f"Failed to read overlay file {path}: {detail}")

    @classmethod
    def missing_virtual_file(cls, path: Path) -> Self:
        """Build an error when a virtual file is absent from the plan.

        Args:
            path: Requested relative path inside the virtual workspace.

        Returns:
            An `OverlayError` naming the missing virtual file.
        """
        return cls(f"Virtual file not found in overlay plan: {path.as_posix()}")

    @classmethod
    def non_empty_target(cls, path: Path) -> Self:
        """Build an error when a mount or staging target is non-empty.

        Args:
            path: Target merged directory path.

        Returns:
            An `OverlayError` refusing to clobber existing files.
        """
        return cls(f"Virtual directory target already contains files: {path}")

    @classmethod
    def already_active(cls, path: Path) -> Self:
        """Build an error when a profile workspace is already active.

        Args:
            path: Active merged directory path.

        Returns:
            An `OverlayError` telling the caller to unmount first.
        """
        return cls(f"Virtual workspace is already active at: {path}")

    @classmethod
    def not_active(cls, path: Path) -> Self:
        """Build an error when unmounting an inactive workspace.

        Args:
            path: Expected merged directory path.

        Returns:
            An `OverlayError` noting there is nothing to unmount.
        """
        return cls(f"No active virtual workspace at: {path}")

    @classmethod
    def corrupt_manifest(cls, path: Path, detail: str) -> Self:
        """Build an error when a staging manifest cannot be parsed.

        Args:
            path: Manifest file path.
            detail: Parse or validation error message.

        Returns:
            An `OverlayError` describing the corrupt manifest.
        """
        return cls(f"Corrupt staging manifest at {path}: {detail}")

    @classmethod
    def invalid_manifest_schema(cls, path: Path) -> Self:
        """Build an error when a staging manifest has invalid fields.

        Args:
            path: Manifest file path.

        Returns:
            An `OverlayError` describing the schema mismatch.
        """
        return cls(f"Staging manifest has invalid schema: {path}")

    @classmethod
    def invalid_patch(cls, path: Path, detail: str) -> Self:
        """Build an error when a text or INI patch file is malformed.

        Args:
            path: Patch file path.
            detail: Syntax or schema failure description.

        Returns:
            An `OverlayError` describing the invalid patch.
        """
        return cls(f"Invalid overlay patch {path}: {detail}")

    @classmethod
    def invalid_mix(cls, path: Path, detail: str) -> Self:
        """Build an error when a MIX archive cannot be decoded or built.

        Args:
            path: MIX archive path or diagnostic label.
            detail: Decryption, parsing, or composition failure detail.

        Returns:
            An `OverlayError` describing the invalid MIX archive.
        """
        return cls(f"Invalid MIX archive {path}: {detail}")

    @classmethod
    def patch_target_not_found(
        cls,
        patch_path: Path,
        target_snippet: str,
    ) -> Self:
        """Build an error when a required replacement anchor is absent.

        Args:
            patch_path: Patch file that requested the edit.
            target_snippet: Missing target or anchor text.

        Returns:
            An `OverlayError` naming the missing target text.
        """
        return cls(
            f"Patch {patch_path} failed: target text {target_snippet!r} "
            "was not found in base file"
        )


class MountError(OverlayError):
    """Raised when a FUSE mount or unmount operation fails."""

    command: tuple[str, ...]
    returncode: int | None
    stderr: str

    def __init__(
        self,
        message: str,
        *,
        command: tuple[str, ...] = (),
        returncode: int | None = None,
        stderr: str = "",
    ) -> None:
        """Initialise a mount error with optional command details.

        Args:
            message: Human-readable failure summary.
            command: Invoked command arguments, if any.
            returncode: Process exit status, if a command ran.
            stderr: Captured standard error text, if any.
        """
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stderr = stderr

    @classmethod
    def unsupported_platform(cls, backend: str, platform: str) -> Self:
        """Build an error when a backend is unavailable on a platform.

        Args:
            backend: Backend identifier such as `fuse-overlayfs`.
            platform: Host platform identifier such as `windows`.

        Returns:
            A `MountError` explaining the platform constraint.
        """
        return cls(
            f"Backend {backend!r} is not supported on platform {platform!r}; "
            "use backend = 'symlink'."
        )

    @classmethod
    def tool_missing(cls, tool: str) -> Self:
        """Build an error when a required FUSE executable is missing.

        Args:
            tool: Executable name that was not found on `PATH`.

        Returns:
            A `MountError` identifying the missing tool.
        """
        return cls(
            f"Required overlay tool {tool!r} was not found on PATH. "
            "Install fuse-overlayfs or switch backend to 'symlink'."
        )

    @classmethod
    def command_failed(
        cls,
        command: Sequence[str],
        returncode: int,
        stderr: str,
    ) -> Self:
        """Build an error from a failing mount or unmount subprocess.

        Args:
            command: Argument vector passed to the subprocess.
            returncode: Non-zero process exit status.
            stderr: Captured stderr output from the command.

        Returns:
            A `MountError` preserving command diagnostics.
        """
        cmd_tuple = tuple(command)
        detail = stderr.strip() or f"exit status {returncode}"
        return cls(
            f"Overlay command failed ({cmd_tuple[0]}): {detail}",
            command=cmd_tuple,
            returncode=returncode,
            stderr=stderr,
        )


class RunnerError(MentaraError):
    """Raised when the configured game runner cannot be launched."""

    @classmethod
    def missing_runner(cls, command: str) -> Self:
        """Build an error when a runner binary cannot be located.

        Args:
            command: Configured runner executable name or path.

        Returns:
            A `RunnerError` identifying the missing runner.
        """
        return cls(f"Configured runner executable not found: {command}")

    @classmethod
    def missing_executable(cls, path: Path) -> Self:
        """Build an error when the game executable is absent in merged.

        Args:
            path: Expected executable path inside the merged directory.

        Returns:
            A `RunnerError` naming the missing target executable.
        """
        return cls(f"Target executable not found in virtual workspace: {path}")

    @classmethod
    def spawn_failed(cls, command: Sequence[str], detail: str) -> Self:
        """Build an error when spawning the runner process fails.

        Args:
            command: Argument vector passed to `subprocess.Popen`.
            detail: Underlying OS error description.

        Returns:
            A `RunnerError` reporting the spawn failure.
        """
        prog = command[0] if command else "<empty>"
        return cls(f"Failed to launch {prog}: {detail}")


class AssetError(MentaraError):
    """Raised when an asset source cannot be decoded or compiled."""

    @classmethod
    def invalid_format(cls, format_name: str, detail: str) -> Self:
        """Build an error for malformed data in a file format.

        Args:
            format_name: Format being decoded or encoded, such as `PNG`.
            detail: What is wrong with the data.

        Returns:
            An `AssetError` naming the format and the problem.
        """
        return cls(f"Invalid {format_name} data: {detail}")

    @classmethod
    def invalid_source(cls, path: Path, detail: str) -> Self:
        """Build an error for an asset source that cannot be compiled.

        Args:
            path: Source file or directory.
            detail: Underlying decoding or validation failure.

        Returns:
            An `AssetError` naming the source.
        """
        return cls(f"Cannot build asset from {path}: {detail}")

    @classmethod
    def missing_tool(cls, tool: str, purpose: str) -> Self:
        """Build an error when a required build tool is not installed.

        Args:
            tool: Executable name searched on `PATH`.
            purpose: What the tool is needed for.

        Returns:
            An `AssetError` naming the missing tool.
        """
        return cls(f"{tool} not found on PATH; it is needed to {purpose}")
