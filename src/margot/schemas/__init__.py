"""Vendored LinkML schemas shipped with margot (data, not code)."""

from importlib.resources import files

# Upstream Margo specification schema, pinned to a draft commit. The spec is not
# released yet: this SHA is what `margot verify` reports so results are never mistaken
# for validation against a stable spec.
SCHEMA_A_COMMIT = "45f4359d129c1f04532d17b358d6f50eaa3ca62f"
SCHEMA_A_SHORT_COMMIT = SCHEMA_A_COMMIT[:7]
SCHEMA_A_URL = (
    "https://github.com/margo/specification/blob/"
    f"{SCHEMA_A_COMMIT}/src/specification/applications/application-description.linkml.yaml"
)

# Root class of the upstream schema. It declares several candidate root classes
# (ApplicationDescription plus the profile/schema subclasses), so LinkML cannot infer
# one and the target class must be passed explicitly.
SCHEMA_A_TARGET_CLASS = "ApplicationDescription"

SCHEMA_A_PATH = str(files("margot.schemas") / "application-description.linkml.yaml")
