"""Unit tests for domain/install_parameters.py: parameter selection, value resolution, drop-in text and
the byte-exact Environment encoding verified by sprint-13 spike S2 (every vector of the table)."""

from pytest import mark, raises

from margot.domain.install_parameters import (
    DROPIN_NAME,
    SOURCE_DESCRIPTOR,
    SOURCE_SET,
    Binding,
    dropin_relpath,
    encode_environment,
    parse_set_options,
    render_dropin,
    render_value,
    resolve_parameters,
    variables_by_unit,
)

# S2 vectors: (input value, drop-in line written by margot, value seen by the container).
# The seen value equals the input in every case (S2, 19 of 19 byte-exact on the reference host).
S2_VECTORS = [
    ("00", "", 'Environment="S2V00="'),
    ("01", " lead", 'Environment="S2V01= lead"'),
    ("02", "trail ", 'Environment="S2V02=trail "'),
    ("03", "a  b", 'Environment="S2V03=a  b"'),
    ("04", 'say "hi"', 'Environment="S2V04=say \\"hi\\""'),
    ("05", "it's", 'Environment="S2V05=it\'s"'),
    ("06", "back\\slash", 'Environment="S2V06=back\\\\slash"'),
    ("07", "50%", 'Environment="S2V07=50%%"'),
    ("08", "100%%", 'Environment="S2V08=100%%%%"'),
    ("09", "$HOME", 'Environment="S2V09=$HOME"'),
    ("10", "${HOME}", 'Environment="S2V10=${HOME}"'),
    ("11", "$$", 'Environment="S2V11=$$"'),
    ("12", "#not comment", 'Environment="S2V12=#not comment"'),
    ("13", "a;b", 'Environment="S2V13=a;b"'),
    ("14", "k=v=w", 'Environment="S2V14=k=v=w"'),
    ("15", "tab\there", 'Environment="S2V15=tab\there"'),
    ("16", "é ü 中", 'Environment="S2V16=é ü 中"'),
    ("17", "end\\", 'Environment="S2V17=end\\\\"'),
    ("18", "abcdefgh" * 128, 'Environment="S2V18=' + "abcdefgh" * 128 + '"'),
]


def _doc(parameters: dict | None) -> dict:
    return {"id": "com-example-web", "parameters": parameters}


def _param(value: object = None, *targets: tuple[str, list[str]]) -> dict:
    spec: dict = {"targets": [{"pointer": pointer, "components": components} for pointer, components in targets]}
    if value is not None:
        spec["value"] = value
    return spec


class TestEncodeEnvironment:
    """The Environment= line that stores a value byte-for-byte (sprint-13 §3.9, spike S2)."""

    @mark.parametrize(("vector", "value", "expected"), S2_VECTORS, ids=[vector for vector, _, _ in S2_VECTORS])
    def test_s2_vector_is_encoded_as_recorded(self, vector: str, value: str, expected: str) -> None:
        """Should produce exactly the drop-in line recorded for S2 vector {vector}."""
        assert encode_environment(f"S2V{vector}", value) == expected

    def test_dollar_signs_are_not_escaped(self) -> None:
        """Should leave $ untouched: systemd stores it literally inside Environment= quotes."""
        assert encode_environment("X", "$A${B}$$") == 'Environment="X=$A${B}$$"'

    @mark.parametrize("bad", ["a\nb", "a\rb", "a\x00b"], ids=["newline", "cr", "nul"])
    def test_newline_cr_and_nul_are_refused(self, bad: str) -> None:
        """Should refuse a value with a newline, carriage return or NUL (exit 3 in the command)."""
        with raises(ValueError, match=r"newline, carriage return or NUL"):
            encode_environment("X", bad)

    @mark.parametrize("name", ["1X", "A-B", "A B", "", "A=B"])
    def test_invalid_variable_name_is_refused(self, name: str) -> None:
        """Should refuse a variable name that does not match [A-Za-z_][A-Za-z0-9_]*."""
        with raises(ValueError, match=r"environment variable name"):
            encode_environment(name, "v")


