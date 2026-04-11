"""
Sandboxed File Operations
=========================
Read, write, list, and search files within the workspace.

Security design:
  - All paths resolved to absolute and validated against WORKSPACE_ROOT
  - Path traversal (../) detected and blocked
  - Symlinks resolved before validation — cannot escape workspace
  - Write operations flagged for human approval
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class FileOpType(str, Enum):
    """Type of file operation."""

    READ = "READ"
    WRITE = "WRITE"
    LIST = "LIST"
    SEARCH = "SEARCH"
    DELETE = "DELETE"


class PathSecurityError(Exception):
    """Raised when a path violates workspace boundaries."""
    pass


@dataclass
class FileOpResult:
    """Result of a file operation."""

    success: bool
    operation: FileOpType
    path: str
    content: Optional[str] = None
    error: Optional[str] = None
    requires_approval: bool = False
    file_size_bytes: int = 0
    files_listed: Optional[list[str]] = None


class FileOps:
    """
    Sandboxed file operations scoped to workspace root.

    Every path is validated before any operation executes.
    """

    def __init__(self, workspace_root: str = "/workspace") -> None:
        self._workspace = Path(workspace_root).resolve()
        if not self._workspace.exists():
            self._workspace.mkdir(parents=True, exist_ok=True)

    def _validate_path(self, path: str) -> Path:
        """
        Validate that a path is within the workspace.

        Security checks:
          1. Resolve to absolute path
          2. Check for path traversal
          3. Resolve symlinks and re-check
          4. Verify within workspace boundary

        Args:
            path: Raw path string from agent.

        Returns:
            Resolved, validated Path object.

        Raises:
            PathSecurityError: If path is outside workspace.
        """
        # Normalize and resolve
        raw_path = Path(path)

        # If relative, join with workspace root
        if not raw_path.is_absolute():
            resolved = (self._workspace / raw_path).resolve()
        else:
            resolved = raw_path.resolve()

        # Check for traversal patterns in the raw input
        path_str = str(path)
        if ".." in path_str:
            raise PathSecurityError(
                f"Path traversal detected in '{path}'. "
                f"Paths containing '..' are not permitted."
            )

        # Verify the resolved path is within workspace
        try:
            resolved.relative_to(self._workspace)
        except ValueError:
            raise PathSecurityError(
                f"Path '{path}' resolves to '{resolved}' which is "
                f"outside the workspace '{self._workspace}'. "
                f"Access denied."
            ) from None

        # If the path exists, resolve symlinks and re-check
        if resolved.exists() and resolved.is_symlink():
            real_path = resolved.resolve()
            try:
                real_path.relative_to(self._workspace)
            except ValueError:
                raise PathSecurityError(
                    f"Symlink '{path}' points to '{real_path}' which is "
                    f"outside the workspace. Access denied."
                ) from None

        return resolved

    def read(self, path: str) -> FileOpResult:
        """
        Read file contents.

        Args:
            path: Path to file (relative to workspace or absolute).

        Returns:
            FileOpResult with file contents.
        """
        try:
            validated = self._validate_path(path)
        except PathSecurityError as e:
            return FileOpResult(
                success=False,
                operation=FileOpType.READ,
                path=path,
                error=str(e),
            )

        if not validated.exists():
            return FileOpResult(
                success=False,
                operation=FileOpType.READ,
                path=str(validated),
                error=f"File not found: {validated}",
            )

        if not validated.is_file():
            return FileOpResult(
                success=False,
                operation=FileOpType.READ,
                path=str(validated),
                error=f"Not a file: {validated}",
            )

        try:
            content = validated.read_text(encoding="utf-8")
            return FileOpResult(
                success=True,
                operation=FileOpType.READ,
                path=str(validated),
                content=content,
                file_size_bytes=validated.stat().st_size,
            )
        except UnicodeDecodeError:
            return FileOpResult(
                success=False,
                operation=FileOpType.READ,
                path=str(validated),
                error=f"Cannot read binary file: {validated}",
            )
        except PermissionError:
            return FileOpResult(
                success=False,
                operation=FileOpType.READ,
                path=str(validated),
                error=f"Permission denied: {validated}",
            )

    def write(
        self, path: str, content: str, create_dirs: bool = True
    ) -> FileOpResult:
        """
        Write content to a file. Requires human approval.

        Args:
            path: Target file path.
            content: Content to write.
            create_dirs: Create parent directories if needed.

        Returns:
            FileOpResult flagged for approval.
        """
        try:
            validated = self._validate_path(path)
        except PathSecurityError as e:
            return FileOpResult(
                success=False,
                operation=FileOpType.WRITE,
                path=path,
                error=str(e),
            )

        # Flag for human approval — actual write happens after approval
        return FileOpResult(
            success=True,
            operation=FileOpType.WRITE,
            path=str(validated),
            content=content,
            requires_approval=True,
            file_size_bytes=len(content.encode("utf-8")),
        )

    def execute_write(
        self, path: str, content: str, create_dirs: bool = True
    ) -> FileOpResult:
        """
        Execute the actual file write after approval.

        This should only be called after human approval.
        """
        try:
            validated = self._validate_path(path)
        except PathSecurityError as e:
            return FileOpResult(
                success=False,
                operation=FileOpType.WRITE,
                path=path,
                error=str(e),
            )

        try:
            if create_dirs:
                validated.parent.mkdir(parents=True, exist_ok=True)
            validated.write_text(content, encoding="utf-8")
            return FileOpResult(
                success=True,
                operation=FileOpType.WRITE,
                path=str(validated),
                file_size_bytes=validated.stat().st_size,
            )
        except PermissionError:
            return FileOpResult(
                success=False,
                operation=FileOpType.WRITE,
                path=str(validated),
                error=f"Permission denied: {validated}",
            )

    def delete(self, path: str) -> FileOpResult:
        """
        Delete a file. Requires human approval.

        Only single files — no recursive directory deletion.
        """
        try:
            validated = self._validate_path(path)
        except PathSecurityError as e:
            return FileOpResult(
                success=False,
                operation=FileOpType.DELETE,
                path=path,
                error=str(e),
            )

        if not validated.exists():
            return FileOpResult(
                success=False,
                operation=FileOpType.DELETE,
                path=str(validated),
                error=f"File not found: {validated}",
            )

        if validated.is_dir():
            return FileOpResult(
                success=False,
                operation=FileOpType.DELETE,
                path=str(validated),
                error="Directory deletion not permitted. Delete files individually.",
            )

        return FileOpResult(
            success=True,
            operation=FileOpType.DELETE,
            path=str(validated),
            requires_approval=True,
            file_size_bytes=validated.stat().st_size,
        )

    def execute_delete(self, path: str) -> FileOpResult:
        """Execute file deletion after approval."""
        try:
            validated = self._validate_path(path)
        except PathSecurityError as e:
            return FileOpResult(
                success=False, operation=FileOpType.DELETE,
                path=path, error=str(e),
            )

        try:
            validated.unlink()
            return FileOpResult(
                success=True, operation=FileOpType.DELETE,
                path=str(validated),
            )
        except PermissionError:
            return FileOpResult(
                success=False, operation=FileOpType.DELETE,
                path=str(validated),
                error=f"Permission denied: {validated}",
            )

    def list_dir(
        self, path: str = ".", recursive: bool = False, max_depth: int = 3
    ) -> FileOpResult:
        """
        List files in a directory.

        Args:
            path: Directory path (default: workspace root).
            recursive: Include subdirectories.
            max_depth: Maximum recursion depth.
        """
        try:
            validated = self._validate_path(path)
        except PathSecurityError as e:
            return FileOpResult(
                success=False, operation=FileOpType.LIST,
                path=path, error=str(e),
            )

        if not validated.is_dir():
            return FileOpResult(
                success=False, operation=FileOpType.LIST,
                path=str(validated),
                error=f"Not a directory: {validated}",
            )

        files: list[str] = []
        try:
            if recursive:
                for item in sorted(validated.rglob("*")):
                    # Respect max depth
                    rel = item.relative_to(validated)
                    if len(rel.parts) <= max_depth:
                        prefix = "  " * (len(rel.parts) - 1)
                        marker = "📁 " if item.is_dir() else "📄 "
                        files.append(f"{prefix}{marker}{rel}")
            else:
                for item in sorted(validated.iterdir()):
                    marker = "📁 " if item.is_dir() else "📄 "
                    files.append(f"{marker}{item.name}")
        except PermissionError:
            return FileOpResult(
                success=False, operation=FileOpType.LIST,
                path=str(validated),
                error=f"Permission denied: {validated}",
            )

        return FileOpResult(
            success=True, operation=FileOpType.LIST,
            path=str(validated),
            files_listed=files,
            content="\n".join(files),
        )

    def search(
        self, pattern: str, path: str = "."
    ) -> FileOpResult:
        """
        Search for files matching a glob pattern.

        Args:
            pattern: Glob pattern (e.g., "*.py", "test_*.py").
            path: Directory to search in.
        """
        try:
            validated = self._validate_path(path)
        except PathSecurityError as e:
            return FileOpResult(
                success=False, operation=FileOpType.SEARCH,
                path=path, error=str(e),
            )

        files = [
            str(f.relative_to(self._workspace))
            for f in sorted(validated.rglob(pattern))
            if f.is_file()
        ]

        return FileOpResult(
            success=True, operation=FileOpType.SEARCH,
            path=str(validated),
            files_listed=files,
            content="\n".join(files) if files else "No files found.",
        )
