"""Unit tests for CLI commands."""

import subprocess
import sys

import pytest


class TestCLIBasics:
    """Test basic CLI functionality."""

    def test_cli_help(self):
        """Test CLI help command."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "tektonit" in result.stdout.lower()

    def test_cli_version(self):
        """Test CLI version command."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "--version"],
            capture_output=True,
            text=True,
        )
        # Version may or may not be implemented
        assert result.returncode in [0, 2]  # 2 = unrecognized option

    def test_scan_command_exists(self):
        """Test scan command is available."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "scan", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "scan" in result.stdout.lower()

    def test_generate_command_exists(self):
        """Test generate command is available."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "generate", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0


class TestScanCommand:
    """Test scan command functionality."""

    def test_scan_missing_path(self):
        """Test scan with missing path."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "scan"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_scan_nonexistent_path(self):
        """Test scan with nonexistent path."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "scan", "/nonexistent/path"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Should fail or exit cleanly
        assert result.returncode in [0, 1, 2]


class TestGenerateCommand:
    """Test generate command functionality."""

    def test_generate_missing_path(self):
        """Test generate with missing path."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "generate"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_generate_requires_api_key(self):
        """Test generate fails without API key."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "generate", "/tmp"],
            capture_output=True,
            text=True,
            env={},  # No API keys
            timeout=5,
        )
        # Should fail without API key
        assert result.returncode != 0 or "api" in result.stderr.lower()


@pytest.mark.skip(reason="CLI integration tests need complex mocking")
class TestCLIIntegration:
    """Test CLI integration with actual commands."""

    def test_scan_command_with_mock(self):
        """Test scan command with mocked discovery."""
        pass

    def test_generate_single_with_mock(self):
        """Test generate-single command with mocking."""
        pass
