"""Unit tests for infra/credentials.py."""

from datetime import UTC, datetime, timedelta
from io import StringIO
from json import dumps
from pathlib import Path

from pytest import fixture, raises

from margot.infra import credentials as creds_module
from margot.infra.credentials import (
    CredentialsExpiredError,
    check_credentials,
    list_oras_registries,
    list_tracked,
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

    def test_removes_last_entry_leaves_no_data(self, creds_file: Path) -> None:
        """Should leave no loadable entry when removing the only registry tracked."""
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        expires_at = datetime(2026, 6, 26, 23, 0, 0, tzinfo=UTC)
        save_expiry("public.ecr.aws", expires_at, credentials_file=creds_file)

        remove_expiry("public.ecr.aws", credentials_file=creds_file)

        assert load_expiry("public.ecr.aws", credentials_file=creds_file) is None
        assert creds_file.exists()  # file still written (empty), not deleted


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
        assert "warning:" in err_text
        assert "public.ecr.aws" in err_text
        assert "minutes" in err_text

    def test_returns_silently_when_expiry_in_future(self, creds_file: Path) -> None:
        """Should not raise or warn when expiry is more than 5 minutes away."""
        future = datetime.now(tz=UTC) + timedelta(hours=6)
        save_expiry("public.ecr.aws", future, credentials_file=creds_file)

        check_credentials("public.ecr.aws", credentials_file=creds_file)


class TestListTracked:
    """Tests for list_tracked()."""

    def test_returns_empty_list_when_file_does_not_exist(self, creds_file: Path) -> None:
        """Should return [] when credentials file does not exist."""
        assert list_tracked(credentials_file=creds_file) == []

    def test_returns_empty_list_when_no_registries(self, creds_file: Path) -> None:
        """Should return [] when the file exists but has no registries."""
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text("")

        assert list_tracked(credentials_file=creds_file) == []

    def test_returns_all_tracked_registries(self, creds_file: Path) -> None:
        """Should return (hostname, expires_at) for every tracked registry."""
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        content = (
            '[registries."public.ecr.aws"]\nexpires_at = "2026-06-26T23:00:00Z"\n\n'
            '[registries."other.registry.io"]\nexpires_at = "2026-07-01T12:00:00Z"\n'
        )
        creds_file.write_text(content)

        result = list_tracked(credentials_file=creds_file)

        assert set(result) == {
            ("public.ecr.aws", datetime(2026, 6, 26, 23, 0, 0, tzinfo=UTC)),
            ("other.registry.io", datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)),
        }

    def test_skips_entry_without_expires_at(self, creds_file: Path) -> None:
        """Should skip registries that have no expires_at field."""
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        content = (
            '[registries."public.ecr.aws"]\nexpires_at = "2026-06-26T23:00:00Z"\n\n'
            '[registries."no-expiry.registry.io"]\n'
        )
        creds_file.write_text(content)

        result = list_tracked(credentials_file=creds_file)

        assert result == [("public.ecr.aws", datetime(2026, 6, 26, 23, 0, 0, tzinfo=UTC))]


class TestListOrasRegistries:
    """Tests for list_oras_registries()."""

    def test_returns_empty_list_when_file_does_not_exist(self, tmp_path: Path) -> None:
        """Should return [] when docker config file does not exist."""
        missing = tmp_path / "config.json"
        assert list_oras_registries(docker_config_file=missing) == []

    def test_returns_empty_list_when_no_auths_key(self, tmp_path: Path) -> None:
        """Should return [] when the file has no 'auths' key."""
        config_file = tmp_path / "config.json"
        config_file.write_text(dumps({}))

        assert list_oras_registries(docker_config_file=config_file) == []

    def test_returns_empty_list_when_auths_empty(self, tmp_path: Path) -> None:
        """Should return [] when 'auths' is present but empty."""
        config_file = tmp_path / "config.json"
        config_file.write_text(dumps({"auths": {}}))

        assert list_oras_registries(docker_config_file=config_file) == []

    def test_returns_hostnames_from_auths(self, tmp_path: Path) -> None:
        """Should return the list of hostnames present in 'auths'."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            dumps(
                {
                    "auths": {
                        "public.ecr.aws": {"auth": "dGVzdA=="},
                        "other.registry.io": {"auth": "b3RoZXI="},
                    }
                }
            )
        )

        result = list_oras_registries(docker_config_file=config_file)

        assert set(result) == {"public.ecr.aws", "other.registry.io"}

    def test_returns_empty_list_on_malformed_json(self, tmp_path: Path) -> None:
        """Should return [] without raising when the file has malformed JSON."""
        config_file = tmp_path / "config.json"
        config_file.write_text("{not valid json")

        result = list_oras_registries(docker_config_file=config_file)

        assert result == []

    def test_defaults_to_docker_config_file_constant(self, mocker) -> None:
        """Should default to DOCKER_CONFIG_FILE when no path is given."""
        mocker.patch.object(creds_module, "DOCKER_CONFIG_FILE", mocker.MagicMock(exists=lambda: False))

        result = list_oras_registries()

        assert result == []
