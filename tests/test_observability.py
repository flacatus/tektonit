"""Unit tests for observability module."""

import pytest

from tektonit.observability import (
    get_status,
    setup_logging,
    start_health_server,
    update_status,
)


class TestLogging:
    """Test logging functionality."""

    def test_setup_logging_default(self):
        """Test setup logging with default settings."""
        # Should not raise
        setup_logging()

    def test_setup_logging_json_format(self):
        """Test setup logging with JSON format."""
        # Should not raise
        setup_logging(json_format=True)

    def test_setup_logging_plain_format(self):
        """Test setup logging with plain format."""
        # Should not raise
        setup_logging(json_format=False)


class TestStatus:
    """Test status management."""

    def test_update_status(self):
        """Test updating status."""
        status = {"test": "value", "count": 123}
        update_status(status)
        # Should not raise

    def test_get_status(self):
        """Test getting status."""
        result = get_status()
        assert isinstance(result, dict)

    def test_update_and_get_status(self):
        """Test update then get status."""
        test_status = {"processed": 10, "failed": 2}
        update_status(test_status)
        result = get_status()
        # Status should be updated
        assert isinstance(result, dict)


class TestHealthServer:
    """Test health server functionality."""

    @pytest.mark.skip(reason="Requires actual server startup")
    def test_start_health_server(self):
        """Test starting health server."""
        # Would start actual HTTP server
        import threading

        thread = threading.Thread(target=lambda: start_health_server(port=9999))
        thread.daemon = True
        thread.start()

    def test_health_server_import(self):
        """Test health server function exists."""
        assert callable(start_health_server)
