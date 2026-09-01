"""Unit tests for domain/app_description.py — component reference extraction."""

from pathlib import Path

from pytest import fail, fixture
import yaml

from margot.domain.app_description import ComponentRef, extract_component_refs


@fixture
def fixtures_dir() -> Path:
    """Return the path to the app-descriptions fixtures directory."""
    return Path(__file__).parent.parent / "fixtures" / "app-descriptions"


@fixture
def complex_doc(fixtures_dir: Path) -> dict:
    """Load the complex.yaml fixture."""
    with (fixtures_dir / "complex.yaml").open() as f:
        return yaml.safe_load(f)


@fixture
def minimal_doc(fixtures_dir: Path) -> dict:
    """Load the minimal.yaml fixture."""
    with (fixtures_dir / "minimal.yaml").open() as f:
        return yaml.safe_load(f)


@fixture
def missing_recommended_doc(fixtures_dir: Path) -> dict:
    """Load the missing-recommended.yaml fixture."""
    with (fixtures_dir / "missing-recommended.yaml").open() as f:
        return yaml.safe_load(f)


@fixture
def unlinked_parameters_doc(fixtures_dir: Path) -> dict:
    """Load the unlinked-parameters.yaml fixture."""
    with (fixtures_dir / "unlinked-parameters.yaml").open() as f:
        return yaml.safe_load(f)


class TestComponentRefDataclass:
    """Tests for ComponentRef dataclass."""

    def test_component_ref_ref_property(self) -> None:
        """ComponentRef.ref should return repository:tag."""
        ref = ComponentRef(name="db", repository="quay.io/charts/db", tag="1.2.3")
        assert ref.ref == "quay.io/charts/db:1.2.3"

    def test_component_ref_frozen(self) -> None:
        """ComponentRef should be frozen (immutable)."""
        ref = ComponentRef(name="db", repository="quay.io/charts/db", tag="1.2.3")
        try:
            ref.name = "new-name"
            fail("Should not be able to mutate frozen dataclass")
        except (AttributeError, TypeError):
            pass  # Expected


class TestExtractComponentRefsFromComplexFixture:
    """Tests extract_component_refs against complex.yaml fixture."""

    def test_complex_fixture_yields_three_refs(self, complex_doc: dict) -> None:
        """complex.yaml should yield exactly 3 unique component refs."""
        refs, skipped = extract_component_refs(complex_doc)
        assert len(refs) == 3
        assert len(skipped) == 0

    def test_complex_fixture_first_component(self, complex_doc: dict) -> None:
        """First component from complex.yaml: database-services."""
        refs, _ = extract_component_refs(complex_doc)
        assert refs[0].name == "database-services"
        assert refs[0].repository == "quay.io/charts/realtime-database-services"
        assert refs[0].tag == "2.3.7"

    def test_complex_fixture_second_component(self, complex_doc: dict) -> None:
        """Second component from complex.yaml: digitron-orchestrator."""
        refs, _ = extract_component_refs(complex_doc)
        # The second unique ref should be digitron-orchestrator from helm profile
        # (the compose profile's digitron-orchestrator-docker is a different repository)
        assert refs[1].name == "digitron-orchestrator"
        assert refs[1].repository == "northstarida.azurecr.io/charts/northstarida-digitron-orchestrator"
        assert refs[1].tag == "1.0.9"

    def test_complex_fixture_deduplicates_same_repo_tag(self, complex_doc: dict) -> None:
        """complex.yaml declares digitron-orchestrator-docker in compose profile.

        This has a different repository than the helm profile's component, so both
        should appear... wait, let me check the fixture again. Actually looking at
        the fixture, there are 3 components declared but only 2 unique repos:
        - database-services (helm profile)
        - digitron-orchestrator (helm profile)
        - digitron-orchestrator-docker (compose profile, different repo)

        So we should get 3 unique (repo, tag) pairs.
        """
        refs, _ = extract_component_refs(complex_doc)
        # Actually verify the structure
        assert len(refs) == 3  # 3 unique (repo, tag) pairs
        repo_tags = [(ref.repository, ref.tag) for ref in refs]
        assert ("quay.io/charts/realtime-database-services", "2.3.7") in repo_tags
        assert ("northstarida.azurecr.io/charts/northstarida-digitron-orchestrator", "1.0.9") in repo_tags
        assert ("northstarida.azurecr.io/compose/digitron-orchestrator", "1.0.9") in repo_tags


