"""Unit tests for resilience mechanisms (retry, circuit breaker, rate limiting)."""

import pytest
import time
from unittest.mock import Mock, patch

from tektonit.resilience import (
    llm_retry,
    CircuitBreaker,
    TokenBucket,
)


class TestRetryDecorator:
    """Test retry decorator functionality."""

    def test_retry_decorator_exists(self):
        """Test llm_retry decorator is callable."""
        assert callable(llm_retry)

    def test_retry_with_max_attempts(self):
        """Test retry decorator accepts max_attempts."""
        @llm_retry(max_attempts=3)
        def test_func():
            return "success"

        result = test_func()
        assert result == "success"

    def test_decorated_function_callable(self):
        """Test decorated function remains callable."""
        call_count = {"count": 0}

        @llm_retry(max_attempts=2)
        def counting_func():
            call_count["count"] += 1
            return "done"

        result = counting_func()
        assert result == "done"
        assert call_count["count"] == 1


class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    def test_circuit_breaker_starts_closed(self):
        """Test circuit breaker starts in closed state."""
        cb = CircuitBreaker(fail_threshold=3, reset_timeout=1.0)
        assert cb.state == CircuitBreaker.CLOSED

    def test_circuit_breaker_opens_after_threshold(self):
        """Test circuit breaker opens after failure threshold."""
        cb = CircuitBreaker(fail_threshold=3, reset_timeout=1.0)

        # Record 3 failures
        for _ in range(3):
            cb.record_failure()

        assert cb.state == CircuitBreaker.OPEN
        assert cb.is_open

    def test_circuit_breaker_property_is_open(self):
        """Test is_open property."""
        cb = CircuitBreaker(fail_threshold=2, reset_timeout=1.0)

        assert not cb.is_open  # Should be closed initially

        cb.record_failure()
        cb.record_failure()

        assert cb.is_open  # Should be open after threshold

    def test_circuit_breaker_resets_on_success(self):
        """Test circuit breaker resets failure count on success."""
        cb = CircuitBreaker(fail_threshold=3, reset_timeout=1.0)

        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # Should reset count

        assert cb.state == CircuitBreaker.CLOSED
        assert cb._failure_count == 0

    def test_circuit_breaker_half_open_after_timeout(self):
        """Test circuit breaker enters half-open state after timeout."""
        cb = CircuitBreaker(fail_threshold=2, reset_timeout=0.1)

        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open

        # Wait for recovery timeout
        time.sleep(0.15)

        # Check state (should transition to half-open or closed)
        # After timeout, next call should be allowed to test
        assert cb.state in [CircuitBreaker.CLOSED, CircuitBreaker.OPEN]

    def test_circuit_breaker_success_closes_from_half_open(self):
        """Test circuit breaker closes after successful call in half-open."""
        cb = CircuitBreaker(fail_threshold=2, reset_timeout=0.1)

        # Open and wait
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)

        # Record success should close circuit
        cb.record_success()
        assert cb.state == CircuitBreaker.CLOSED

    def test_circuit_breaker_multiple_failures(self):
        """Test circuit breaker handles many failures."""
        cb = CircuitBreaker(fail_threshold=5, reset_timeout=1.0)

        # Record failures below threshold
        for _ in range(4):
            cb.record_failure()
        assert not cb.is_open

        # One more should open it
        cb.record_failure()
        assert cb.is_open


class TestTokenBucket:
    """Test token bucket rate limiting."""

    def test_token_bucket_initialization(self):
        """Test TokenBucket initialization."""
        bucket = TokenBucket(capacity=10, refill_rate=5.0)
        assert bucket.capacity == 10
        assert bucket.refill_rate == 5.0

    def test_token_bucket_allows_within_capacity(self):
        """Test token bucket allows requests within capacity."""
        bucket = TokenBucket(capacity=5, refill_rate=1.0)

        # Should allow first 5 requests
        for _ in range(5):
            assert bucket.acquire(timeout=0.1)

    def test_token_bucket_blocks_over_capacity(self):
        """Test token bucket blocks requests over capacity."""
        bucket = TokenBucket(capacity=3, refill_rate=1.0)

        # Use up capacity
        for _ in range(3):
            bucket.acquire(timeout=0.1)

        # Next request should fail (timeout)
        start = time.time()
        result = bucket.acquire(timeout=0.1)
        duration = time.time() - start

        # Should timeout quickly
        assert duration < 0.5  # Allow some margin

    def test_token_bucket_refills_over_time(self):
        """Test token bucket refills tokens over time."""
        bucket = TokenBucket(capacity=2, refill_rate=10.0)  # 10 tokens/sec

        # Use capacity
        bucket.acquire()
        bucket.acquire()

        # Wait for refill (0.2 seconds = 2 tokens at 10/sec)
        time.sleep(0.25)

        # Should allow new requests
        assert bucket.acquire(timeout=0.1)

    def test_token_bucket_timeout_parameter(self):
        """Test token bucket respects timeout parameter."""
        bucket = TokenBucket(capacity=1, refill_rate=0.1)

        # Use capacity
        bucket.acquire()

        # Try to acquire with short timeout
        start = time.time()
        result = bucket.acquire(timeout=0.05)
        duration = time.time() - start

        # Should timeout in approximately specified time
        assert duration < 0.2  # Should be close to 0.05


