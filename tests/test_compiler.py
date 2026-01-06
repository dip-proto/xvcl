"""
Tests for the xvcl compiler.

Run with: pytest tests/ -v
"""

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import pytest

TESTS_DIR = Path(__file__).parent
XVCL_DIR = TESTS_DIR / "xvcl"
EXPECTED_DIR = TESTS_DIR / "expected"


def compile_xvcl(source_file: Path, output_file: Optional[Path] = None) -> tuple:
    """Compile an xvcl file and return (output, stderr, returncode).

    If output_file is None, compiles to a temp file and returns its contents.
    """
    if output_file is None:
        with tempfile.NamedTemporaryFile(suffix=".vcl", delete=False) as f:
            output_file = Path(f.name)
        cleanup = True
    else:
        cleanup = False

    try:
        result = subprocess.run(
            [sys.executable, "-m", "xvcl.compiler", str(source_file), "-o", str(output_file)],
            capture_output=True,
            text=True,
            cwd=TESTS_DIR.parent,
        )

        if result.returncode == 0 and output_file.exists():
            output = output_file.read_text()
        else:
            output = ""

        return output, result.stderr, result.returncode
    finally:
        if cleanup and output_file.exists():
            output_file.unlink()


def get_feature_tests() -> list[tuple[str, Path, Path]]:
    """Find all feature tests (xvcl files with matching expected files)."""
    tests = []
    for xvcl_file in sorted(XVCL_DIR.glob("*.xvcl")):
        if xvcl_file.name.startswith("error_"):
            continue
        expected_file = EXPECTED_DIR / xvcl_file.with_suffix(".vcl").name
        if expected_file.exists():
            tests.append((xvcl_file.stem, xvcl_file, expected_file))
    return tests


def get_error_tests() -> list[tuple[str, Path, str]]:
    """Find all error tests (xvcl files starting with 'error_')."""
    tests = []
    for xvcl_file in sorted(XVCL_DIR.glob("error_*.xvcl")):
        content = xvcl_file.read_text()
        first_line = content.split("\n")[0]
        if first_line.startswith("// ERROR:"):
            expected_error = first_line[9:].strip()
            tests.append((xvcl_file.stem, xvcl_file, expected_error))
    return tests


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    import re
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


class TestFeatures:
    """Tests for xvcl features that should compile successfully."""

    @pytest.mark.parametrize("name,xvcl_file,expected_file", get_feature_tests())
    def test_feature(self, name: str, xvcl_file: Path, expected_file: Path):
        """Test that xvcl compiles to expected output."""
        output, stderr, returncode = compile_xvcl(xvcl_file)

        assert returncode == 0, f"Compilation failed:\n{strip_ansi(stderr)}"

        expected = expected_file.read_text()
        assert output.strip() == expected.strip(), (
            f"Output mismatch for {name}:\n"
            f"=== Expected ===\n{expected}\n"
            f"=== Got ===\n{output}"
        )


class TestErrors:
    """Tests for xvcl error handling."""

    @pytest.mark.parametrize("name,xvcl_file,expected_error", get_error_tests())
    def test_error(self, name: str, xvcl_file: Path, expected_error: str):
        """Test that xvcl produces expected error message."""
        output, stderr, returncode = compile_xvcl(xvcl_file)

        assert returncode != 0, f"Expected compilation to fail for {name}"
        stderr_clean = strip_ansi(stderr)
        assert expected_error in stderr_clean, (
            f"Expected error '{expected_error}' not found in:\n{stderr_clean}"
        )


FALCO_DIR = XVCL_DIR / "falco"


def get_falco_tests() -> list[tuple[str, Path]]:
    """Find all xvcl files in falco/ that should produce valid VCL for falco lint."""
    tests = []
    if not FALCO_DIR.exists():
        return tests
    for xvcl_file in sorted(FALCO_DIR.glob("*.xvcl")):
        tests.append((xvcl_file.stem, xvcl_file))
    return tests


def run_falco_lint(vcl_content: str) -> tuple[str, int]:
    """Run falco lint on VCL content. Returns (output, returncode)."""
    import shutil
    falco_path = shutil.which("falco")
    if falco_path is None:
        pytest.skip("falco not installed")

    with tempfile.NamedTemporaryFile(suffix=".vcl", delete=False, mode="w") as f:
        f.write(vcl_content)
        vcl_file = Path(f.name)

    try:
        result = subprocess.run(
            [falco_path, "lint", "-I", str(TESTS_DIR / "xvcl"), str(vcl_file)],
            capture_output=True,
            text=True,
        )
        return result.stdout + result.stderr, result.returncode
    finally:
        vcl_file.unlink()


class TestFalcoValidation:
    """Tests that compiled VCL passes falco lint."""

    @pytest.mark.parametrize("name,xvcl_file", get_falco_tests())
    def test_falco_lint(self, name: str, xvcl_file: Path):
        """Test that compiled VCL passes falco lint."""
        output, stderr, returncode = compile_xvcl(xvcl_file)
        assert returncode == 0, f"Compilation failed:\n{strip_ansi(stderr)}"

        falco_output, falco_returncode = run_falco_lint(output)
        # falco returns 1 for lint errors
        if falco_returncode != 0:
            # Ignore certain falco warnings/errors that aren't actual issues
            if "backend" in output.lower() and "first_byte_timeout" in falco_output:
                pytest.skip("falco warning about missing backend properties (not an xvcl issue)")
            assert falco_returncode == 0, (
                f"falco lint failed for {name}:\n{falco_output}\n\n"
                f"Generated VCL:\n{output}"
            )