class TestExtractComponentRefsFromMinimalFixture:
    """Tests extract_component_refs against minimal.yaml fixture."""

    def test_minimal_fixture_yields_one_ref(self, minimal_doc: dict) -> None:
        """minimal.yaml should yield exactly 1 component ref."""
        refs, skipped = extract_component_refs(minimal_doc)
        assert len(refs) == 1
        assert len(skipped) == 0

    def test_minimal_fixture_component_has_properties(self, minimal_doc: dict) -> None:
        """minimal.yaml component should have repository and revision."""
        refs, _ = extract_component_refs(minimal_doc)
        assert refs[0].name == "hello-world-compose"
        assert refs[0].repository == "example.com/compose/hello-world"
        assert refs[0].tag == "1.0.0"


class TestExtractComponentRefsFromMissingRecommendedFixture:
    """Tests extract_component_refs against missing-recommended.yaml fixture."""

    def test_missing_recommended_fixture_yields_one_ref(self, missing_recommended_doc: dict) -> None:
        """missing-recommended.yaml should yield exactly 1 component ref."""
        refs, skipped = extract_component_refs(missing_recommended_doc)
        assert len(refs) == 1
        assert len(skipped) == 0

    def test_missing_recommended_fixture_component(self, missing_recommended_doc: dict) -> None:
        """Component from missing-recommended.yaml."""
        refs, _ = extract_component_refs(missing_recommended_doc)
        assert refs[0].name == "plain-service-compose"
        assert refs[0].repository == "example.com/compose/plain-service"
        assert refs[0].tag == "2.0.0"


class TestExtractComponentRefsStripScheme:
    """Tests that extract_component_refs strips oci:// scheme."""

    def test_strips_oci_scheme_from_repository(self) -> None:
        """Repository values with oci:// prefix should be stripped."""
        doc = {
            "deploymentProfiles": [
                {
                    "components": [
                        {
                            "name": "test-comp",
                            "properties": {
                                "repository": "oci://quay.io/charts/test",
                                "revision": "1.0.0",
                            },
                        }
                    ]
                }
            ]
        }
        refs, _ = extract_component_refs(doc)
        assert len(refs) == 1
        assert refs[0].repository == "quay.io/charts/test"

    def test_handles_repository_without_oci_scheme(self) -> None:
        """Repository values without scheme should be returned as-is."""
        doc = {
            "deploymentProfiles": [
                {
                    "components": [
                        {
                            "name": "test-comp",
                            "properties": {
                                "repository": "quay.io/charts/test",
                                "revision": "1.0.0",
                            },
                        }
                    ]
                }
            ]
        }
        refs, _ = extract_component_refs(doc)
        assert len(refs) == 1
        assert refs[0].repository == "quay.io/charts/test"