class TestParseSetOptions:
    """--set NAME=VALUE parsing: split on the first '=' only, repeated names counted."""

    def test_value_keeps_every_equals_sign(self) -> None:
        """Should split on the first '=' only."""
        overrides, repeated = parse_set_options(["A=k=v=w"])
        assert overrides == {"A": "k=v=w"}
        assert repeated == ()

    def test_empty_value_is_a_value(self) -> None:
        """Should accept NAME= as an empty string value."""
        overrides, _ = parse_set_options(["A="])
        assert overrides == {"A": ""}

    def test_last_value_wins_and_the_name_is_reported_as_repeated(self) -> None:
        """Should keep the last value of a repeated name and report the name once."""
        overrides, repeated = parse_set_options(["A=1", "B=2", "A=3", "A=4"])
        assert overrides == {"A": "4", "B": "2"}
        assert repeated == ("A",)

    @mark.parametrize("raw", ["NAME", "=value", ""], ids=["no-equals", "empty-name", "empty-argument"])
    def test_argument_without_a_name_and_equals_is_refused(self, raw: str) -> None:
        """Should refuse an argument that has no '=' or no name (usage error, exit 2 in the command)."""
        with raises(ValueError, match=r"NAME=VALUE"):
            parse_set_options([raw])


class TestRenderValue:
    """Descriptor values as strings: string as is, integer and double in decimal, boolean in YAML form."""

    def test_string_is_used_as_is(self) -> None:
        """Should return a string unchanged, including spaces and brackets."""
        assert render_value("array[string] [Container]") == "array[string] [Container]"

    def test_boolean_is_lowercase_yaml_form(self) -> None:
        """Should render True as true and False as false."""
        assert render_value(True) == "true"
        assert render_value(False) == "false"

    def test_integer_is_decimal(self) -> None:
        """Should render an integer without a decimal point."""
        assert render_value(8080) == "8080"

    def test_double_is_decimal_not_exponent(self) -> None:
        """Should render doubles in decimal notation."""
        assert render_value(0.1) == "0.1"
        assert render_value(1e20) == "100000000000000000000"
        assert render_value(1.0) == "1.0"

    def test_non_finite_double_is_refused(self) -> None:
        """Should refuse NaN and infinity, which have no decimal form."""
        with raises(ValueError, match=r"finite"):
            render_value(float("inf"))


