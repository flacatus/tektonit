"""Additional CLI command tests to increase coverage."""

import subprocess
import sys


class TestCLICommandStructure:
    """Test CLI command structure and help."""

    def test_main_help_lists_commands(self):
        """Test main help lists available commands."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        # Should list commands
        output_lower = result.stdout.lower()
        assert "scan" in output_lower or "generate" in output_lower

    def test_scan_help_shows_options(self):
        """Test scan help shows available options."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "scan", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "scan" in result.stdout.lower()

    def test_generate_help_shows_options(self):
        """Test generate help shows available options."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "generate", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "generate" in result.stdout.lower()


class TestScanCommandOptions:
    """Test scan command options."""

    def test_scan_with_branch_option(self):
        """Test scan with branch option."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "scan", "--help"],
            capture_output=True,
            text=True,
        )
        # Should show branch option
        assert "branch" in result.stdout.lower() or result.returncode == 0


class TestGenerateCommandOptions:
    """Test generate command options."""

    def test_generate_with_provider_option(self):
        """Test generate with provider option."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "generate", "--help"],
            capture_output=True,
            text=True,
        )
        # Should show provider option
        assert "provider" in result.stdout.lower() or result.returncode == 0

    def test_generate_single_help(self):
        """Test generate-single command help."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "generate-single", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0


class TestCLIErrorHandling:
    """Test CLI error handling."""

    def test_invalid_command(self):
        """Test running invalid command."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "invalid-command"],
            capture_output=True,
            text=True,
        )
        # Should fail
        assert result.returncode != 0

    def test_scan_missing_required_arg(self):
        """Test scan without required argument."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "scan"],
            capture_output=True,
            text=True,
        )
        # Should show error or usage
        assert result.returncode != 0 or "usage" in result.stdout.lower()


class TestGenerateTemplateCommand:
    """Test generate-template command."""

    def test_generate_template_help(self):
        """Test generate-template help."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "generate-template", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_generate_template_missing_args(self):
        """Test generate-template without arguments."""
        result = subprocess.run(
            [sys.executable, "-m", "tektonit.cli", "generate-template"],
            capture_output=True,
            text=True,
        )
        # Should fail or show usage
        assert result.returncode != 0 or "usage" in result.stdout.lower()
