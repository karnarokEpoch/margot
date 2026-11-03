"""Unit tests for the pure reading of Quadlet generator output (sprint-13 §3.10, guard 2).

The fixture lines are copied from `quadlet -dryrun -user` on the reference host (Podman 5.8.2) with
QUADLET_UNIT_DIRS pointing at a tree that holds a unit with an unresolved reference. The PIDs are the
ones the host printed; they are not significant.
"""

from pytest import mark

from margot.domain.install import group_generator_output, judge_generator, parse_generator_stderr, reference_only

PROGRESS_A = "quadlet-generator[811023]: Loading source unit file /tmp/gen-ref/app/a.container"
PROGRESS_B = "quadlet-generator[811023]: Loading source unit file /tmp/gen-ref/app/b.container"
PROGRESS_C = "quadlet-generator[811033]: Loading source unit file /tmp/gen-ref/app/c.container"
PROGRESS_DROPIN_B = (
    "quadlet-generator[817680]: Loading source drop-in file /tmp/gen-dropin/t/scratch-b.container.d/50-margot-parameters.conf"
)
NETWORK_B = 'quadlet-generator[817680]: converting "scratch-b.container": requested Quadlet unit scratch-a.network was not found'
NETWORK_A = 'quadlet-generator[811023]: converting "a.container": requested Quadlet unit nothere.network was not found'
VOLUME = 'quadlet-generator[811170]: converting "v.container": requested Quadlet source nothere.volume was not found'
POD = 'quadlet-generator[811177]: converting "p.container": quadlet pod unit nothere.pod does not exist'
IMAGE = 'quadlet-generator[811184]: converting "i.container": requested Quadlet image nothere.image was not found'
KUBE_NETWORK = 'quadlet-generator[811191]: converting "k.kube": requested Quadlet unit nothere.network was not found'
SUMMARY = "quadlet-generator[811023]: processing encountered some errors"
SYNTAX_C = (
    "quadlet-generator[811033]: converting \"c.container\": unsupported key 'NoSuchKey' in group 'Container' "
    "in /tmp/gen-ref/app/c.container"
)


def _stderr(*lines: str) -> str:
    return "\n".join(lines) + "\n"


class TestParseGeneratorStderr:
    """Splitting generator stderr into unresolved references and other error lines."""

    def test_progress_lines_are_neither_errors_nor_references(self) -> None:
        """Should ignore the 'Loading source unit file' lines Quadlet logs for every unit."""
        report = parse_generator_stderr(_stderr(PROGRESS_A, PROGRESS_B))

        assert report.unresolved == ()
        assert report.errors == ()

    def test_drop_in_progress_lines_are_not_errors(self) -> None:
        """Should ignore 'Loading source drop-in file' lines: a unit with a drop-in logs one (host output, S2 Checkpoint)."""
        report = parse_generator_stderr(_stderr(PROGRESS_DROPIN_B, NETWORK_B, SUMMARY))

        assert report.errors == ()
        assert [(ref.unit, ref.name) for ref in report.unresolved] == [("scratch-b.container", "scratch-a.network")]

    def test_unresolved_network_reports_the_unit_file_and_the_name(self) -> None:
        """Should read the real network line into (unit file, referenced unit)."""
        report = parse_generator_stderr(_stderr(PROGRESS_A, NETWORK_A, SUMMARY))

        assert len(report.unresolved) == 1
        assert report.unresolved[0].unit == "a.container"
        assert report.unresolved[0].name == "nothere.network"
        assert report.errors == ()

    @mark.parametrize(
        ("line", "unit", "name"),
        [
            (VOLUME, "v.container", "nothere.volume"),
            (POD, "p.container", "nothere.pod"),
            (IMAGE, "i.container", "nothere.image"),
            (KUBE_NETWORK, "k.kube", "nothere.network"),
        ],
        ids=["volume", "pod", "image", "kube-network"],
    )
    def test_every_host_reference_form_is_recognised(self, line: str, unit: str, name: str) -> None:
        """Should recognise the volume, pod, image and .kube wording the host prints, not only the network one."""
        report = parse_generator_stderr(_stderr(line, SUMMARY))

        assert [(ref.unit, ref.name) for ref in report.unresolved] == [(unit, name)]
        assert report.errors == ()

    def test_several_units_each_report_their_reference(self) -> None:
        """Should keep every unresolved reference, in output order."""
        report = parse_generator_stderr(_stderr(PROGRESS_A, NETWORK_A, VOLUME, POD, SUMMARY))

        assert [(ref.unit, ref.name) for ref in report.unresolved] == [
            ("a.container", "nothere.network"),
            ("v.container", "nothere.volume"),
            ("p.container", "nothere.pod"),
        ]

    def test_a_real_error_is_kept_and_the_reference_is_still_reported(self) -> None:
        """Should keep the syntax error as an error line and still report the unresolved reference."""
        report = parse_generator_stderr(_stderr(PROGRESS_A, PROGRESS_C, NETWORK_A, SYNTAX_C, SUMMARY))

        assert report.errors == (SYNTAX_C,)
        assert [ref.name for ref in report.unresolved] == ["nothere.network"]

    def test_summary_line_is_not_an_error(self) -> None:
        """Should not count the closing 'processing encountered some errors' line as an error."""
        report = parse_generator_stderr(_stderr(SUMMARY))

        assert report.errors == ()
        assert report.unresolved == ()

    def test_unknown_lines_are_kept_as_errors(self) -> None:
        """Should keep any line it does not recognise, so unexpected output still fails the install."""
        report = parse_generator_stderr("quadlet-generator[1]: something new went wrong\n")

        assert report.errors == ("quadlet-generator[1]: something new went wrong",)
        assert report.unresolved == ()

    def test_empty_text_gives_an_empty_report(self) -> None:
        """Should return an empty report for empty stderr."""
        report = parse_generator_stderr("")

        assert report.unresolved == ()
        assert report.errors == ()


