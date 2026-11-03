"""Integration tests for services/install.py::prepare_install: project, static and remote sources.

The remote path fakes only the registry boundary (prepare_oci_retrieval, pull_prepared_context and the
remote descriptor resolver). Nothing here touches systemd or the Quadlet directory.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pytest import fixture, mark, raises

from margot.domain.models import PackageType
from margot.infra.credentials import CredentialsExpiredError
from margot.services import install as install_service
from margot.services.remote import ResolvedRemoteDescriptor
from tests.integration._install_helpers import (
    MOSQUITTO_QUADLET_TAG,
    REPOSITORY,
    app_description,
    build_project,
    build_static_folder,
    quadlet_payload,
    write_tar,
)

REFERENCE = f"{REPOSITORY}:1.0.2+mosquitto-quadlet"


@fixture(autouse=True)
def isolated_staging(monkeypatch: Any, tmp_path: Path) -> Path:
    """Point the Quadlet root and the temp directory at tmp_path, so staging leftovers are visible."""
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    staging_tmp = tmp_path / "tmp"
    staging_tmp.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(staging_tmp))
    return staging_tmp


def _leftover_staging(staging_tmp: Path) -> list[str]:
    return sorted(p.name for p in staging_tmp.iterdir() if p.name.startswith("margot-install-"))


class TestProjectSource:
    """A built project: the descriptor and archives come from the build directory only (sprint-13 §3.4)."""

    def test_built_project_is_staged_and_planned(self, tmp_path: Path) -> None:
        """Should stage the built quadlet archive and build the plan from it."""
        project, build = build_project(tmp_path)

        prepared = install_service.prepare_install(uri=None, project_dir=str(project), build_dir=str(build), profile_id=None)
        try:
            plan = prepared.plan
            assert plan.app_id == "com-belden-mosquitto"
            assert plan.profile_id == "quadlet-v1"
            assert plan.source.kind == "project"
            assert plan.services == ("mosquitto.service",)
            assert sorted(plan.files) == [
                "conf/mosquitto.conf",
                "mosquitto.container",
                "mosquitto.container.d/50-margot-parameters.conf",
            ]
            component = plan.components[0]
            assert component.entry.repository == REPOSITORY
            assert component.entry.revision == "1.0.2+mosquitto-quadlet"
            assert len(component.entry.archive_sha256) == 64
            assert prepared.files["mosquitto.container"].is_file()
        finally:
            prepared.cleanup()

    def test_missing_build_directory_names_the_build_command(self, tmp_path: Path) -> None:
        """Should refuse with the 'margot build -t all' hint when the descriptor is not built."""
        project, _ = build_project(tmp_path)

        with raises(ValueError, match=r"margot build -t all"):
            install_service.prepare_install(
                uri=None, project_dir=str(project), build_dir=str(tmp_path / "nowhere"), profile_id=None
            )

    def test_missing_component_archive_is_listed_and_not_fetched(self, tmp_path: Path) -> None:
        """Should list the component that is not built, never fall back to the registry."""
        project, build = build_project(tmp_path)
        (build / MOSQUITTO_QUADLET_TAG / f"mosquitto-{MOSQUITTO_QUADLET_TAG}.tgz").unlink()

        with raises(ValueError, match=r"not built.*mosquitto-quadlet.*margot install <uri>"):
            install_service.prepare_install(uri=None, project_dir=str(project), build_dir=str(build), profile_id=None)

    def test_compose_payload_in_quadlet_profile_is_refused(self, tmp_path: Path) -> None:
        """Should refuse a quadlet profile whose archive holds a compose file (flat collision)."""
        project, build = build_project(tmp_path, archive_members={"compose.yaml": b"services: {}\n"})

        with raises(ValueError, match=r"compose file"):
            install_service.prepare_install(uri=None, project_dir=str(project), build_dir=str(build), profile_id=None)

    def test_unknown_profile_is_refused_with_available_list(self, tmp_path: Path) -> None:
        """Should refuse an unknown --profile id and list what exists."""
        project, build = build_project(tmp_path)

        with raises(ValueError, match=r"No deployment profile with id 'nope'"):
            install_service.prepare_install(uri=None, project_dir=str(project), build_dir=str(build), profile_id="nope")

    def test_staging_directory_is_removed_when_preparation_fails(self, tmp_path: Path, isolated_staging: Path) -> None:
        """Should leave no staging directory behind after a failed preparation."""
        project, build = build_project(tmp_path, archive_members={"compose.yaml": b"x"})

        with raises(ValueError, match=r"compose file"):
            install_service.prepare_install(uri=None, project_dir=str(project), build_dir=str(build), profile_id=None)

        assert _leftover_staging(isolated_staging) == []

    def test_cleanup_removes_the_staging_directory(self, tmp_path: Path, isolated_staging: Path) -> None:
        """Should remove the staging directory when the caller cleans up."""
        project, build = build_project(tmp_path)
        prepared = install_service.prepare_install(uri=None, project_dir=str(project), build_dir=str(build), profile_id=None)
        assert _leftover_staging(isolated_staging) != []

        prepared.cleanup()

        assert _leftover_staging(isolated_staging) == []

    def test_no_systemd_call_during_preparation(self, tmp_path: Path, mocker: Any) -> None:
        """Should never call systemctl while preparing (dry-run relies on this)."""
        run = mocker.patch("margot.infra.systemd.run")
        project, build = build_project(tmp_path)

        prepared = install_service.prepare_install(uri=None, project_dir=str(project), build_dir=str(build), profile_id=None)
        prepared.cleanup()

        run.assert_not_called()


class TestStaticSource:
    """A `pull --recursive` folder: app.yaml next to <component>/<one archive> (sprint-13 §3.4)."""

    def test_pulled_folder_is_staged_and_planned(self, tmp_path: Path) -> None:
        """Should read the single archive of the component folder and plan the install."""
        folder = build_static_folder(tmp_path)

        prepared = install_service.prepare_install(uri=None, project_dir=str(folder), build_dir=None, profile_id=None)
        try:
            assert prepared.plan.source.kind == "static"
            assert prepared.plan.source.path is not None
            assert prepared.plan.services == ("mosquitto.service",)
        finally:
            prepared.cleanup()

    def test_missing_component_folder_suggests_pull_recursive(self, tmp_path: Path) -> None:
        """Should name the expected folder and suggest 'margot pull --recursive'."""
        folder = build_static_folder(tmp_path)
        (folder / "mosquitto-quadlet" / "bundle.tgz").unlink()
        (folder / "mosquitto-quadlet").rmdir()

        with raises(ValueError, match=r"mosquitto-quadlet.*margot pull <uri> --recursive"):
            install_service.prepare_install(uri=None, project_dir=str(folder), build_dir=None, profile_id=None)

    def test_several_files_in_component_folder_are_refused(self, tmp_path: Path) -> None:
        """Should refuse a component folder that does not hold exactly one archive."""
        folder = build_static_folder(tmp_path)
        (folder / "mosquitto-quadlet" / "extra.tgz").write_bytes(b"x")

        with raises(ValueError, match=r"exactly one"):
            install_service.prepare_install(uri=None, project_dir=str(folder), build_dir=None, profile_id=None)

    def test_non_tar_component_file_is_refused(self, tmp_path: Path) -> None:
        """Should name the component when its only file is not a tar archive."""
        folder = build_static_folder(tmp_path)
        (folder / "mosquitto-quadlet" / "bundle.tgz").write_text("plain text", encoding="utf-8")

        with raises(ValueError, match=r"not a readable tar archive"):
            install_service.prepare_install(uri=None, project_dir=str(folder), build_dir=None, profile_id=None)

    def test_jinja_descriptor_without_margo_yaml_is_the_actionable_error(self, tmp_path: Path) -> None:
        """Should pass the Sprint 12 '.jinja without margo.yaml' error through unchanged."""
        folder = tmp_path / "templated"
        folder.mkdir()
        (folder / "app.yaml.jinja").write_text("kind: ApplicationDescription\n", encoding="utf-8")

        with raises(ValueError, match=r"app\.yaml\.jinja"):
            install_service.prepare_install(uri=None, project_dir=str(folder), build_dir=None, profile_id=None)

    def test_directory_without_descriptor_is_refused(self, tmp_path: Path) -> None:
        """Should refuse a directory with neither margo.yaml nor a static descriptor."""
        empty = tmp_path / "empty"
        empty.mkdir()

        with raises(ValueError, match=r"No application description|margo.yaml|app.yaml"):
            install_service.prepare_install(uri=None, project_dir=str(empty), build_dir=None, profile_id=None)


class TestRemoteSource:
    """Remote OCI artifacts through the faked registry boundary (sprint-13 §3.4)."""

    @fixture
    def remote_descriptor(self, tmp_path: Path, mocker: Any) -> Path:
        """Fake the margo artifact resolution: a pulled app.yaml held in a temporary directory."""
        temp = tmp_path / "remote-temp"
        temp.mkdir()
        app_yaml = temp / "app.yaml"
        app_yaml.write_text(app_description(repository=f"oci://{REPOSITORY}"), encoding="utf-8")
        resolved = ResolvedRemoteDescriptor(
            normalized_uri=f"{REPOSITORY}:1.0.3",
            app_yaml_path=str(app_yaml),
            temp_dir=SimpleNamespace(cleanup=lambda: None),
        )
        mocker.patch("margot.services.remote.resolve_remote_descriptor", return_value=resolved)
        return app_yaml

    @fixture
    def registry(self, mocker: Any, tmp_path: Path) -> SimpleNamespace:
        """Fake prepare_oci_retrieval/pull_prepared_context: one quadlet artifact whose payload is written on pull."""
        archive_members = quadlet_payload(root=None)

        def fake_prepare(reference: str) -> SimpleNamespace:
            return SimpleNamespace(
                normalized_uri=reference,
                package_type=PackageType.QUADLET,
                manifest={"artifactType": "application/vnd.org.margo.component.quadlet.v1+json", "layers": []},
            )

        def fake_pull(_prepared: Any, outdir: str, **_: Any) -> list[str]:
            archive = write_tar(Path(outdir) / "bundle-1.0.2.tgz", archive_members)
            return [str(archive)]

        mocker.patch("margot.services.pull.prepare_oci_retrieval", side_effect=fake_prepare)
        mocker.patch("margot.services.pull.pull_prepared_context", side_effect=fake_pull)
        return SimpleNamespace(prepare=fake_prepare)

    def test_remote_artifact_is_staged_and_planned(self, remote_descriptor: Path, registry: SimpleNamespace) -> None:
        """Should install a quadlet component pulled from the registry, using its reference."""
        prepared = install_service.prepare_install(
            uri=f"oci://{REPOSITORY}:1.0.3", project_dir=None, build_dir=None, profile_id=None
        )
        try:
            plan = prepared.plan
            assert plan.source.kind == "remote"
            assert plan.source.uri == f"{REPOSITORY}:1.0.3"
            assert plan.components[0].reference == REFERENCE
            assert plan.services == ("mosquitto.service",)
            assert sorted(plan.files) == [
                "conf/mosquitto.conf",
                "mosquitto.container",
                "mosquitto.container.d/50-margot-parameters.conf",
            ]
        finally:
            prepared.cleanup()

    def test_component_of_another_type_is_refused(self, remote_descriptor: Path, mocker: Any, tmp_path: Path) -> None:
        """Should refuse a component whose artifact is not a quadlet one."""
        mocker.patch(
            "margot.services.pull.prepare_oci_retrieval",
            return_value=SimpleNamespace(
                normalized_uri=REFERENCE,
                package_type=PackageType.COMPOSE,
                manifest={"artifactType": "application/vnd.org.margo.component.compose.v1+json"},
            ),
        )

        with raises(ValueError, match=r"'mosquitto-quadlet'.*not a quadlet component"):
            install_service.prepare_install(uri=f"{REPOSITORY}:1.0.3", project_dir=None, build_dir=None, profile_id=None)

    def test_expired_credentials_propagate_for_exit_4(self, remote_descriptor: Path, mocker: Any) -> None:
        """Should let CredentialsExpiredError through so the command can map it to exit 4."""
        mocker.patch("margot.services.pull.prepare_oci_retrieval", side_effect=CredentialsExpiredError("expired"))

        with raises(CredentialsExpiredError):
            install_service.prepare_install(uri=f"{REPOSITORY}:1.0.3", project_dir=None, build_dir=None, profile_id=None)

    def test_remote_temp_directories_are_removed_on_failure(self, tmp_path: Path, mocker: Any, isolated_staging: Path) -> None:
        """Should clean the descriptor's temporary directory and the staging directory when a component fails."""
        temp = tmp_path / "remote-temp-2"
        temp.mkdir()
        (temp / "app.yaml").write_text(app_description(), encoding="utf-8")
        cleaned: list[bool] = []
        resolved = ResolvedRemoteDescriptor(
            normalized_uri="x",
            app_yaml_path=str(temp / "app.yaml"),
            temp_dir=SimpleNamespace(cleanup=lambda: cleaned.append(True)),
        )
        mocker.patch("margot.services.remote.resolve_remote_descriptor", return_value=resolved)
        mocker.patch("margot.services.pull.prepare_oci_retrieval", side_effect=CredentialsExpiredError("expired"))

        with raises(CredentialsExpiredError):
            install_service.prepare_install(uri="x", project_dir=None, build_dir=None, profile_id=None)

        assert cleaned == [True]
        assert _leftover_staging(isolated_staging) == []

    def test_non_margot_shaped_artifact_installs(self, remote_descriptor: Path, mocker: Any) -> None:
        """Should install an archive with no top-level directory and other file names (sprint-13 §4 fixture)."""
        other_members = {"web.container": b"[Container]\nImage=docker.io/library/nginx:1\n", "site/index.html": b"<h1>x</h1>"}

        def pull(_prepared: Any, outdir: str, **_: Any) -> list[str]:
            return [str(write_tar(Path(outdir) / "layer-without-name", other_members))]

        mocker.patch(
            "margot.services.pull.prepare_oci_retrieval",
            return_value=SimpleNamespace(
                normalized_uri=REFERENCE,
                package_type=PackageType.QUADLET,
                manifest={"artifactType": "application/vnd.org.margo.component.quadlet.v1+json"},
            ),
        )
        mocker.patch("margot.services.pull.pull_prepared_context", side_effect=pull)

        prepared = install_service.prepare_install(uri=f"{REPOSITORY}:1.0.3", project_dir=None, build_dir=None, profile_id=None)
        try:
            assert sorted(prepared.plan.files) == [
                "site/index.html",
                "web.container",
                "web.container.d/50-margot-parameters.conf",
            ]
            assert prepared.plan.services == ("web.service",)
        finally:
            prepared.cleanup()


@mark.parametrize("missing", ["repository", "revision"])
def test_component_without_location_fails_before_any_pull(tmp_path: Path, mocker: Any, missing: str) -> None:
    """Should refuse before fetching anything when a component lacks repository or revision."""
    descriptor = app_description()
    descriptor = descriptor.replace(f"          {missing}:", f"          x{missing}:")
    folder = build_static_folder(tmp_path, descriptor=descriptor)
    run = mocker.patch("margot.services.pull.prepare_oci_retrieval")

    with raises(ValueError, match=r"mosquitto-quadlet"):
        install_service.prepare_install(uri=None, project_dir=str(folder), build_dir=None, profile_id=None)
    run.assert_not_called()