class TestResolveParameters:
    """Which parameters apply to the selected profile, and with which value (sprint-13 §3.9)."""

    def test_descriptor_value_applies_to_the_target_component(self) -> None:
        """Should bind the descriptor default to the component named in the target."""
        doc = _doc({"port": _param(8080, ("NGINX_PORT", ["web"]))})

        resolution = resolve_parameters(doc, ["web"], {})

        assert resolution.bindings == (
            Binding(parameter="port", component="web", variable="NGINX_PORT", value="8080", source=SOURCE_DESCRIPTOR),
        )
        assert resolution.unapplied == ()

    def test_set_value_wins_over_the_descriptor(self) -> None:
        """Should use the --set value and report its source as --set."""
        doc = _doc({"port": _param(8080, ("NGINX_PORT", ["web"]))})

        resolution = resolve_parameters(doc, ["web"], {"port": "9090"})

        assert resolution.bindings[0].value == "9090"
        assert resolution.bindings[0].source == SOURCE_SET

    def test_targets_of_other_profiles_are_ignored(self) -> None:
        """Should not apply or report a parameter whose targets name no component of this profile."""
        doc = _doc({"port": _param(8080, ("NGINX_PORT", ["other"]))})

        resolution = resolve_parameters(doc, ["web"], {})

        assert resolution.bindings == ()
        assert resolution.unapplied == ()

    def test_parameter_without_any_value_is_unapplied(self) -> None:
        """Should list an applicable parameter that has neither a descriptor value nor --set."""
        doc = _doc({"b": _param(None, ("B_VAR", ["web"])), "a": _param(1, ("A_VAR", ["web"]))})

        resolution = resolve_parameters(doc, ["web"], {})

        assert resolution.unapplied == ("b",)
        assert [binding.variable for binding in resolution.bindings] == ["A_VAR"]

    def test_set_supplies_a_value_for_an_unvalued_parameter(self) -> None:
        """Should apply a parameter without a descriptor value once --set gives it one."""
        doc = _doc({"b": _param(None, ("B_VAR", ["web"]))})

        resolution = resolve_parameters(doc, ["web"], {"b": "x"})

        assert resolution.bindings[0].value == "x"
        assert resolution.unapplied == ()

    def test_set_for_a_parameter_outside_the_profile_is_refused(self) -> None:
        """Should refuse --set NAME for a parameter that applies to no component, listing the applicable ones."""
        doc = _doc({"port": _param(8080, ("NGINX_PORT", ["web"]))})

        with raises(ValueError, match=r"not a parameter of this profile.*port"):
            resolve_parameters(doc, ["web"], {"ghost": "1"})

    def test_several_components_each_get_the_variable(self) -> None:
        """Should bind one parameter to every component its targets name."""
        doc = _doc({"port": _param(8080, ("NGINX_PORT", ["web", "proxy"]))})

        resolution = resolve_parameters(doc, ["web", "proxy"], {})

        assert sorted(binding.component for binding in resolution.bindings) == ["proxy", "web"]

    @mark.parametrize(
        "pointer",
        ["1PORT", "NGINX-PORT", "NGINX PORT", "", None],
        ids=["digit", "dash", "space", "empty", "missing"],
    )
    def test_invalid_pointer_is_refused_naming_parameter_pointer_and_component(self, pointer: str | None) -> None:
        """Should refuse a pointer that is not an environment variable name, naming the parameter and component."""
        doc = _doc({"port": _param(8080, (pointer, ["web"]))})

        with raises(ValueError, match=r"'port'.*web"):
            resolve_parameters(doc, ["web"], {})

    def test_same_pointer_twice_on_one_component_is_a_conflict(self) -> None:
        """Should refuse two parameters that set the same variable on one component, naming both."""
        doc = _doc({"a": _param(1, ("PORT", ["web"])), "b": _param(2, ("PORT", ["web"]))})

        with raises(ValueError, match=r"'a' and 'b'.*PORT.*'web'"):
            resolve_parameters(doc, ["web"], {})

    def test_quadlet_dir_pointer_is_reserved_by_margot(self) -> None:
        """Should refuse a parameter whose pointer is QUADLET_DIR on a selected component, naming it as reserved."""
        doc = _doc({"dir": _param("/elsewhere", ("QUADLET_DIR", ["web"]))})

        with raises(ValueError, match=r"'dir'.*QUADLET_DIR.*'web'.*reserved by margot"):
            resolve_parameters(doc, ["web"], {})

    def test_quadlet_dir_pointer_on_a_component_outside_the_profile_is_ignored(self) -> None:
        """Should not refuse QUADLET_DIR when the target names a component the profile does not select."""
        doc = _doc({"dir": _param("/elsewhere", ("QUADLET_DIR", ["other"]))})

        assert resolve_parameters(doc, ["web"], {}).bindings == ()

    def test_set_cannot_reach_quadlet_dir(self) -> None:
        """Should refuse --set QUADLET_DIR, because it is not an applicable parameter name."""
        doc = _doc({"port": _param(8080, ("NGINX_PORT", ["web"]))})

        with raises(ValueError, match=r"--set QUADLET_DIR"):
            resolve_parameters(doc, ["web"], {"QUADLET_DIR": "/tmp"})

    def test_same_pointer_on_different_components_is_not_a_conflict(self) -> None:
        """Should allow two parameters to use one variable name on two different components."""
        doc = _doc({"a": _param(1, ("PORT", ["web"])), "b": _param(2, ("PORT", ["proxy"]))})

        resolution = resolve_parameters(doc, ["web", "proxy"], {})

        assert len(resolution.bindings) == 2

    def test_array_descriptor_value_is_refused_naming_the_parameter(self) -> None:
        """Should refuse an array descriptor value that would be applied."""
        doc = _doc({"hosts": _param(["a", "b"], ("HOSTS", ["web"]))})

        with raises(ValueError, match=r"'hosts'.*array"):
            resolve_parameters(doc, ["web"], {})

    def test_array_descriptor_value_is_allowed_when_set_replaces_it(self) -> None:
        """Should not refuse an array default that --set replaces with a string."""
        doc = _doc({"hosts": _param(["a", "b"], ("HOSTS", ["web"]))})

        resolution = resolve_parameters(doc, ["web"], {"hosts": "c"})

        assert resolution.bindings[0].value == "c"

    def test_newline_in_a_descriptor_value_is_refused_naming_the_parameter(self) -> None:
        """Should refuse a descriptor string with a newline, naming the parameter and component."""
        doc = _doc({"banner": _param("line1\nline2", ("BANNER", ["web"]))})

        with raises(ValueError, match=r"'banner'.*web.*newline"):
            resolve_parameters(doc, ["web"], {})

    def test_newline_in_a_set_value_is_refused(self) -> None:
        """Should refuse a --set value with a newline, naming the parameter."""
        doc = _doc({"banner": _param("x", ("BANNER", ["web"]))})

        with raises(ValueError, match=r"'banner'.*newline"):
            resolve_parameters(doc, ["web"], {"banner": "a\nb"})

    def test_no_parameters_section_yields_nothing(self) -> None:
        """Should return no bindings and no unapplied names when the descriptor has no parameters."""
        resolution = resolve_parameters(_doc(None), ["web"], {})

        assert resolution.bindings == ()
        assert resolution.unapplied == ()

    def test_bindings_are_sorted_by_component_then_variable(self) -> None:
        """Should return bindings in a deterministic order (component, then variable)."""
        doc = _doc({"z": _param(1, ("ZED", ["web"])), "a": _param(2, ("ALPHA", ["web"]))})

        resolution = resolve_parameters(doc, ["web"], {})

        assert [binding.variable for binding in resolution.bindings] == ["ALPHA", "ZED"]


