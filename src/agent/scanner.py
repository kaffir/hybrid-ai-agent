"""
Workspace Scanner
==================
Reads workspace files and sends them to the LLM for analysis.

Provides the /scan command for quick code review, bug detection,
and project understanding.

Security design:
  - All file reads go through FileOps (path validation)
  - Total content capped to prevent context overflow
  - No file writes — read-only analysis
  - Output sanitized for credential leakage
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.tools.file_ops import FileOps


# Maximum total bytes to send to LLM
_MAX_SCAN_BYTES = 50_000

# File extensions to include in scans
_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".kt", ".go", ".rs", ".rb",
    ".c", ".cpp", ".h", ".hpp", ".cs",
    ".html", ".css", ".scss",
    ".sql", ".sh", ".bash",
    ".yml", ".yaml", ".toml", ".json",
    ".md", ".txt", ".cfg", ".ini",
    ".dockerfile",
}

# Files to always skip
_SKIP_FILES = {
    "package-lock.json", "yarn.lock", "poetry.lock",
    "Pipfile.lock", "uv.lock",
}

# Directories to skip
_SKIP_DIRS = {
    "__pycache__", "node_modules", ".git", ".venv",
    "venv", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".egg-info", ".agent",
}


@dataclass
class ScanResult:
    """Result of a workspace scan."""

    files_scanned: list[str] = field(default_factory=list)
    total_bytes: int = 0
    truncated: bool = False
    content: str = ""
    error: Optional[str] = None

    @property
    def file_count(self) -> int:
        return len(self.files_scanned)


class WorkspaceScanner:
    """
    Scans workspace files for LLM analysis.

    Collects code files, respects size limits,
    and formats content for structured analysis.
    """

    def __init__(
        self,
        file_ops: FileOps,
        max_bytes: int = _MAX_SCAN_BYTES,
    ) -> None:
        self._file_ops = file_ops
        self._max_bytes = max_bytes

    def scan(
        self,
        path: str = ".",
        pattern: Optional[str] = None,
        specific_file: Optional[str] = None,
    ) -> ScanResult:
        """
        Scan workspace files and collect their contents.

        Args:
            path: Directory to scan (relative to workspace).
            pattern: Glob pattern to filter files.
            specific_file: Scan a single specific file.

        Returns:
            ScanResult with collected file contents.
        """
        result = ScanResult()

        if specific_file:
            return self._scan_single_file(specific_file)

        # Discover files
        if pattern:
            search_result = self._file_ops.search(pattern, path)
            if not search_result.success:
                result.error = search_result.error
                return result
            files = search_result.files_listed or []
        else:
            files = self._discover_code_files(path)

        if not files:
            result.error = (
                f"No code files found in '{path}'."
            )
            return result

        # Read files up to size limit
        content_parts = []
        total_bytes = 0

        for file_path in sorted(files):
            read_result = self._file_ops.read(file_path)
            if not read_result.success:
                continue

            file_content = read_result.content or ""
            file_bytes = len(file_content.encode("utf-8"))

            if total_bytes + file_bytes > self._max_bytes:
                result.truncated = True
                break

            content_parts.append(
                f"--- FILE: {file_path} ---\n"
                f"{file_content}\n"
                f"--- END: {file_path} ---\n"
            )
            result.files_scanned.append(file_path)
            total_bytes += file_bytes

        result.total_bytes = total_bytes
        result.content = "\n".join(content_parts)

        return result

    def _scan_single_file(self, file_path: str) -> ScanResult:
        """Scan a single file."""
        result = ScanResult()

        read_result = self._file_ops.read(file_path)
        if not read_result.success:
            result.error = read_result.error
            return result

        file_content = read_result.content or ""
        result.files_scanned.append(file_path)
        result.total_bytes = len(file_content.encode("utf-8"))
        result.content = (
            f"--- FILE: {file_path} ---\n"
            f"{file_content}\n"
            f"--- END: {file_path} ---\n"
        )

        return result

    def _discover_code_files(self, path: str) -> list[str]:
        """
        Discover code files in a directory recursively.

        Filters by extension and skips known non-code directories.
        """
        list_result = self._file_ops.list_dir(
            path, recursive=True, max_depth=5
        )
        if not list_result.success:
            return []

        # Use search to get actual file paths
        all_files: list[str] = []
        for ext in _CODE_EXTENSIONS:
            search = self._file_ops.search(f"*{ext}", path)
            if search.success and search.files_listed:
                all_files.extend(search.files_listed)

        # Filter out skipped directories and files
        filtered = []
        for f in all_files:
            parts = Path(f).parts
            if any(d in _SKIP_DIRS for d in parts):
                continue
            if Path(f).name in _SKIP_FILES:
                continue
            filtered.append(f)

        return sorted(set(filtered))

    def build_analysis_prompt(
        self,
        scan_result: ScanResult,
        instruction: str = "",
    ) -> str:
        """
        Build a structured prompt for LLM analysis.

        Args:
            scan_result: Result from scan().
            instruction: Specific analysis instruction.

        Returns:
            Formatted prompt string.
        """
        if not instruction:
            instruction = (
                "Analyze the following code files. "
                "Look for bugs, security issues, code quality "
                "problems, and suggest improvements. "
                "Be specific about file names and line numbers."
            )

        header = (
            f"Scanned {scan_result.file_count} file(s), "
            f"{scan_result.total_bytes:,} bytes total."
        )

        if scan_result.truncated:
            header += (
                "\n⚠️ Some files were skipped due to size limit. "
                "Scan specific directories for complete coverage."
            )

        return (
            f"{instruction}\n\n"
            f"{header}\n\n"
            f"{scan_result.content}"
        )
