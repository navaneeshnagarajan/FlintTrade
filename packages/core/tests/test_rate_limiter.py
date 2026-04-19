"""Tests for RateLimiter token-bucket implementation.

Run with:
    python -m pytest packages/core/tests/test_rate_limiter.py -v --import-mode=importlib
"""

from __future__ import annotations

import time

import pytest
from flask import Flask

from packages.core.src.rate_limiter import RateLimiter, _Bucket, rate_limit


# ---------------------------------------------------------------------------
# _Bucket
# ---------------------------------------------------------------------------


class TestBucket:
    def test_full_bucket_allows_request(self):
        b = _Bucket(capacity=5.0, rate=5.0, tokens=5.0)
        allowed, retry_ms = b.consume()
        assert allowed is True
        assert retry_ms == 0

    def test_empty_bucket_denies_request(self):
        b = _Bucket(capacity=5.0, rate=5.0, tokens=0.0)
        allowed, retry_ms = b.consume()
        assert allowed is False
        assert retry_ms > 0

    def test_tokens_decrease_on_consume(self):
        b = _Bucket(capacity=5.0, rate=5.0, tokens=5.0)
        b.consume()
        assert b.tokens < 5.0

    def test_tokens_refill_with_time(self):
        b = _Bucket(capacity=10.0, rate=10.0, tokens=0.0)
        # Simulate 0.5s elapsed by moving last_refill back
        b.last_refill = time.monotonic() - 0.5
        allowed, _ = b.consume()
        assert allowed is True  # 5 tokens added; 1 consumed

    def test_tokens_capped_at_capacity(self):
        b = _Bucket(capacity=5.0, rate=5.0, tokens=5.0)
        # Even if a lot of time has passed, tokens don't exceed capacity
        b.last_refill = time.monotonic() - 100
        b.consume()
        assert b.tokens <= 5.0


# ---------------------------------------------------------------------------
# RateLimiter.check
# ---------------------------------------------------------------------------


class TestRateLimiterCheck:
    def _limiter(self, user_rate=5, global_rate=20):
        return RateLimiter(global_rate=global_rate, per_user_rate=user_rate)

    def test_first_request_allowed(self):
        rl = self._limiter()
        allowed, retry_ms = rl.check("alice", "orders")
        assert allowed is True
        assert retry_ms == 0

    def test_user_rate_limit_enforced(self):
        rl = self._limiter(user_rate=2, global_rate=100)
        rl.check("alice", "orders")
        rl.check("alice", "orders")
        # Third call should be blocked
        allowed, retry_ms = rl.check("alice", "orders")
        assert allowed is False
        assert retry_ms > 0

    def test_global_rate_limit_enforced(self):
        rl = self._limiter(user_rate=100, global_rate=2)
        rl.check("alice", "orders")
        rl.check("bob", "orders")  # different user, same global bucket
        allowed, _ = rl.check("charlie", "orders")
        assert allowed is False

    def test_different_endpoints_independent(self):
        rl = self._limiter(user_rate=1, global_rate=100)
        rl.check("alice", "orders")  # exhausts "orders" bucket
        # "history" endpoint should still be available
        allowed, _ = rl.check("alice", "history")
        assert allowed is True

    def test_different_users_independent(self):
        rl = self._limiter(user_rate=1, global_rate=100)
        rl.check("alice", "orders")  # exhausts alice's bucket
        allowed, _ = rl.check("bob", "orders")
        assert allowed is True

    def test_retry_after_ms_positive_when_blocked(self):
        rl = self._limiter(user_rate=1, global_rate=100)
        rl.check("alice", "orders")
        _, retry_ms = rl.check("alice", "orders")
        assert retry_ms > 0


# ---------------------------------------------------------------------------
# RateLimiter.get_limits / set_limit
# ---------------------------------------------------------------------------


class TestRateLimiterLimits:
    def test_default_limits_returned(self):
        rl = RateLimiter(global_rate=50, per_user_rate=5)
        limits = rl.get_limits("orders")
        assert limits["user_rate"] == 5
        assert limits["global_rate"] == 50

    def test_set_limit_overrides_defaults(self):
        rl = RateLimiter(global_rate=50, per_user_rate=5)
        rl.set_limit("orders", user_rate=2, global_rate=10)
        limits = rl.get_limits("orders")
        assert limits["user_rate"] == 2
        assert limits["global_rate"] == 10

    def test_set_limit_resets_buckets(self):
        rl = RateLimiter(global_rate=100, per_user_rate=2)
        rl.check("alice", "orders")
        rl.check("alice", "orders")  # bucket exhausted
        rl.set_limit("orders", user_rate=10, global_rate=100)  # reset + new capacity
        allowed, _ = rl.check("alice", "orders")
        assert allowed is True

    def test_different_endpoint_unaffected_by_set_limit(self):
        rl = RateLimiter(global_rate=100, per_user_rate=5)
        rl.set_limit("orders", user_rate=1, global_rate=1)
        limits = rl.get_limits("history")
        assert limits["user_rate"] == 5  # default unchanged


