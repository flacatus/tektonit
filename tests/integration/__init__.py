"""Integration tests for tektonit.

These tests validate the complete pipeline:
- Build system (.claude/ → prompts.py)
- Test generation (prompts.py → LLM → test files)
- End-to-end flows (catalog scan → generation → execution)

Run with:
    pytest tests/integration/ -v

Run slow tests (requires API keys):
    pytest tests/integration/ -v --run-slow
"""