class TestJudgeGenerator:
    """The verdict on a dry-run: the exit status decides, and only a non-reference error fails."""

    def test_exit_zero_passes_even_with_progress_lines(self) -> None:
        """Should pass a valid tree on exit 0."""
        verdict = judge_generator(0, parse_generator_stderr(_stderr(PROGRESS_A)))

        assert verdict.passed is True
        assert verdict.errors == ()
        assert verdict.unresolved == ()

    def test_only_unresolved_references_pass_and_are_returned(self) -> None:
        """Should accept a failed run whose only errors are unresolved references, and return them."""
        verdict = judge_generator(1, parse_generator_stderr(_stderr(PROGRESS_A, NETWORK_A, SUMMARY)))

        assert verdict.passed is True
        assert verdict.errors == ()
        assert [ref.name for ref in verdict.unresolved] == ["nothere.network"]

    def test_a_real_error_fails_and_only_that_error_is_listed(self) -> None:
        """Should fail, list only the real error line, and still return the references."""
        verdict = judge_generator(1, parse_generator_stderr(_stderr(NETWORK_A, SYNTAX_C, SUMMARY)))

        assert verdict.passed is False
        assert verdict.errors == (SYNTAX_C,)
        assert [ref.name for ref in verdict.unresolved] == ["nothere.network"]

    def test_non_zero_exit_without_any_line_fails_with_the_status(self) -> None:
        """Should fail a non-zero exit that printed nothing recognisable, naming the status."""
        verdict = judge_generator(1, parse_generator_stderr(""))

        assert verdict.passed is False
        assert verdict.errors == ("quadlet generator exited with status 1",)
        assert verdict.unresolved == ()


SYNTAX_A = 'quadlet-generator[811023]: converting "a.container": unsupported key \'NoSuchKey\' in group \'Container\''


class TestGroupGeneratorOutput:
    """Generator output sorted by the unit file each line names (sprint-13 §3.10, guard 3 diagnosis)."""

    def test_references_and_errors_are_grouped_by_their_unit(self) -> None:
        """Should keep each unit's references and error lines under its unit file name."""
        grouped = group_generator_output(_stderr(PROGRESS_A, NETWORK_A, VOLUME, SYNTAX_C, SUMMARY))

        assert set(grouped) == {"a.container", "v.container", "c.container"}
        assert [ref.name for ref in grouped["a.container"].references] == ["nothere.network"]
        assert grouped["a.container"].errors == ()
        assert grouped["c.container"].references == ()
        assert grouped["c.container"].errors == (SYNTAX_C,)

    def test_a_unit_with_a_reference_and_an_error_has_both(self) -> None:
        """Should record both kinds for one unit, so the verdict can refuse it."""
        grouped = group_generator_output(_stderr(NETWORK_A, SYNTAX_A, SUMMARY))

        assert [ref.name for ref in grouped["a.container"].references] == ["nothere.network"]
        assert grouped["a.container"].errors == (SYNTAX_A,)

    def test_lines_that_name_no_unit_are_not_grouped(self) -> None:
        """Should leave out lines that name no unit, because they cannot be tied to a missing service."""
        assert group_generator_output(_stderr("quadlet-generator[1]: something new went wrong", SUMMARY)) == {}

    def test_empty_text_gives_no_groups(self) -> None:
        """Should return an empty mapping for empty stderr."""
        assert group_generator_output("") == {}


class TestReferenceOnly:
    """A missing service may be explained by references alone; any other error line keeps it a failure."""

    def test_a_unit_with_only_references_returns_them(self) -> None:
        """Should return the references of a unit whose only problems are unresolved references."""
        diagnosis = group_generator_output(_stderr(NETWORK_A))["a.container"]

        assert [ref.name for ref in reference_only(diagnosis)] == ["nothere.network"]

    def test_a_reference_beside_an_error_returns_nothing(self) -> None:
        """Should return nothing when the same unit also has a real error."""
        diagnosis = group_generator_output(_stderr(NETWORK_A, SYNTAX_A))["a.container"]

        assert reference_only(diagnosis) == ()

    def test_a_unit_with_only_an_error_returns_nothing(self) -> None:
        """Should return nothing for a unit that has no reference."""
        diagnosis = group_generator_output(_stderr(SYNTAX_C))["c.container"]

        assert reference_only(diagnosis) == ()

    def test_no_diagnosis_returns_nothing(self) -> None:
        """Should return nothing when the unit does not appear in the generator output at all."""
        assert reference_only(None) == ()