class TestDropIn:
    """The drop-in text and the mapping of variables to unit files (sprint-13 §3.9)."""

    def test_dropin_text_has_the_documented_header_and_sorted_lines(self) -> None:
        """Should write the two header comments, [Service], then one Environment line per name, sorted."""
        text = render_dropin({"ZED": "2", "ALPHA": "a b"})

        assert text == (
            "# Managed by margot - regenerated on every install.\n"
            "# Add your own overrides in a differently named file (e.g. 90-local.conf).\n"
            "[Service]\n"
            'Environment="ALPHA=a b"\n'
            'Environment="ZED=2"\n'
        )

    def test_dropin_file_name_sits_beside_the_unit(self) -> None:
        """Should name the drop-in <unit file>.d/50-margot-parameters.conf in the unit's own directory."""
        assert DROPIN_NAME == "50-margot-parameters.conf"
        assert dropin_relpath("conf/nginx.container") == "conf/nginx.container.d/50-margot-parameters.conf"
        assert dropin_relpath("nginx.kube") == "nginx.kube.d/50-margot-parameters.conf"

    def test_every_unit_of_a_component_gets_all_its_variables(self) -> None:
        """Should map each unit of a component to all variables of that component, plus QUADLET_DIR."""
        bindings = [
            Binding("port", "web", "NGINX_PORT", "8080", SOURCE_DESCRIPTOR),
            Binding("greet", "web", "GREETING", "hi", SOURCE_DESCRIPTOR),
        ]

        mapping = variables_by_unit(bindings, {"web": ["web.container", "conf/net.network"]}, "/app")

        assert mapping == {
            "web.container": {"NGINX_PORT": "8080", "GREETING": "hi", "QUADLET_DIR": "/app"},
            "conf/net.network": {"NGINX_PORT": "8080", "GREETING": "hi", "QUADLET_DIR": "/app"},
        }

    def test_unit_without_parameters_still_gets_quadlet_dir(self) -> None:
        """Should give every unit QUADLET_DIR even when no parameter applies to its component."""
        mapping = variables_by_unit([], {"web": ["web.container"]}, "/cfg/com-x")

        assert mapping == {"web.container": {"QUADLET_DIR": "/cfg/com-x"}}

    def test_quadlet_dir_line_escapes_space_percent_and_quotes(self) -> None:
        """Should write QUADLET_DIR with % doubled and quotes escaped, the spike S2 rules applied to a path."""
        text = render_dropin({"QUADLET_DIR": '/cfg/my apps/100%/"quoted"'})

        assert text.splitlines()[-1] == 'Environment="QUADLET_DIR=/cfg/my apps/100%%/\\"quoted\\""'

    def test_unit_shipped_by_two_components_gets_the_union(self) -> None:
        """Should give a shared unit the variables of every component that ships it."""
        bindings = [
            Binding("a", "web", "A", "1", SOURCE_DESCRIPTOR),
            Binding("b", "copy", "B", "2", SOURCE_DESCRIPTOR),
        ]

        mapping = variables_by_unit(bindings, {"web": ["x.container"], "copy": ["x.container"]}, "/app")

        assert mapping == {"x.container": {"A": "1", "B": "2", "QUADLET_DIR": "/app"}}

    def test_unit_shared_with_different_values_for_one_variable_is_refused(self) -> None:
        """Should refuse a shared unit that two components would set to different values for one variable."""
        bindings = [
            Binding("a", "web", "PORT", "1", SOURCE_DESCRIPTOR),
            Binding("b", "copy", "PORT", "2", SOURCE_DESCRIPTOR),
        ]

        with raises(ValueError, match=r"x\.container.*PORT"):
            variables_by_unit(bindings, {"web": ["x.container"], "copy": ["x.container"]}, "/app")
