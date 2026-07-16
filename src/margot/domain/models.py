"""Domain models: enums and pure mapping functions."""

from enum import StrEnum

_ARTIFACT_TYPE_MAP: dict[str, "PackageType"] = {}


class PackageType(StrEnum):
    """Margo artifact package types."""

    MARGO = "margo"
    COMPOSE = "compose"
    QUADLET = "quadlet"
    UNKNOWN = "unknown"


_ARTIFACT_TYPE_MAP = {
    "application/vnd.margo.app.v1+json": PackageType.MARGO,
    "application/vnd.org.margo.component.compose+json": PackageType.COMPOSE,
    "application/vnd.org.margo.component.quadlet+json": PackageType.QUADLET,
}


def artifact_type_to_package_type(artifact_type: str | None) -> PackageType:
    """Map OCI artifactType string to PackageType.

    Args:
        artifact_type: The OCI artifactType field value, or None.

    Returns:
        The matching PackageType, or PackageType.UNKNOWN for unrecognised values.
    """
    if artifact_type is None:
        return PackageType.UNKNOWN
    return _ARTIFACT_TYPE_MAP.get(artifact_type, PackageType.UNKNOWN)
