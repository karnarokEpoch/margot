"""Unit tests for margot.domain.auth — pure function tests, no mocks needed."""

import base64
from datetime import UTC, datetime
import json

from margot.domain.auth import parse_token_expiry


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
