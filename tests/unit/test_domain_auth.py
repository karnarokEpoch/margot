"""Unit tests for margot.domain.auth — pure function tests, no mocks needed."""

import base64
from datetime import UTC, datetime, timedelta
import json

from pytest import raises

from margot.domain.auth import TrackedRegistryStatus, classify_expiry, parse_token_expiry


def _make_ecr_token(expiration: int) -> str:
    """Build a valid ECR-format token for testing."""
    payload = json.dumps({"payload": "dummy", "version": "3", "type": "DATA_KEY", "expiration": expiration})
    return base64.b64encode(payload.encode()).decode()


class TestParseTokenExpiry:
    def test_returns_datetime_for_valid_ecr_token(self):
        token = _make_ecr_token(1785291060)
        result = parse_token_expiry(token)
        assert result == datetime.fromtimestamp(1785291060, tz=UTC)

    def test_returns_none_for_plain_string(self):
        assert parse_token_expiry("myplainpassword") is None

    def test_returns_none_for_empty_string(self):
        assert parse_token_expiry("") is None

    def test_returns_none_for_base64_json_without_expiration(self):
        payload = json.dumps({"foo": "bar"})
        token = base64.b64encode(payload.encode()).decode()
        assert parse_token_expiry(token) is None

    def test_returns_none_for_base64_non_json(self):
        token = base64.b64encode(b"not json at all").decode()
        assert parse_token_expiry(token) is None

    def test_returns_none_for_expiration_as_string(self):
        payload = json.dumps({"expiration": "not-a-number"})
        token = base64.b64encode(payload.encode()).decode()
        assert parse_token_expiry(token) is None

    def test_handles_token_with_missing_padding(self):
        # Tokens without padding should still parse
        token = _make_ecr_token(1785291060).rstrip("=")
        result = parse_token_expiry(token)
        assert result == datetime.fromtimestamp(1785291060, tz=UTC)

    def test_float_expiration_is_accepted(self):
        payload = json.dumps({"expiration": 1785291060.5})
        token = base64.b64encode(payload.encode()).decode()
        result = parse_token_expiry(token)
        assert result is not None
        assert result.tzinfo is not None


class TestClassifyExpiry:
    """Tests for classify_expiry()."""

    def test_valid_when_well_in_future(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        expires_at = now + timedelta(hours=6)
        assert classify_expiry(expires_at, now=now) == "VALID"

    def test_valid_when_just_over_5_minutes_remaining(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        expires_at = now + timedelta(minutes=5, seconds=1)
        assert classify_expiry(expires_at, now=now) == "VALID"

    def test_expiring_at_exactly_5_minute_boundary(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        expires_at = now + timedelta(minutes=5)
        assert classify_expiry(expires_at, now=now) == "EXPIRING"

    def test_expiring_just_under_5_minutes(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        expires_at = now + timedelta(minutes=4, seconds=59)
        assert classify_expiry(expires_at, now=now) == "EXPIRING"

    def test_expired_when_now_equals_expires_at(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert classify_expiry(now, now=now) == "EXPIRED"

    def test_expired_when_in_the_past(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        expires_at = now - timedelta(hours=1)
        assert classify_expiry(expires_at, now=now) == "EXPIRED"

    def test_defaults_now_to_current_time_when_not_provided(self):
        expires_at = datetime.now(tz=UTC) + timedelta(hours=6)
        assert classify_expiry(expires_at) == "VALID"


class TestTrackedRegistryStatus:
    """Tests for the TrackedRegistryStatus dataclass."""

    def test_constructs_with_expected_fields(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        expires_at = now + timedelta(hours=1)
        status = TrackedRegistryStatus(
            hostname="public.ecr.aws",
            expires_at=expires_at,
            remaining=expires_at - now,
            status="VALID",
        )

        assert status.hostname == "public.ecr.aws"
        assert status.expires_at == expires_at
        assert status.remaining == timedelta(hours=1)
        assert status.status == "VALID"

    def test_is_frozen(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        status = TrackedRegistryStatus(
            hostname="public.ecr.aws",
            expires_at=now,
            remaining=timedelta(0),
            status="EXPIRED",
        )

        with raises(AttributeError):
            status.hostname = "other.registry.io"

    def test_remaining_can_be_negative_when_expired(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        expires_at = now - timedelta(hours=1)
        status = TrackedRegistryStatus(
            hostname="public.ecr.aws",
            expires_at=expires_at,
            remaining=expires_at - now,
            status="EXPIRED",
        )

        assert status.remaining == timedelta(hours=-1)
