"""Unit tests for OrasClient manifest cache — single-client, no cross-reference leakage."""

from typing import Any
from unittest.mock import MagicMock

from oras.container import Container

from margot.infra.oci import OrasClient


class TestOrasClientManifestCache:
    """Tests for per-client manifest cache in OrasClient."""

    def test_cache_is_per_client_instance(self, mocker: Any) -> None:
        """Each OrasClient instance should have its own independent manifest cache."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.get_manifest")

        client1 = OrasClient()
        client2 = OrasClient()

        # Both should have a cache, but they should be different objects
        assert hasattr(client1, "_manifest_cache")
        assert hasattr(client2, "_manifest_cache")
        assert client1._manifest_cache is not client2._manifest_cache

    def test_cache_serves_already_fetched_manifest_on_string_uri(self, mocker: Any) -> None:
        """When cache has a manifest, get_manifest should return cached value without calling base."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.get_manifest")
        mocker.patch.object(OrasClient, "get_container", return_value=MagicMock())

        client = OrasClient()

        # Manually seed the cache with a manifest for the URI
        test_uri = "public.ecr.aws/g2n4p2m7/margo:1.0.0"
        cached_manifest = {"schemaVersion": 2, "artifactType": "application/vnd.margo.app.v1+json"}
        client._manifest_cache[test_uri] = cached_manifest

        # Call get_manifest with the same URI
        result = client.get_manifest(test_uri)

        # Should return cached manifest without calling base
        assert result == cached_manifest

    def test_cache_serves_already_fetched_manifest_on_container_object(self, mocker: Any) -> None:
        """When cache has a manifest, get_manifest(Container) should return cached without calling base."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.get_manifest")

        client = OrasClient()

        # Seed cache with a manifest for a URI
        test_uri = "public.ecr.aws/g2n4p2m7/margo:1.0.0"
        cached_manifest = {"schemaVersion": 2, "artifactType": "application/vnd.margo.app.v1+json"}
        client._manifest_cache[test_uri] = cached_manifest

        # Create a Container and call get_manifest with it
        # Container's uri property should match the cache key
        container = Container(name="g2n4p2m7/margo:1.0.0", registry="public.ecr.aws")

        result = client.get_manifest(container)

        # Should return cached manifest without calling base
        assert result == cached_manifest

    def test_cache_fetch_on_miss_with_string_uri(self, mocker: Any) -> None:
        """On cache miss, get_manifest(uri_string) should fetch, cache, and return."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        test_manifest = {"schemaVersion": 2, "artifactType": "application/vnd.margo.app.v1+json"}
        _mock_base_get_manifest = mocker.patch(
            "margot.infra.oci.OrasClientLib.get_manifest",
            return_value=test_manifest,
        )
        mock_container = MagicMock()
        mocker.patch.object(OrasClient, "get_container", return_value=mock_container)

        client = OrasClient()
        test_uri = "public.ecr.aws/g2n4p2m7/margo:1.0.0"

        # Cache is empty
        assert test_uri not in client._manifest_cache

        # Call get_manifest
        result = client.get_manifest(test_uri)

        # Should call base and cache the result
        assert result == test_manifest
        _mock_base_get_manifest.assert_called_once()
        assert client._manifest_cache[test_uri] == test_manifest

    def test_cache_fetch_on_miss_with_container_object(self, mocker: Any) -> None:
        """On cache miss, get_manifest(Container) should fetch, cache by string key, and return."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        test_manifest = {"schemaVersion": 2, "artifactType": "application/vnd.margo.app.v1+json"}
        _mock_base_get_manifest = mocker.patch(
            "margot.infra.oci.OrasClientLib.get_manifest",
            return_value=test_manifest,
        )

        client = OrasClient()
        container = Container(name="g2n4p2m7/margo:1.0.0", registry="public.ecr.aws")

        # The container's uri property should be the cache key
        container_uri = container.uri

        # Cache is empty
        assert container_uri not in client._manifest_cache

        # Call get_manifest with container
        result = client.get_manifest(container)

        # Should call base and cache by the string URI derived from container
        assert result == test_manifest
        _mock_base_get_manifest.assert_called_once()
        assert client._manifest_cache[container_uri] == test_manifest

    def test_cache_does_not_leak_between_clients(self, mocker: Any) -> None:
        """Manifest cached in client1 should not be visible to client2."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.get_manifest")
        mocker.patch.object(OrasClient, "get_container", return_value=MagicMock())

        client1 = OrasClient()
        client2 = OrasClient()

        test_uri = "public.ecr.aws/g2n4p2m7/margo:1.0.0"
        cached_manifest = {"schemaVersion": 2, "artifactType": "application/vnd.margo.app.v1+json"}

        # Seed client1's cache
        client1._manifest_cache[test_uri] = cached_manifest

        # client2 should NOT have this cached manifest
        assert test_uri not in client2._manifest_cache

    def test_cache_does_not_leak_to_unrelated_reference(self, mocker: Any) -> None:
        """Manifest for uri1 should not be returned for a different uri2."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)
        mocker.patch("margot.infra.oci.OrasClientLib.get_manifest")
        mocker.patch.object(OrasClient, "get_container", return_value=MagicMock())

        client = OrasClient()

        uri1 = "public.ecr.aws/g2n4p2m7/margo:1.0.0"
        uri2 = "public.ecr.aws/g2n4p2m7/margo:2.0.0"

        manifest1 = {"schemaVersion": 2, "artifactType": "application/vnd.margo.app.v1+json", "version": "1"}
        manifest2 = {"schemaVersion": 2, "artifactType": "application/vnd.margo.app.v1+json", "version": "2"}

        # Seed cache
        client._manifest_cache[uri1] = manifest1
        client._manifest_cache[uri2] = manifest2

        # Requesting uri1 should return manifest1, not manifest2
        result1 = client.get_manifest(uri1)
        assert result1 == manifest1
        assert result1["version"] == "1"

        # Requesting uri2 should return manifest2
        result2 = client.get_manifest(uri2)
        assert result2 == manifest2
        assert result2["version"] == "2"

