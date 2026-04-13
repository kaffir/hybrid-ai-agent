"""
Tests for Workspace Scanner
=============================
Validates file discovery, content collection,
size limits, and prompt building.
"""

import pytest
import tempfile
import shutil
from pathlib import Path

from src.tools.file_ops import FileOps
from src.agent.scanner import WorkspaceScanner


@pytest.fixture
def tmp_workspace():
    tmpdir = tempfile.mkdtemp(prefix="scanner_test_")
    yield tmpdir
    shutil.rmtree(tmpdir)


@pytest.fixture
def scanner(tmp_workspace: str) -> WorkspaceScanner:
    file_ops = FileOps(workspace_root=tmp_workspace)
    return WorkspaceScanner(file_ops=file_ops)


class TestFileDiscovery:
    """Scanner must find code files correctly."""

    def test_finds_python_files(
        self, scanner: WorkspaceScanner, tmp_workspace: str
    ) -> None:
        Path(tmp_workspace, "main.py").write_text("x = 1")
        Path(tmp_workspace, "utils.py").write_text("y = 2")
        result = scanner.scan()
        assert result.file_count == 2

    def test_finds_nested_files(
        self, scanner: WorkspaceScanner, tmp_workspace: str
    ) -> None:
        src = Path(tmp_workspace, "src")
        src.mkdir()
        Path(src, "app.py").write_text("code")
        result = scanner.scan()
        assert result.file_count == 1
        assert "src/app.py" in result.files_scanned[0]

    def test_skips_pycache(
        self, scanner: WorkspaceScanner, tmp_workspace: str
    ) -> None:
        cache = Path(tmp_workspace, "__pycache__")
        cache.mkdir()
        Path(cache, "module.cpython-311.pyc").write_text("bytes")
        Path(tmp_workspace, "main.py").write_text("code")
        result = scanner.scan()
        assert result.file_count == 1

    def test_skips_node_modules(
        self, scanner: WorkspaceScanner, tmp_workspace: str
    ) -> None:
        nm = Path(tmp_workspace, "node_modules")
        nm.mkdir()
        Path(nm, "index.js").write_text("code")
        Path(tmp_workspace, "app.js").write_text("code")
        result = scanner.scan()
        assert result.file_count == 1

    def test_skips_git_directory(
        self, scanner: WorkspaceScanner, tmp_workspace: str
    ) -> None:
        git = Path(tmp_workspace, ".git")
        git.mkdir()
        Path(git, "config").write_text("data")
        Path(tmp_workspace, "main.py").write_text("code")
        result = scanner.scan()
        assert result.file_count == 1

    def test_empty_workspace(
        self, scanner: WorkspaceScanner
    ) -> None:
        result = scanner.scan()
        assert result.error is not None
        assert "No code files" in result.error


class TestSpecificTargets:
    """Scanning specific files and directories."""

    def test_scan_single_file(
        self, scanner: WorkspaceScanner, tmp_workspace: str
    ) -> None:
        Path(tmp_workspace, "target.py").write_text(
            "def hello(): pass"
        )
        result = scanner.scan(specific_file="target.py")
        assert result.file_count == 1
        assert "def hello" in result.content

    def test_scan_specific_directory(
        self, scanner: WorkspaceScanner, tmp_workspace: str
    ) -> None:
        src = Path(tmp_workspace, "src")
        src.mkdir()
        Path(src, "a.py").write_text("a = 1")
        Path(src, "b.py").write_text("b = 2")
        Path(tmp_workspace, "other.py").write_text("other")
        result = scanner.scan(path="src")
        assert result.file_count == 2

    def test_scan_with_pattern(
        self, scanner: WorkspaceScanner, tmp_workspace: str
    ) -> None:
        Path(tmp_workspace, "test_one.py").write_text("t1")
        Path(tmp_workspace, "test_two.py").write_text("t2")
        Path(tmp_workspace, "main.py").write_text("main")
        result = scanner.scan(pattern="test_*.py")
        assert result.file_count == 2

    def test_scan_nonexistent_file(
        self, scanner: WorkspaceScanner
    ) -> None:
        result = scanner.scan(specific_file="ghost.py")
        assert result.error is not None


class TestSizeLimits:
    """Scanner must respect size limits."""

    def test_truncation_on_large_content(
        self, tmp_workspace: str
    ) -> None:
        file_ops = FileOps(workspace_root=tmp_workspace)
        scanner = WorkspaceScanner(
            file_ops=file_ops, max_bytes=1000
        )
        # Create files that exceed limit
        for i in range(10):
            Path(tmp_workspace, f"file{i}.py").write_text(
                "x = 1\n" * 100
            )
        result = scanner.scan()
        assert result.truncated
        assert result.total_bytes <= 1000

    def test_no_truncation_under_limit(
        self, scanner: WorkspaceScanner, tmp_workspace: str
    ) -> None:
        Path(tmp_workspace, "small.py").write_text("x = 1")
        result = scanner.scan()
        assert not result.truncated


class TestPromptBuilding:
    """Analysis prompt must be well-structured."""

    def test_prompt_includes_file_content(
        self, scanner: WorkspaceScanner, tmp_workspace: str
    ) -> None:
        Path(tmp_workspace, "code.py").write_text(
            "def buggy(): return 1/0"
        )
        result = scanner.scan()
        prompt = scanner.build_analysis_prompt(result)
        assert "buggy" in prompt
        assert "code.py" in prompt

    def test_prompt_includes_custom_instruction(
        self, scanner: WorkspaceScanner, tmp_workspace: str
    ) -> None:
        Path(tmp_workspace, "code.py").write_text("x = 1")
        result = scanner.scan()
        prompt = scanner.build_analysis_prompt(
            result, instruction="Check for type errors"
        )
        assert "type errors" in prompt

    def test_prompt_shows_truncation_warning(
        self, tmp_workspace: str
    ) -> None:
        file_ops = FileOps(workspace_root=tmp_workspace)
        scanner = WorkspaceScanner(
            file_ops=file_ops, max_bytes=100
        )
        for i in range(5):
            Path(tmp_workspace, f"f{i}.py").write_text(
                "x = 1\n" * 50
            )
        result = scanner.scan()
        prompt = scanner.build_analysis_prompt(result)
        assert "skipped" in prompt.lower() or "truncat" in prompt.lower()
