"""Code review tools tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from coworker.tools.code_review import (
    _review_security,
    _review_test_coverage,
    code_review_tools,
)


def test_code_review_tools_factory():
    """Factory returns 3 tools."""
    tools = code_review_tools()
    assert len(tools) == 3
    names = {t.__coworker_schema__["function"]["name"] for t in tools}
    assert names == {"review_pr", "review_security", "review_test_coverage"}


def test_review_security_scan(tmp_path):
    """Security scan should find hardcoded API keys."""
    # Write a file with a fake secret
    src = tmp_path / "config.py"
    src.write_text(
        'API_KEY = "sk-abcdefghij1234567890abcdefghij"\nSECRET = "my_super_secret_password_123"\n'
    )

    result = _review_security(str(tmp_path))
    assert result["files_scanned"] >= 1
    assert result["findings_count"] >= 1
    # At least one finding should be a secret type
    secret_findings = [f for f in result["findings"] if f["type"] == "secret"]
    assert len(secret_findings) >= 1


def test_review_security_clean_dir(tmp_path):
    """A directory with no code files should scan 0 files."""
    (tmp_path / "readme.txt").write_text("no code here")
    result = _review_security(str(tmp_path))
    assert result["files_scanned"] == 0
    assert result["findings_count"] == 0


def test_review_security_nonexistent_dir():
    result = _review_security("/nonexistent/path/xyz")
    assert "error" in result


def test_review_test_coverage(tmp_path):
    """Test coverage analyzer should detect test and source files."""
    # Create source file
    (tmp_path / "app.py").write_text("def hello(): pass\n")
    # Create test file
    (tmp_path / "test_app.py").write_text("def test_hello(): pass\n")

    result = _review_test_coverage(str(tmp_path))
    assert result["test_file_count"] == 1
    assert result["source_file_count"] == 1
    assert "app.py" not in result["potentially_untested_files"]  # has test


def test_review_test_coverage_untested(tmp_path):
    """Files without tests should appear in the untested list."""
    (tmp_path / "utils.py").write_text("def helper(): pass\n")
    (tmp_path / "models.py").write_text("class User: pass\n")
    # No test files

    result = _review_test_coverage(str(tmp_path))
    assert result["test_file_count"] == 0
    assert result["source_file_count"] == 2
    untested_basenames = [os.path.basename(f) for f in result["potentially_untested_files"]]
    assert "utils.py" in untested_basenames
    assert "models.py" in untested_basenames


def test_review_test_coverage_nonexistent():
    result = _review_test_coverage("/nonexistent/path/xyz")
    assert "error" in result


def test_review_pr_no_token(monkeypatch):
    """review_pr without a GitHub token returns an error message."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    tools = code_review_tools()
    review_pr = next(t for t in tools if t.__coworker_schema__["function"]["name"] == "review_pr")
    result = review_pr(repo="owner/repo", pr_number=1)
    assert "error" in result
    assert "token" in result["error"].lower()
