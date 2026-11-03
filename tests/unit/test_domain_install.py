"""Unit tests for domain/install.py: profile selection, component specs, payload and merge checks,
unit-to-service derivation (sprint-13 spike S1), the ownership marker, and the plan dataclasses."""

from pytest import fixture, mark, raises

from margot.domain import install as install_domain
from margot.domain.install import (
    ComponentEntry,
    ComponentFiles,
    ComponentSpec,
    InstallRecord,
    SourceRecord,
    application_dir_name,
    check_payload,
    component_specs,
    merge_components,
    record_from_dict,
    select_profile,
    start_targets,
    unapplied_parameters,
    unit_service_name,
)


def _quadlet_profile(profile_id: str = "quadlet-v1", components: list | None = None) -> dict:
    return {
        "id": profile_id,
        "type": "quadlet",
        "components": components
        if components is not None
        else [
            {
                "name": "mosquitto-quadlet",
                "properties": {"repository": "oci://public.ecr.aws/g2n4p2m7/belden-margo", "revision": "1.0.2_x"},
            }
        ],
    }


def _doc(*profiles: dict, parameters: dict | None = None) -> dict:
    doc: dict = {"kind": "ApplicationDescription", "id": "com-example-app", "deploymentProfiles": list(profiles)}
    if parameters is not None:
        doc["parameters"] = parameters
    return doc


class TestSelectProfile:
    """Profile selection rows of sprint-13 §3.3."""

    def test_single_quadlet_profile_is_selected_without_id(self) -> None:
        """Should select the only quadlet profile when no --profile is given."""
        doc = _doc(_quadlet_profile("quadlet-v1"), {"id": "c", "type": "compose", "components": []})

        assert select_profile(doc)["id"] == "quadlet-v1"

    def test_several_quadlet_profiles_without_id_exit_3(self) -> None:
        """Should refuse with a ValueError listing the ids when several quadlet profiles exist."""
        doc = _doc(_quadlet_profile("a"), _quadlet_profile("b"))

        with raises(ValueError, match=r"Several quadlet deployment profiles.*a.*b"):
            select_profile(doc)

    def test_app_with_compose_and_quadlet_installs_quadlet_without_id(self) -> None:
        """Should select the quadlet profile when a compose profile is also present."""
        doc = _doc({"id": "compose-v1", "type": "compose", "components": []}, _quadlet_profile("quadlet-v1"))

        assert select_profile(doc)["type"] == "quadlet"

    def test_no_installable_profile_exits_3(self) -> None:
        """Should refuse when the description has no quadlet profile at all."""
        doc = _doc({"id": "helm-v1", "type": "helm", "components": []})

        with raises(ValueError, match=r"No quadlet deployment profile"):
            select_profile(doc)

    def test_no_profiles_at_all_exits_3(self) -> None:
        """Should refuse when the description has no deploymentProfiles."""
        with raises(ValueError, match=r"no deployment profiles"):
            select_profile({"kind": "ApplicationDescription"})

    def test_explicit_quadlet_id_is_selected(self) -> None:
        """Should return the profile whose id matches --profile."""
        doc = _doc(_quadlet_profile("quadlet-v1"), _quadlet_profile("quadlet-v2"))

        assert select_profile(doc, "quadlet-v2")["id"] == "quadlet-v2"

    def test_unknown_id_lists_available_profiles(self) -> None:
        """Should name the missing id and list the available ids with their types."""
        doc = _doc(_quadlet_profile("quadlet-v1"), {"id": "compose-v1", "type": "compose", "components": []})

        with raises(ValueError, match=r"No deployment profile with id 'nope'.*quadlet-v1 \(quadlet\).*compose-v1 \(compose\)"):
            select_profile(doc, "nope")

    def test_explicit_compose_profile_is_refused_as_not_supported_yet(self) -> None:
        """Should refuse a compose profile with the 'not supported yet' message."""
        doc = _doc({"id": "compose-v1", "type": "compose", "components": []}, _quadlet_profile("quadlet-v1"))

        with raises(ValueError, match=r"compose.*not supported yet"):
            select_profile(doc, "compose-v1")

    def test_explicit_helm_profile_is_refused(self) -> None:
        """Should refuse a helm profile with the 'not supported' message."""
        doc = _doc({"id": "helm-v1", "type": "helm", "components": []})

        with raises(ValueError, match=r"helm.*not supported"):
            select_profile(doc, "helm-v1")