# ---------------------------------------------------------------------------
# RateLimiter.stats
# ---------------------------------------------------------------------------


class TestRateLimiterStats:
    def test_stats_empty_initially(self):
        rl = RateLimiter()
        stats = rl.stats()
        assert stats["global_buckets"] == {}
        assert stats["user_buckets"] == {}

    def test_stats_populate_after_check(self):
        rl = RateLimiter()
        rl.check("alice", "orders")
        stats = rl.stats()
        assert "orders" in stats["global_buckets"]
        assert "alice:orders" in stats["user_buckets"]

    def test_stats_token_counts_are_numeric(self):
        rl = RateLimiter()
        rl.check("alice", "orders")
        stats = rl.stats()
        assert isinstance(stats["global_buckets"]["orders"]["tokens"], float)


# ---------------------------------------------------------------------------
# RateLimiter — per-user overrides
# ---------------------------------------------------------------------------


class TestRateLimiterUserOverrides:
    def test_set_user_override_increases_effective_rate(self) -> None:
        """User with override gets higher rate than default."""
        rl = RateLimiter(global_rate=100, per_user_rate=2)
        # Without override, alice is limited to 2/s.
        rl.set_user_override("alice", "orders", 20)
        # Alice should still be allowed on the 3rd call (override = 20/s bucket).
        rl.check("alice", "orders")
        rl.check("alice", "orders")
        allowed, _ = rl.check("alice", "orders")
        assert allowed is True  # default would have denied

    def test_set_user_override_does_not_affect_other_users(self) -> None:
        """Override for alice does not change bob's effective rate."""
        rl = RateLimiter(global_rate=100, per_user_rate=1)
        rl.set_user_override("alice", "orders", 20)
        rl.check("bob", "orders")
        allowed, _ = rl.check("bob", "orders")
        assert allowed is False  # bob still limited at 1/s

    def test_remove_user_override_returns_true_when_existed(self) -> None:
        rl = RateLimiter(global_rate=100, per_user_rate=10)
        rl.set_user_override("alice", "orders", 50)
        assert rl.remove_user_override("alice", "orders") is True

    def test_remove_user_override_returns_false_when_absent(self) -> None:
        rl = RateLimiter(global_rate=100, per_user_rate=10)
        assert rl.remove_user_override("nobody", "orders") is False

    def test_list_overrides_returns_all_entries(self) -> None:
        rl = RateLimiter(global_rate=100, per_user_rate=10)
        rl.set_user_override("alice", "orders", 20)
        rl.set_user_override("bob", "history", 30)
        overrides = rl.list_overrides()
        assert len(overrides) == 2
        keys = {(o["user_id"], o["endpoint"]) for o in overrides}
        assert ("alice", "orders") in keys
        assert ("bob", "history") in keys

    def test_set_user_override_invalid_rate_raises(self) -> None:
        rl = RateLimiter()
        with pytest.raises(ValueError):
            rl.set_user_override("alice", "orders", 0)


# ---------------------------------------------------------------------------
# rate_limit decorator
# ---------------------------------------------------------------------------


class TestRateLimitDecorator:
    def _app(self, user_rate=5, global_rate=20):
        app = Flask(__name__)
        limiter = RateLimiter(global_rate=global_rate, per_user_rate=user_rate)
        app.config["RATE_LIMITER"] = limiter

        @app.route("/test", methods=["GET"])
        @rate_limit("test_endpoint", user_rate=user_rate, global_rate=global_rate)
        def _view():
            return "ok", 200

        return app

    def test_first_request_passes(self):
        with self._app().test_client() as client:
            resp = client.get("/test", headers={"X-User-ID": "alice"})
        assert resp.status_code == 200

    def test_rate_limited_returns_429(self):
        app = self._app(user_rate=1, global_rate=100)
        with app.test_client() as client:
            client.get("/test", headers={"X-User-ID": "alice"})
            resp = client.get("/test", headers={"X-User-ID": "alice"})
        assert resp.status_code == 429

    def test_429_response_has_retry_after_header(self):
        app = self._app(user_rate=1, global_rate=100)
        with app.test_client() as client:
            client.get("/test", headers={"X-User-ID": "alice"})
            resp = client.get("/test", headers={"X-User-ID": "alice"})
        assert "Retry-After" in resp.headers

    def test_no_limiter_allows_all(self):
        app = Flask(__name__)

        @app.route("/test")
        @rate_limit("endpoint", user_rate=1, global_rate=1)
        def _view():
            return "ok", 200

        # No RATE_LIMITER in config — should allow through
        with app.test_client() as client:
            for _ in range(5):
                resp = client.get("/test", headers={"X-User-ID": "alice"})
            assert resp.status_code == 200

    def test_different_users_independent(self):
        app = self._app(user_rate=1, global_rate=100)
        with app.test_client() as client:
            client.get("/test", headers={"X-User-ID": "alice"})
            resp = client.get("/test", headers={"X-User-ID": "bob"})
        assert resp.status_code == 200
