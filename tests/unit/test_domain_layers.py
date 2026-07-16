"""Unit tests for domain/layers.py."""

from margot.domain.layers import resolve_filename, select_payload_layer

_COMPOSE_MEDIA_TYPE = "application/vnd.org.margo.component.compose.tar+gzip"
_OTHER_MEDIA_TYPE = "application/vnd.margo.app.description.v1+yaml"


class TestSelectPayloadLayer:
    """Tests for select_payload_layer()."""

    def test_returns_first_matching_layer(self) -> None:
        """Should return the first layer whose mediaType matches."""
        layers = [
            {"mediaType": _OTHER_MEDIA_TYPE, "digest": "sha256:aaa"},
            {"mediaType": _COMPOSE_MEDIA_TYPE, "digest": "sha256:bbb"},
        ]
        result = select_payload_layer(layers, _COMPOSE_MEDIA_TYPE)
        assert result is not None
        assert result["digest"] == "sha256:bbb"

    def test_returns_none_when_no_match(self) -> None:
        """Should return None when no layer has the given mediaType."""
        layers = [
            {"mediaType": _OTHER_MEDIA_TYPE, "digest": "sha256:aaa"},
        ]
        result = select_payload_layer(layers, _COMPOSE_MEDIA_TYPE)
        assert result is None

    def test_returns_first_when_multiple_match(self) -> None:
        """Should return the first matching layer when multiple layers share the mediaType."""
        layers = [
            {"mediaType": _COMPOSE_MEDIA_TYPE, "digest": "sha256:first"},
            {"mediaType": _COMPOSE_MEDIA_TYPE, "digest": "sha256:second"},
        ]
        result = select_payload_layer(layers, _COMPOSE_MEDIA_TYPE)
        assert result is not None
        assert result["digest"] == "sha256:first"


class TestResolveFilename:
    """Tests for resolve_filename()."""

    # TODO(karnarokEpoch): Should also have a test for malicious title renames and we should succeed it.
    # Traversal path, weird charaters in path...
    # name of the title should pass a set of constraints, and if not fail.
    # User should then be able to pull anyway with a force flag
    def test_uses_layer_title_annotation_when_present(self) -> None:
        """Should return the layer's own title annotation if available."""
        layer = {
            "mediaType": _COMPOSE_MEDIA_TYPE,
            "annotations": {"org.opencontainers.image.title": "myapp-1.0.0.tgz"},
        }
        result = resolve_filename(layer, manifest_annotations=None)
        assert result == "myapp-1.0.0.tgz"

    def test_falls_back_to_manifest_annotations(self) -> None:
        """Should construct '<title>-<version>.tgz' from manifest-level annotations when layer has no title."""
        layer = {"mediaType": _COMPOSE_MEDIA_TYPE}
        manifest_annotations = {
            "org.opencontainers.image.title": "myapp",
            "org.opencontainers.image.version": "2.3.1",
        }
        result = resolve_filename(layer, manifest_annotations)
        assert result == "myapp-2.3.1.tgz"

    def test_returns_none_when_no_naming_info(self) -> None:
        """Should return None when neither layer title nor manifest annotations are present."""
        layer = {"mediaType": _COMPOSE_MEDIA_TYPE}
        result = resolve_filename(layer, manifest_annotations=None)
        assert result is None

    def test_returns_none_when_manifest_annotations_missing_title(self) -> None:
        """Should return None when manifest annotations exist but 'title' key is absent."""
        layer = {"mediaType": _COMPOSE_MEDIA_TYPE}
        manifest_annotations = {
            "org.opencontainers.image.version": "1.0.0",
        }
        result = resolve_filename(layer, manifest_annotations)
        assert result is None