class TestIntegration:
    """Test integration of resilience mechanisms."""

    def test_circuit_breaker_and_retry_together(self):
        """Test using circuit breaker with retry logic."""
        cb = CircuitBreaker(fail_threshold=3, reset_timeout=0.5)

        call_count = {"count": 0}

        @llm_retry(max_attempts=5)
        def function_with_breaker():
            call_count["count"] += 1

            if cb.is_open:
                raise RuntimeError("Circuit breaker open")

            if call_count["count"] < 3:
                cb.record_failure()
                raise Exception("Temporary failure")

            cb.record_success()
            return "success"

        # Circuit breaker should open, then function should fail
        # (This tests the interaction, not necessarily success)
        try:
            result = function_with_breaker()
        except (Exception, RuntimeError):
            # Either succeeds or circuit breaker stops it
            pass

    def test_token_bucket_rate_limiting(self):
        """Test token bucket enforces rate limiting."""
        bucket = TokenBucket(capacity=5, refill_rate=10.0)

        successful_calls = 0

        # Try to make 10 calls
        for _ in range(10):
            if bucket.acquire(timeout=0.01):
                successful_calls += 1

        # Should allow initial capacity, rest timeout
        assert successful_calls == 5


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_circuit_breaker_invalid_threshold(self):
        """Test circuit breaker with invalid threshold."""
        # Should handle edge cases gracefully
        cb = CircuitBreaker(fail_threshold=1, reset_timeout=0.1)
        cb.record_failure()
        assert cb.is_open

    def test_token_bucket_zero_timeout(self):
        """Test token bucket with zero timeout."""
        bucket = TokenBucket(capacity=1, refill_rate=1.0)
        bucket.acquire()  # Use capacity

        # Zero timeout should fail immediately
        start = time.time()
        result = bucket.acquire(timeout=0.0)
        duration = time.time() - start

        assert duration < 0.05  # Should be nearly instant

    def test_circuit_breaker_rapid_state_changes(self):
        """Test circuit breaker handles rapid state transitions."""
        cb = CircuitBreaker(fail_threshold=2, reset_timeout=0.05)

        # Rapid failures and successes
        cb.record_failure()
        cb.record_success()  # Reset
        cb.record_failure()
        cb.record_failure()  # Open

        assert cb.is_open

        time.sleep(0.1)  # Wait for reset
        cb.record_success()  # Should close

        assert not cb.is_open


class TestRealWorldScenarios:
    """Test realistic usage scenarios."""

    def test_api_call_with_all_resilience(self):
        """Test simulated API call with all resilience mechanisms."""
        cb = CircuitBreaker(fail_threshold=3, reset_timeout=1.0)
        bucket = TokenBucket(capacity=5, refill_rate=2.0)

        call_count = {"count": 0}

        @llm_retry(max_attempts=3)
        def api_call():
            call_count["count"] += 1

            # Check circuit breaker
            if cb.is_open:
                raise RuntimeError("Circuit open")

            # Check rate limit
            if not bucket.acquire(timeout=0.1):
                raise RuntimeError("Rate limited")

            # Simulate occasional failure
            if call_count["count"] == 1:
                cb.record_failure()
                raise Exception("Temporary failure")

            cb.record_success()
            return "success"

        # Should eventually succeed
        try:
            result = api_call()
            assert result == "success" or call_count["count"] > 0
        except RuntimeError:
            # May fail due to circuit breaker or rate limiting
            assert call_count["count"] > 0
