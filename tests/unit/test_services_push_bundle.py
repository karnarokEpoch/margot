"""Unit tests for services/push.py BUNDLE rejection."""

from pytest import raises

from margot.domain.models import PackageType
from margot.services import push as push_service


def test_push_bundle_raises_value_error(mocker):
    """Pushing PackageType.BUNDLE should raise ValueError."""
    mock_meta = mocker.MagicMock()
    mocker.patch("margot.services.push.load_margo_yaml", return_value=mock_meta)

    with raises(ValueError, match="Bundles are not pushed to registries"):
        push_service.push(
            PackageType.BUNDLE,
            project_dir=".",
            build_dir=".dist",
        )


def test_push_unknown_raises_value_error(mocker):
    """Pushing PackageType.UNKNOWN should raise ValueError."""
    mock_meta = mocker.MagicMock()
    mocker.patch("margot.services.push.load_margo_yaml", return_value=mock_meta)

    with raises(ValueError, match="Cannot push UNKNOWN package type"):
        push_service.push(
            PackageType.UNKNOWN,
            project_dir=".",
            build_dir=".dist",
        )
