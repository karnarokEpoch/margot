"""Unit tests for the pure guard rules in domain/install.py: search roots, candidates and unit collisions."""


from pytest import fixture, mark, raises

from margot.domain import install as domain


@fixture
def roots() -> tuple[str, ...]:
    """Search roots for runtime dir /run/user/1000, config root /home/u/.config/containers/systemd, uid 1000."""
    return domain.search_path_roots("/run/user/1000", "/home/u/.config/containers/systemd", 1000)


class TestSearchPathRoots:
    """The six search-path roots of the user manager, in Quadlet's order."""

    def test_all_six_roots_are_listed_in_quadlet_order(self, roots: tuple[str, ...]) -> None:
        """Should list the runtime, config and four system roots, with $UID substituted."""
        assert roots == (
            "/run/user/1000/containers/systemd",
            "/home/u/.config/containers/systemd",
            "/etc/containers/systemd/users/1000",
            "/etc/containers/systemd/users",
            "/usr/share/containers/systemd/users/1000",
            "/usr/share/containers/systemd/users",
        )

    def test_unset_runtime_dir_drops_only_the_runtime_root(self) -> None:
        """Should omit the runtime root when XDG_RUNTIME_DIR is not set."""
        result = domain.search_path_roots(None, "/home/u/.config/containers/systemd", 1000)

        assert result[0] == "/home/u/.config/containers/systemd"
        assert len(result) == 5

    def test_empty_runtime_dir_is_treated_as_unset(self) -> None:
        """Should treat an empty XDG_RUNTIME_DIR as unset: the first root is the config root."""
        assert domain.search_path_roots("", "/c", 7)[0] == "/c"

    def test_relative_runtime_dir_is_ignored(self) -> None:
        """Should ignore a relative XDG_RUNTIME_DIR, as the XDG rule requires."""
        result = domain.search_path_roots("run/user", "/c", 7)

        assert all(not root.startswith("run/") for root in result)

    def test_uid_is_substituted_in_the_system_roots(self) -> None:
        """Should put the given uid into the /etc and /usr/share per-user directories."""
        result = domain.search_path_roots(None, "/c", 4242)

        assert "/etc/containers/systemd/users/4242" in result
        assert "/usr/share/containers/systemd/users/4242" in result


class TestCandidates:
    """Only visible quadlet unit file names are candidates; hidden, marker, drop-in and non-unit files are not."""

    @mark.parametrize("name", ["web.container", "data.volume", "net.network", "app.kube", "x.artifact", "y.image"])
    def test_quadlet_names_are_candidates(self, name: str) -> None:
        """Should accept every quadlet source suffix."""
        assert domain.is_unit_candidate(name)

    @mark.parametrize(
        "name",
        [".hidden.container", ".margot-install.json", "90-local.conf", "README.md", "web.container.d", "webcontainer"],
    )
    def test_hidden_marker_drop_in_and_non_unit_names_are_not_candidates(self, name: str) -> None:
        """Should ignore hidden files, the marker, drop-in files and anything without a quadlet suffix."""
        assert not domain.is_unit_candidate(name)


class TestUnitConflicts:
    """Collisions between the units to install and the files already in the Quadlet search path."""

    OWN = "/home/u/.config/containers/systemd/com-new"

    def test_no_conflict_when_nothing_is_found(self) -> None:
        """Should return no conflicts for an empty search path."""
        assert domain.find_unit_conflicts([f"{self.OWN}/web.container"], [], self.OWN) == []

    def test_same_file_name_in_another_directory_conflicts(self) -> None:
        """Should report a file-name collision that names both paths."""
        existing = "/home/u/.config/containers/systemd/com-other/web.container"

        conflicts = domain.find_unit_conflicts([f"{self.OWN}/web.container"], [existing], self.OWN)

        assert len(conflicts) == 1
        assert conflicts[0].reason == "file name"
        assert conflicts[0].target == f"{self.OWN}/web.container"
        assert conflicts[0].existing == existing

    def test_kube_and_container_with_same_stem_conflict_on_the_service_name(self) -> None:
        """Should report a service-name collision when <name>.kube and <name>.container share a stem."""
        existing = "/home/u/.config/containers/systemd/com-other/foo.kube"

        conflicts = domain.find_unit_conflicts([f"{self.OWN}/foo.container"], [existing], self.OWN)

        assert len(conflicts) == 1
        assert conflicts[0].reason == "service name"
        assert conflicts[0].name == "foo.service"

    def test_same_stem_with_different_generated_services_does_not_conflict(self) -> None:
        """Should not flag data.volume against data.network: they generate data-volume.service and data-network.service."""
        existing = "/etc/containers/systemd/users/1000/data.network"

        assert domain.find_unit_conflicts([f"{self.OWN}/data.volume"], [existing], self.OWN) == []

    def test_files_of_the_application_own_directory_are_allowed(self) -> None:
        """Should allow a unit that already sits in the application's own directory (upgrade)."""
        existing = f"{self.OWN}/web.container"

        assert domain.find_unit_conflicts([f"{self.OWN}/web.container"], [existing], self.OWN) == []

    def test_hidden_marker_drop_in_and_non_unit_files_never_conflict(self) -> None:
        """Should ignore hidden files, the marker, drop-ins and non-unit files in the search path."""
        found = [
            "/home/u/.config/containers/systemd/com-other/.web.container",
            "/home/u/.config/containers/systemd/com-other/.margot-install.json",
            "/home/u/.config/containers/systemd/com-other/web.container.d/web.conf",
            "/home/u/.config/containers/systemd/com-other/web.conf",
            "/home/u/.config/containers/systemd/com-other/web.container.d/50-margot.conf",
        ]

        assert domain.find_unit_conflicts([f"{self.OWN}/web.container"], found, self.OWN) == []

    def test_every_conflict_is_reported_once_per_pair(self) -> None:
        """Should report each clashing pair, not one error per run."""
        found = [
            "/home/u/.config/containers/systemd/a/web.container",
            "/etc/containers/systemd/users/web.kube",
        ]
        targets = [f"{self.OWN}/web.container", f"{self.OWN}/db.container"]

        conflicts = domain.find_unit_conflicts(targets, found, self.OWN)

        assert [(c.target, c.existing) for c in conflicts] == [
            (f"{self.OWN}/web.container", "/home/u/.config/containers/systemd/a/web.container"),
            (f"{self.OWN}/web.container", "/etc/containers/systemd/users/web.kube"),
        ]

    def test_same_path_listed_twice_is_one_conflict(self) -> None:
        """Should deduplicate the search-path listing so one file is reported once."""
        existing = "/home/u/.config/containers/systemd/a/web.container"

        conflicts = domain.find_unit_conflicts([f"{self.OWN}/web.container"], [existing, existing], self.OWN)

        assert len(conflicts) == 1

    def test_sibling_with_a_prefix_name_is_not_the_own_directory(self) -> None:
        """Should not treat com-new-other as inside com-new (path parts, not string prefixes)."""
        existing = "/home/u/.config/containers/systemd/com-new-other/web.container"

        conflicts = domain.find_unit_conflicts([f"{self.OWN}/web.container"], [existing], self.OWN)

        assert len(conflicts) == 1

    def test_unit_service_name_rejects_non_unit_paths(self) -> None:
        """Should refuse to derive a service name for a file that is not a quadlet unit."""
        with raises(ValueError, match=r"not a quadlet unit"):
            domain.unit_service_name("conf/mosquitto.conf")