class TestComponentSpecs:
    """Component validation rules of sprint-13 §3.3."""

    def test_valid_component_is_returned_with_scheme_stripped(self) -> None:
        """Should return name, repository without oci:// and revision."""
        specs = component_specs(_quadlet_profile())

        assert specs == [
            ComponentSpec(
                name="mosquitto-quadlet",
                repository="public.ecr.aws/g2n4p2m7/belden-margo",
                revision="1.0.2_x",
            )
        ]

    def test_component_spec_tag_and_reference(self) -> None:
        """Should expose the archive tag (+ replaced by _) and the OCI reference."""
        spec = ComponentSpec(name="n", repository="registry/repo", revision="1.0.2+quadlet")

        assert spec.tag == "1.0.2_quadlet"
        assert spec.reference == "registry/repo:1.0.2+quadlet"

    def test_profile_without_components_is_refused(self) -> None:
        """Should refuse a quadlet profile with no components."""
        with raises(ValueError, match=r"has no components"):
            component_specs(_quadlet_profile(components=[]))

    @mark.parametrize("missing", ["repository", "revision"])
    def test_component_without_repository_or_revision_is_refused(self, missing: str) -> None:
        """Should name the component when repository or revision is missing."""
        props = {"repository": "r/x", "revision": "1"}
        del props[missing]
        profile = _quadlet_profile(components=[{"name": "web", "properties": props}])

        with raises(ValueError, match=r"'web'.*no properties.repository and properties.revision"):
            component_specs(profile)

    def test_package_location_component_is_refused_with_limitation_message(self) -> None:
        """Should refuse a component located by packageLocation and name it."""
        profile = _quadlet_profile(components=[{"name": "web", "properties": {"packageLocation": "https://x/y.tgz"}}])

        with raises(ValueError, match=r"'web'.*packageLocation"):
            component_specs(profile)

    def test_component_without_name_is_refused(self) -> None:
        """Should refuse a component that has no name."""
        profile = _quadlet_profile(components=[{"properties": {"repository": "r", "revision": "1"}}])

        with raises(ValueError, match=r"has no name"):
            component_specs(profile)

    def test_unsafe_component_name_is_refused_and_rendered_as_data(self) -> None:
        """Should refuse a name with a path separator, quoting it as data."""
        profile = _quadlet_profile(components=[{"name": "../evil", "properties": {"repository": "r", "revision": "1"}}])

        with raises(ValueError, match=r"cannot be used as a directory name"):
            component_specs(profile)


class TestApplicationDirName:
    """The application id becomes the install directory name."""

    def test_plain_id_is_used_as_is(self) -> None:
        """Should keep a normal descriptor id unchanged."""
        assert application_dir_name("com-belden-mosquitto") == "com-belden-mosquitto"

    @mark.parametrize("bad", ["", "a/b", "..", "."])
    def test_unsafe_id_is_refused(self, bad: str) -> None:
        """Should refuse ids that cannot be a single directory name."""
        with raises(ValueError, match=r"cannot be used as a directory name"):
            application_dir_name(bad)


class TestUnitServiceName:
    """Service names from file names, per spike S1 (sprint-13 §4 'Spike results')."""

    @mark.parametrize(
        ("filename", "service"),
        [
            ("web.container", "web.service"),
            ("web.kube", "web.service"),
            ("data.volume", "data-volume.service"),
            ("net.network", "net-network.service"),
            ("pod.pod", "pod-pod.service"),
            ("busybox.image", "busybox-image.service"),
            ("app.build", "app-build.service"),
            ("art.artifact", "art-artifact.service"),
            ("my.app.container", "my.app.service"),
        ],
    )
    def test_service_name_per_suffix(self, filename: str, service: str) -> None:
        """Should derive the generated service name for each quadlet suffix."""
        assert unit_service_name(filename) == service

    def test_nested_path_uses_only_the_file_name(self) -> None:
        """Should ignore sub-directories: the service name comes from the file name."""
        assert unit_service_name("sub/deep/nested.container") == "nested.service"

    def test_non_unit_file_is_not_a_unit(self) -> None:
        """Should report that a non-quadlet file has no unit."""
        assert install_domain.is_quadlet_file("notes.txt") is False
        assert install_domain.is_quadlet_file("sub/web.container") is True


class TestCheckPayload:
    """Payload validation: a quadlet component must ship a unit at its root (sprint-13 §3.4)."""

    def test_root_unit_passes(self) -> None:
        """Should accept a payload with a quadlet unit at its root."""
        check_payload("web", ["web.container", "conf/nginx.conf"])

    def test_nested_unit_only_is_refused(self) -> None:
        """Should refuse a payload whose only unit sits in a sub-directory."""
        with raises(ValueError, match=r"'web'.*no quadlet unit"):
            check_payload("web", ["sub/web.container"])

    def test_compose_payload_is_refused_with_collision_hint(self) -> None:
        """Should say the payload is a compose file, not quadlet units (flat collision)."""
        with raises(ValueError, match=r"compose file"):
            check_payload("web", ["compose.yaml"])

    def test_empty_payload_is_refused(self) -> None:
        """Should refuse an empty payload."""
        with raises(ValueError, match=r"no quadlet unit"):
            check_payload("web", [])


