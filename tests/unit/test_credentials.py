"""Unit tests for infra/credentials.py."""

from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

from pytest import fixture, raises

from margot.infra.credentials import (
    CredentialsExpiredError,
    check_credentials,
    load_expiry,
    remove_expiry,
    save_expiry,
)


@fixture
def creds_file(tmp_path: Path) -> Path:
    """Return path to a temporary credentials file."""
    return tmp_path / "credentials.toml"


class TestLoadExpiry:
    """Tests for load_expiry()."""

    def test_returns_none_when_file_does_not_exist(self, creds_file: Path) -> None:
        """Should return None when credentials file does not exist."""
        result = load_expiry("public.ecr.aws", credentials_file=creds_file)
        assert result is None

    def test_returns_none_when_registry_not_in_file(self, creds_file: Path) -> None:
        """Should return None when registry is not present in the file."""
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text('[registries."other.registry.io"]\nexpires_at = "2026-06-26T23:00:00Z"\n')

        result = load_expiry("public.ecr.aws", credentials_file=creds_file)
        assert result is None

    def test_returns_correct_datetime_when_entry_exists(self, creds_file: Path) -> None:
        """Should return the correct UTC datetime for an existing entry."""
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text('[registries."public.ecr.aws"]\nexpires_at = "2026-06-26T23:00:00Z"\n')

        result = load_expiry("public.ecr.aws", credentials_file=creds_file)
        expected = datetime(2026, 6, 26, 23, 0, 0, tzinfo=UTC)
        assert result == expected


class TestSaveExpiry:
    """Tests for save_expiry()."""

    def test_creates_file_if_not_exists(self, creds_file: Path) -> None:
        """Should create the credentials file and parent directories."""
        expires_at = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)
        save_expiry("public.ecr.aws", expires_at, credentials_file=creds_file)

        assert creds_file.exists()
        result = load_expiry("public.ecr.aws", credentials_file=creds_file)
        assert result == expires_at

    def test_adds_entry_without_overwriting_others(self, creds_file: Path) -> None:
        """Should add a new entry without removing existing ones."""
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text('[registries."other.registry.io"]\nexpires_at = "2026-06-26T23:00:00Z"\n')

        new_expiry = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)
        save_expiry("public.ecr.aws", new_expiry, credentials_file=creds_file)

        assert load_expiry("other.registry.io", credentials_file=creds_file) == datetime(2026, 6, 26, 23, 0, 0, tzinfo=UTC)
        assert load_expiry("public.ecr.aws", credentials_file=creds_file) == new_expiry

    def test_overwrites_existing_entry_for_same_registry(self, creds_file: Path) -> None:
        """Should overwrite the expiry for an already-tracked registry."""
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text('[registries."public.ecr.aws"]\nexpires_at = "2026-06-26T23:00:00Z"\n')

        new_expiry = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
        save_expiry("public.ecr.aws", new_expiry, credentials_file=creds_file)

        result = load_expiry("public.ecr.aws", credentials_file=creds_file)
        assert result == new_expiry


class TestRemoveExpiry:
    """Tests for remove_expiry()."""

    def test_noop_when_file_does_not_exist(self, creds_file: Path) -> None:
        """Should not raise when file doesn't exist."""
        remove_expiry("public.ecr.aws", credentials_file=creds_file)
        # No exception raised

    def test_noop_when_registry_not_in_file(self, creds_file: Path) -> None:
        """Should not raise when registry is not present."""
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text('[registries."other.registry.io"]\nexpires_at = "2026-06-26T23:00:00Z"\n')

        remove_expiry("public.ecr.aws", credentials_file=creds_file)
        # Other entry still exists
        assert load_expiry("other.registry.io", credentials_file=creds_file) is not None

    def test_removes_only_target_registry_entry(self, creds_file: Path) -> None:
        """Should remove only the specified registry, keeping others intact."""
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        content = (
            '[registries."public.ecr.aws"]\nexpires_at = "2026-06-26T23:00:00Z"\n\n'
            '[registries."other.registry.io"]\nexpires_at = "2026-07-01T12:00:00Z"\n'
        )
        creds_file.write_text(content)

        remove_expiry("public.ecr.aws", credentials_file=creds_file)

        assert load_expiry("public.ecr.aws", credentials_file=creds_file) is None
        assert load_expiry("other.registry.io", credentials_file=creds_file) == datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)

    def test_removes_last_entry_leaves_empty_file(self, creds_file: Path) -> None:
        """Should write an empty file when the only entry is removed."""
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text('[registries."public.ecr.aws"]\nexpires_at = "2026-06-26T23:00:00Z"\n')

        remove_expiry("public.ecr.aws", credentials_file=creds_file)

        # File still exists but the entry is gone
        assert creds_file.exists()
        assert load_expiry("public.ecr.aws", credentials_file=creds_file) is None


class TestCheckCredentials:
    """Tests for check_credentials()."""

    def test_returns_silently_when_no_expiry_tracked(self, creds_file: Path) -> None:
        """Should not raise when no expiry is tracked for registry."""
        check_credentials("public.ecr.aws", credentials_file=creds_file)

    def test_raises_when_expired(self, creds_file: Path) -> None:
        """Should raise CredentialsExpiredError when credentials are expired."""
        past = datetime.now(tz=UTC) - timedelta(hours=1)
        save_expiry("public.ecr.aws", past, credentials_file=creds_file)

        with raises(CredentialsExpiredError, match="expired"):
            check_credentials("public.ecr.aws", credentials_file=creds_file)

    def test_emits_warning_when_within_5_minutes(self, creds_file: Path, capture_console: tuple[StringIO, StringIO]) -> None:
        """Should emit a console warning when within 5 minutes of expiry."""
        near_expiry = datetime.now(tz=UTC) + timedelta(minutes=3)
        save_expiry("public.ecr.aws", near_expiry, credentials_file=creds_file)

        _out, err = capture_console
        check_credentials("public.ecr.aws", credentials_file=creds_file)

        err_text = err.getvalue()
        assert "Warning:" in err_text
        assert "public.ecr.aws" in err_text
        assert "minutes" in err_text

    def test_returns_silently_when_expiry_in_future(self, creds_file: Path) -> None:
        """Should not raise or warn when expiry is more than 5 minutes away."""
        future = datetime.now(tz=UTC) + timedelta(hours=6)
        save_expiry("public.ecr.aws", future, credentials_file=creds_file)

        check_credentials("public.ecr.aws", credentials_file=creds_file)