class TestExtractComponentRefsMissingProperties:
    """Tests that missing or incomplete properties are skipped silently."""

    def test_skips_component_without_properties(self) -> None:
        """Component with no properties field should be skipped."""
        doc = {
            "deploymentProfiles": [
                {
                    "components": [
                        {
                            "name": "orphan-comp",
                            # No properties field
                        }
                    ]
                }
            ]
        }
        refs, skipped = extract_component_refs(doc)
        assert len(refs) == 0
        assert "orphan-comp" in skipped

    def test_skips_component_without_repository(self) -> None:
        """Component with properties but no repository should be skipped."""
        doc = {
            "deploymentProfiles": [
                {
                    "components": [
                        {
                            "name": "incomplete-comp",
                            "properties": {
                                "revision": "1.0.0",
                                # No repository
                            },
                        }
                    ]
                }
            ]
        }
        refs, skipped = extract_component_refs(doc)
        assert len(refs) == 0
        assert "incomplete-comp" in skipped

    def test_skips_component_without_revision(self) -> None:
        """Component with properties but no revision should be skipped."""
        doc = {
            "deploymentProfiles": [
                {
                    "components": [
                        {
                            "name": "incomplete-comp",
                            "properties": {
                                "repository": "quay.io/charts/test",
                                # No revision
                            },
                        }
                    ]
                }
            ]
        }
        refs, skipped = extract_component_refs(doc)
        assert len(refs) == 0
        assert "incomplete-comp" in skipped

    def test_skips_component_with_empty_repository(self) -> None:
        """Component with empty repository string should be skipped."""
        doc = {
            "deploymentProfiles": [
                {
                    "components": [
                        {
                            "name": "empty-repo-comp",
                            "properties": {
                                "repository": "",
                                "revision": "1.0.0",
                            },
                        }
                    ]
                }
            ]
        }
        refs, skipped = extract_component_refs(doc)
        assert len(refs) == 0
        assert "empty-repo-comp" in skipped

    def test_skips_component_with_empty_revision(self) -> None:
        """Component with empty revision string should be skipped."""
        doc = {
            "deploymentProfiles": [
                {
                    "components": [
                        {
                            "name": "empty-revision-comp",
                            "properties": {
                                "repository": "quay.io/charts/test",
                                "revision": "",
                            },
                        }
                    ]
                }
            ]
        }
        refs, skipped = extract_component_refs(doc)
        assert len(refs) == 0
        assert "empty-revision-comp" in skipped


class TestExtractComponentRefsDeduplication:
    """Tests that duplicate (repository, tag) pairs are deduplicated."""

    def test_deduplicates_same_repo_tag_across_profiles(self) -> None:
        """Same (repo, tag) declared in two profiles should yield one ref."""
        doc = {
            "deploymentProfiles": [
                {
                    "components": [
                        {
                            "name": "db-helm",
                            "properties": {
                                "repository": "quay.io/charts/db",
                                "revision": "1.0.0",
                            },
                        }
                    ]
                },
                {
                    "components": [
                        {
                            "name": "db-compose",
                            "properties": {
                                "repository": "quay.io/charts/db",
                                "revision": "1.0.0",
                            },
                        }
                    ]
                },
            ]
        }
        refs, _ = extract_component_refs(doc)
        assert len(refs) == 1
        # Should keep the first-seen name
        assert refs[0].name == "db-helm"

    def test_preserves_first_seen_order_after_dedup(self) -> None:
        """Refs should appear in first-seen (repo, tag) order."""
        doc = {
            "deploymentProfiles": [
                {
                    "components": [
                        {
                            "name": "first",
                            "properties": {
                                "repository": "quay.io/first",
                                "revision": "1.0",
                            },
                        },
                        {
                            "name": "second",
                            "properties": {
                                "repository": "quay.io/second",
                                "revision": "2.0",
                            },
                        },
                    ]
                }
            ]
        }
        refs, _ = extract_component_refs(doc)
        assert len(refs) == 2
        assert refs[0].name == "first"
        assert refs[1].name == "second"


class TestExtractComponentRefsEmptyDocument:
    """Tests extract_component_refs on edge cases."""

    def test_empty_document(self) -> None:
        """Empty doc should yield zero refs and no skipped."""
        refs, skipped = extract_component_refs({})
        assert len(refs) == 0
        assert len(skipped) == 0

    def test_no_deployment_profiles(self) -> None:
        """Doc without deploymentProfiles should yield zero refs."""
        doc = {"apiVersion": "v1", "kind": "ApplicationDescription"}
        refs, skipped = extract_component_refs(doc)
        assert len(refs) == 0
        assert len(skipped) == 0

    def test_empty_deployment_profiles(self) -> None:
        """Doc with empty deploymentProfiles array should yield zero refs."""
        doc = {"deploymentProfiles": []}
        refs, skipped = extract_component_refs(doc)
        assert len(refs) == 0
        assert len(skipped) == 0

    def test_profiles_with_empty_components(self) -> None:
        """Profiles with empty components arrays should yield zero refs."""
        doc = {"deploymentProfiles": [{"components": []}]}
        refs, skipped = extract_component_refs(doc)
        assert len(refs) == 0
        assert len(skipped) == 0
