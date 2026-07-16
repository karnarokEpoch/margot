"""Unit tests for domain/layers.py."""

from margot.domain.layers import resolve_filename, sanitize_filename, select_payload_layer

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


class TestSanitizeFilename:
    """Tests for sanitize_filename()."""

    def test_clean_name_returns_unchanged(self) -> None:
        """Should return clean filenames unchanged."""
        assert sanitize_filename("myapp-1.0.0.tgz") == "myapp-1.0.0.tgz"

    def test_strips_leading_trailing_whitespace(self) -> None:
        """Should strip leading and trailing whitespace."""
        assert sanitize_filename("  myapp.tgz  ") == "myapp.tgz"

    def test_forward_slash_returns_none(self) -> None:
        """Should return None when name contains a forward slash (path traversal)."""
        assert sanitize_filename("../../etc/passwd") is None

    def test_backslash_returns_none(self) -> None:
        """Should return None when name contains a backslash."""
        assert sanitize_filename("..\\secret") is None

    def test_null_byte_returns_none(self) -> None:
        """Should return None when name contains a null byte."""
        assert sanitize_filename("evil\x00.tgz") is None

    def test_dot_returns_none(self) -> None:
        """Should return None when name is exactly '.'."""
        assert sanitize_filename(".") is None

    def test_double_dot_returns_none(self) -> None:
        """Should return None when name is exactly '..'."""
        assert sanitize_filename("..") is None

    def test_whitespace_only_returns_none(self) -> None:
        """Should return None when name is empty after stripping whitespace."""
        assert sanitize_filename("   ") is None


class TestResolveFilenameWithForce:
    """Tests for resolve_filename() force parameter behaviour."""

    def test_force_false_malicious_title_falls_back_to_manifest_annotations(self) -> None:
        """force=False with malicious layer title should fall back to manifest annotations."""
        layer = {
            "mediaType": _COMPOSE_MEDIA_TYPE,
            "annotations": {"org.opencontainers.image.title": "../../evil.tgz"},
        }
        manifest_annotations = {
            "org.opencontainers.image.title": "myapp",
            "org.opencontainers.image.version": "1.0.0",
        }
        result = resolve_filename(layer, manifest_annotations, force=False)
        assert result == "myapp-1.0.0.tgz"

    def test_force_false_malicious_title_no_manifest_annotations_returns_none(self) -> None:
        """force=False with malicious layer title and no manifest annotations should return None."""
        layer = {
            "mediaType": _COMPOSE_MEDIA_TYPE,
            "annotations": {"org.opencontainers.image.title": "../../evil.tgz"},
        }
        result = resolve_filename(layer, manifest_annotations=None, force=False)
        assert result is None

    def test_force_true_malicious_title_returns_raw(self) -> None:
        """force=True with malicious layer title should return the raw name without sanitization."""
        layer = {
            "mediaType": _COMPOSE_MEDIA_TYPE,
            "annotations": {"org.opencontainers.image.title": "../../evil.tgz"},
        }
        result = resolve_filename(layer, manifest_annotations=None, force=True)
        assert result == "../../evil.tgz"


class TestResolveFilenameNonStringAnnotations:
    """Tests for resolve_filename() when annotation values are not strings."""

    def test_layer_title_dict_returns_none(self) -> None:
        """Layer annotation title is a dict (non-string) → returns None when no manifest annotations."""
        layer = {
            "mediaType": _COMPOSE_MEDIA_TYPE,
            "annotations": {"org.opencontainers.image.title": {"key": "value"}},
        }
        result = resolve_filename(layer, manifest_annotations=None)
        assert result is None

    def test_layer_title_int_returns_none(self) -> None:
        """Layer annotation title is an int (non-string) → returns None when no manifest annotations."""
        layer = {
            "mediaType": _COMPOSE_MEDIA_TYPE,
            "annotations": {"org.opencontainers.image.title": 42},
        }
        result = resolve_filename(layer, manifest_annotations=None)
        assert result is None

    def test_layer_title_dict_falls_back_to_manifest_annotations(self) -> None:
        """Layer annotation title is a dict → falls through to valid manifest-level annotations."""
        layer = {
            "mediaType": _COMPOSE_MEDIA_TYPE,
            "annotations": {"org.opencontainers.image.title": {"key": "value"}},
        }
        manifest_annotations = {
            "org.opencontainers.image.title": "myapp",
            "org.opencontainers.image.version": "3.0.0",
        }
        result = resolve_filename(layer, manifest_annotations)
        assert result == "myapp-3.0.0.tgz"

    def test_manifest_title_dict_returns_none(self) -> None:
        """Manifest annotation title is a dict (non-string) → returns None."""
        layer = {"mediaType": _COMPOSE_MEDIA_TYPE}
        manifest_annotations = {
            "org.opencontainers.image.title": {"key": "value"},
            "org.opencontainers.image.version": "1.0.0",
        }
        result = resolve_filename(layer, manifest_annotations)
        assert result is None

    def test_manifest_version_dict_returns_none(self) -> None:
        """Manifest annotation version is a dict (non-string) → returns None."""
        layer = {"mediaType": _COMPOSE_MEDIA_TYPE}
        manifest_annotations = {
            "org.opencontainers.image.title": "myapp",
            "org.opencontainers.image.version": {"key": "value"},
        }
        result = resolve_filename(layer, manifest_annotations)
        assert result is None
