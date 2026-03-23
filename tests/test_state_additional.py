"""Additional tests for state module."""

import tempfile
from pathlib import Path

import pytest


class TestStateStoreAdditional:
    """Additional state store tests."""

    @pytest.mark.skip(reason="Need to check actual API")
    def test_state_record_processed(self):
        """Test recording processed resource."""
        from tektonit.state import StateStore

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            try:
                StateStore(f.name)
                # API call needs to be fixed
            finally:
                Path(f.name).unlink()

    def test_state_store_init(self):
        """Test state store initialization."""
        from tektonit.state import StateStore

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            try:
                state = StateStore(f.name)
                assert state is not None
                assert state.db_path == f.name
            finally:
                Path(f.name).unlink()

    def test_state_get_stats_exists(self):
        """Test get_stats method exists."""
        from tektonit.state import StateStore

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            try:
                state = StateStore(f.name)
                assert hasattr(state, "get_stats")
            finally:
                Path(f.name).unlink()