class TestMergeComponents:
    """Merge validation across selected components (sprint-13 §3.4)."""

    def test_disjoint_components_merge_and_derive_units(self) -> None:
        """Should merge disjoint components and derive one unit per unit file."""
        merged = merge_components(
            [
                ComponentFiles(name="a", source_key="k1", files=("a.container", "conf/a.conf")),
                ComponentFiles(name="b", source_key="k2", files=("b.volume",)),
            ]
        )

        assert [u.relpath for u in merged.units] == ["a.container", "b.volume"]
        assert [u.service for u in merged.units] == ["a.service", "b-volume.service"]
        assert merged.owners["conf/a.conf"] == "a"

    def test_same_path_in_two_components_is_refused(self) -> None:
        """Should name both components and the clashing path."""
        with raises(ValueError, match=r"'a' and 'b' both ship 'shared.conf'"):
            merge_components(
                [
                    ComponentFiles(name="a", source_key="k1", files=("shared.conf",)),
                    ComponentFiles(name="b", source_key="k2", files=("shared.conf",)),
                ]
            )

    def test_same_artifact_under_two_names_is_not_a_clash(self) -> None:
        """Should accept one artifact installed for two components (same content, same key)."""
        merged = merge_components(
            [
                ComponentFiles(name="a", source_key="same", files=("web.container",)),
                ComponentFiles(name="b", source_key="same", files=("web.container",)),
            ]
        )

        assert [u.relpath for u in merged.units] == ["web.container"]

    def test_same_service_name_from_two_paths_is_refused(self) -> None:
        """Should refuse two units that generate the same service (kube and container of one name)."""
        with raises(ValueError, match=r"both generate 'web.service'"):
            merge_components(
                [
                    ComponentFiles(name="a", source_key="k1", files=("web.container",)),
                    ComponentFiles(name="b", source_key="k2", files=("web.kube",)),
                ]
            )


class TestStartTargets:
    """Only workloads get a printed start command (sprint-13 §3.7, decision note in §4)."""

    def test_containers_kubes_and_pods_are_start_targets(self) -> None:
        """Should return the services of container, kube and pod units only."""
        units = merge_components(
            [
                ComponentFiles(
                    name="a",
                    source_key="k",
                    files=("web.container", "data.volume", "net.network", "p.pod", "k.kube"),
                )
            ]
        ).units

        assert start_targets(units) == ["web.service", "p-pod.service", "k.service"]


class TestUnappliedParameters:
    """Declared parameters are not applied in Step 1."""

    def test_all_declared_parameters_are_reported_sorted(self) -> None:
        """Should list every declared parameter name, sorted."""
        doc = _doc(_quadlet_profile(), parameters={"zeta": {"value": 1}, "alpha": {"value": "x"}})

        assert unapplied_parameters(doc) == ["alpha", "zeta"]

    def test_no_parameters_reports_nothing(self) -> None:
        """Should return an empty list when the description declares no parameters."""
        assert unapplied_parameters(_doc(_quadlet_profile())) == []


class TestInstallRecord:
    """The ownership marker round trip (sprint-13 §3.8)."""

    @fixture
    def record(self) -> InstallRecord:
        """A fully populated installed record."""
        return InstallRecord(
            state="installed",
            app_id="com-belden-mosquitto",
            app_name="Eclipse Mosquitto",
            app_version="1.0.3",
            profile_id="quadlet-v1",
            installed_at="2026-11-03T10:00:00Z",
            source=SourceRecord(kind="remote", uri="public.ecr.aws/g2n4p2m7/belden-margo:1.0.3", path=None),
            components=(
                ComponentEntry(
                    name="mosquitto-quadlet",
                    repository="public.ecr.aws/g2n4p2m7/belden-margo",
                    revision="1.0.2_mosquitto-quadlet",
                    archive_sha256="ab" * 32,
                    files=("mosquitto.container", "conf/mosquitto.conf"),
                ),
            ),
            services=("mosquitto.service",),
            parameters=(),
        )

    def test_to_dict_uses_marker_field_names(self, record: InstallRecord) -> None:
        """Should serialise with the documented camelCase keys and schema 1."""
        data = record.to_dict()

        assert data["schema"] == 1
        assert data["appId"] == "com-belden-mosquitto"
        assert data["components"][0]["archiveSha256"] == "ab" * 32
        assert data["services"] == ["mosquitto.service"]
        assert data["source"] == {"kind": "remote", "uri": "public.ecr.aws/g2n4p2m7/belden-margo:1.0.3"}

    def test_round_trip_is_lossless(self, record: InstallRecord) -> None:
        """Should read back exactly what it wrote."""
        assert record_from_dict(record.to_dict()) == record

    def test_unknown_schema_is_refused(self, record: InstallRecord) -> None:
        """Should refuse a marker with a schema number it does not know."""
        data = record.to_dict()
        data["schema"] = 2

        with raises(ValueError, match=r"schema"):
            record_from_dict(data)

    def test_unknown_state_is_refused(self, record: InstallRecord) -> None:
        """Should refuse a marker whose state is not installing or installed."""
        data = record.to_dict()
        data["state"] = "broken"

        with raises(ValueError, match=r"state"):
            record_from_dict(data)
