"""Component reference extraction from rendered application descriptions.

This module extracts OCI component references from the pulled app.yaml content,
enabling recursive pulling of component artifacts declared in deployment profiles.

All functions are pure domain logic — no I/O, no console imports.
"""

from dataclasses import dataclass

from margot.domain.uri import strip_scheme


@dataclass(frozen=True)
class ComponentRef:
    """A deduplicated component reference: name, repository, and tag.

    Attributes:
        name: Component name as declared in the application description.
        repository: OCI repository (oci:// scheme stripped).
        tag: Version/tag for the component artifact.
    """

    name: str
    repository: str
    tag: str

    @property
    def ref(self) -> str:
        """Return the OCI reference as repository:tag."""
        return f"{self.repository}:{self.tag}"


def extract_component_refs(app_yaml_doc: dict) -> tuple[list[ComponentRef], list[str]]:
    """Extract and deduplicate component references from an application description.

    Walks deploymentProfiles[].components[] and extracts components that have both:
    - properties.repository (OCI URI, oci:// scheme optional)
    - properties.revision (version tag)

    Components missing either field are silently skipped and included in the
    returned skipped list.

    Deduplicates by (repository, tag) pair, preserving first-seen order and the
    name from the first occurrence of each unique (repository, tag) pair.

    Args:
        app_yaml_doc: Parsed application description dict (from YAML load).

    Returns:
        A tuple of (valid_refs, skipped_names):
        - valid_refs: List of ComponentRef in first-seen order, deduplicated by
          (repository, tag).
        - skipped_names: List of component names that were skipped due to missing
          properties.repository or properties.revision.

    Examples:
        Extract from complex.yaml with 2 deployment profiles, 2 components:
        >>> refs, skipped = extract_component_refs(doc)
        >>> len(refs)
        2
        >>> refs[0].ref
        'quay.io/charts/realtime-database-services:2.3.7'

        Extract from minimal.yaml with incomplete component properties:
        >>> refs, skipped = extract_component_refs(doc)
        >>> len(refs)
        1
        >>> refs[0].name
        'hello-world-compose'
    """
    seen_refs: dict[tuple[str, str], None] = {}  # Track (repository, tag) pairs
    valid_refs: list[ComponentRef] = []
    skipped_names: list[str] = []

    for profile in app_yaml_doc.get("deploymentProfiles") or []:
        for component in profile.get("components") or []:
            component_name = component.get("name")
            properties = component.get("properties") or {}

            # Extract repository and revision
            repository_raw = properties.get("repository")
            revision = properties.get("revision")

            # Skip if either is missing
            if not repository_raw or not revision:
                if component_name:
                    skipped_names.append(component_name)
                continue

            # Strip oci:// scheme if present
            repository = strip_scheme(repository_raw)

            # Create ref and check for deduplication
            ref_key = (repository, revision)
            if ref_key in seen_refs:
                # Already seen this (repo, tag) pair; skip the duplicate
                continue
            seen_refs[ref_key] = None

            # Add to valid refs
            component_ref = ComponentRef(name=component_name or "unknown", repository=repository, tag=revision)
            valid_refs.append(component_ref)

    return valid_refs, skipped_names
