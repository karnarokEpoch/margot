"""E2E tests for describe command via CLI."""

from pathlib import Path
import re
from typing import Any

from pytest import fixture
from typer.testing import CliRunner

from margot.main import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

MARGO_YAML = """apiVersion: v1
id: hello-world
name: Hello World
description: A sample application
version: 1.0.0
repository: public.ecr.aws/g2n4p2m7/margo
compose:
  directory: margo
  version: 1.0.0
"""

VALID_APP_YAML = """apiVersion: application.margo.org/v1alpha1
kind: ApplicationDescription
id: hello-world
metadata:
  name: Hello World
  description: A test application
  version: 1.0.0
  catalog:
    application:
      tagline: Simple test application
    organization:
      - name: Test Org
deploymentProfiles:
  - type: compose
    id: default
    description: Default compose setup
    components:
      - name: hello-compose
        properties:
          repository: oci://example.com/hello
configuration:
  sections:
    - name: Settings
      settings:
        - parameter: testParam
          name: Test Parameter
          description: A test parameter
          immutable: false
          schema: testSchema
  schema:
    - name: testSchema
      dataType: string
      minLength: 1
      maxLength: 100
parameters:
  testParam:
    value: "default-value"
    targets:
      - pointer: settings.test
        components:
          - hello-compose
"""

TEMPLATED_APP_YAML = """apiVersion: application.margo.org/v1alpha1
kind: ApplicationDescription
id: {{ manifest.id }}
metadata:
  name: {{ manifest.name }}
  version: {{ manifest.version }}
deploymentProfiles:
  - type: compose
    id: default
    components:
      - name: hello-compose
configuration:
  sections: []
  schema: []
parameters: {}
"""

WRONG_KIND_APP_YAML = """apiVersion: application.margo.org/v1alpha1
kind: SomethingElse
id: hello-world
metadata:
  name: Hello World
  version: 1.0.0
"""


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text for plain-string assertions."""
    return _ANSI_RE.sub("", text)


def _output(result: Any) -> str:
    """Combine stdout and stderr into plain, ANSI-free text."""
    return _strip_ansi(result.stdout + (result.stderr or ""))


@fixture
def cli_project(tmp_path: Path, monkeypatch: Any) -> Path:
    """Create a project with margo.yaml and an empty margo source directory."""
    (tmp_path / "margo.yaml").write_text(MARGO_YAML, encoding="utf-8")
    (tmp_path / "margo").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestDescribeHelp:
    """E2E tests for describe command help output."""

    def test_describe_help(self) -> None:
        """Should list every flag the command accepts."""
        result = runner.invoke(app, ["describe", "--help"])
        plain = _strip_ansi(result.stdout)

        assert result.exit_code == 0
        assert "--project-dir" in plain
        assert "--manifest" in plain
        assert "--section" in plain

    def test_describe_is_registered_on_root_help(self) -> None:
        """Should appear in the root command list."""
        result = runner.invoke(app, ["-h"])

        assert result.exit_code == 0
        assert "describe" in _strip_ansi(result.stdout)


class TestDescribeCLI:
    """E2E tests for margot describe."""

    def test_describe_valid_descriptor_exits_0(self, cli_project: Path) -> None:
        """Should describe the descriptor and exit 0."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # Should show the identity panel with apiVersion as title
        assert "application.margo.org/v1alpha1" in plain or "hello-world" in plain

    def test_describe_missing_margo_yaml_exits_1(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Should exit 1 when margo.yaml is absent."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "margo.yaml" in plain or "Error" in plain

    def test_describe_missing_manifest_exits_1(self, cli_project: Path) -> None:
        """Should exit 1 when --manifest points at a missing file."""
        result = runner.invoke(app, ["describe", "--manifest", str(cli_project / "margo" / "absent.yaml")])
        plain = _output(result)

        assert result.exit_code == 1
        assert "Error" in plain or "not found" in plain.lower()

    def test_describe_wrong_kind_exits_1(self, cli_project: Path) -> None:
        """Should exit 1 when kind is not ApplicationDescription."""
        (cli_project / "margo" / "app.yaml").write_text(WRONG_KIND_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 1
        assert "Error" in plain or "kind" in plain.lower()
        # Should mention running verify
        assert "verify" in plain.lower()

    def test_describe_section_filtering(self, cli_project: Path) -> None:
        """Should render only requested sections."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        # Request only metadata section
        result = runner.invoke(app, ["describe", "--section", "metadata"])
        plain = _output(result)

        assert result.exit_code == 0
        # Should have metadata
        assert "hello-world" in plain or "Hello World" in plain
        # Should not have configuration panel heading
        assert "Configuration" not in plain

    def test_describe_section_order_is_canonical(self, cli_project: Path) -> None:
        """Should always render sections in canonical order regardless of flag order."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        # Request config then metadata
        result1 = runner.invoke(app, ["describe", "--section", "config", "--section", "metadata"])
        # Request metadata then config
        result2 = runner.invoke(app, ["describe", "--section", "metadata", "--section", "config"])
        plain1 = _output(result1)
        plain2 = _output(result2)

        # Both should produce the same output (modulo whitespace)
        assert _strip_ansi(plain1.replace("\n", "")) == _strip_ansi(plain2.replace("\n", ""))

    def test_describe_templated_descriptor_works(self, cli_project: Path) -> None:
        """Should render app.yaml.jinja without requiring a prior build."""
        (cli_project / "margo" / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        assert "hello-world" in plain or "Hello World" in plain
        # Should show path to the template file (not the temp file path)
        assert "app.yaml.jinja" in plain

    def test_describe_with_explicit_manifest_path(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Should describe a descriptor from explicit --manifest path."""
        monkeypatch.chdir(tmp_path)
        descriptor = tmp_path / "elsewhere" / "app.yaml"
        descriptor.parent.mkdir(parents=True)
        descriptor.write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe", "--project-dir", str(tmp_path), "--manifest", str(descriptor)])
        plain = _output(result)

        assert result.exit_code == 0
        assert "hello-world" in plain or "Hello World" in plain

    def test_describe_shows_configuration_settings(self, cli_project: Path) -> None:
        """Should render configuration sections and settings."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # Should have configuration section
        assert "Settings" in plain or "Configuration" in plain
        # Should have setting name
        assert "Test Parameter" in plain or "testParam" in plain

    def test_describe_shows_deployment_profiles(self, cli_project: Path) -> None:
        """Should render deployment profiles."""
        (cli_project / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # Should show profiles panel with profile type and id
        assert "compose" in plain or "default" in plain


SENSOR_DASHBOARD_APP_YAML = """apiVersion: margo.org/v1alpha1
kind: ApplicationDescription
id: sensor-dashboard
metadata:
  name: "Sensor Dashboard"
  version: "<margo_version>"
  description: "Real-time sensor monitoring dashboard for Industrial IoT
    applications with MQTT integration and OpenTelemetry instrumentation"
  catalog:
    application:
      descriptionFile: "resources/description.md"
      icon: "resources/icon.png"
      licenseFile: "resources/license.txt"
      releaseNotes: "resources/release-notes.md"
      tagline: "Simple, Real-Time Industrial Sensor Monitoring"
      tags:
        - "iot"
        - "industrial"
        - "mqtt"
        - "monitoring"
        - "sensors"
        - "edge-computing"
      site: "https://github.com/bhng/sensor-dashboard"
    organization:
      - name: "Belden Inc."
        site: "https://www.belden.com"

deploymentProfiles:
  - id: "helm-v2"
    type: "helm"
    description:
      "Kubernetes deployment using Helm v2 chart. Designed for k3s and
      standard Kubernetes clusters. Supports multi-architecture (amd64/arm64)
      for edge devices including Raspberry Pi."
    requiredResources:
      cpu:
        cores: 0.1
        architectures:
          - amd64
          - arm64
      memory: "256Mi"
      storage: "1Gi"
      interfaces:
        - type: ethernet
    components:
      - name: "sensor-dashboard-helm"
        properties:
          repository: "oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard"
          revision: "<helm_chart_tag>"
          wait: true
          timeout: "5m0s"

  - id: "compose-v1"
    type: "compose"
    description: "Compose deployment for single-machine environments without
      Kubernetes. Suitable for edge devices, development workstations, and demo
      environments. Includes built-in virtual sensors for standalone operation."
    requiredResources:
      cpu:
        cores: 0.1
        architectures:
          - amd64
          - arm64
      memory: "256Mi"
      storage: "1Gi"
      interfaces:
        - type: ethernet
    components:
      - name: "sensor-dashboard-compose"
        properties:
          repository: "oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard"
          revision: "<compose_tag>"
          wait: true
          timeout: "5m0s"

  - id: "compose-v1-simple"
    type: "compose"
    description: "Minimal compose deployment with dashboard only, no broker or
      sensor-daemon. Requires an external MQTT broker."
    requiredResources:
      cpu:
        cores: 0.1
        architectures:
          - amd64
          - arm64
      memory: "256Mi"
      storage: "1Gi"
      interfaces:
        - type: ethernet
    components:
      - name: "sensor-dashboard-compose-simple"
        properties:
          repository: "oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard"
          revision: "<compose_tag>-simple"
          wait: true
          timeout: "5m0s"

  - id: "compose-v1-modular"
    type: "compose"
    description: "Modular compose deployment. Core dashboard plus optional
      add-on components (sensor-daemon, mosquitto) selected at deploy time."
    requiredResources:
      cpu:
        cores: 0.1
        architectures:
          - amd64
          - arm64
      memory: "256Mi"
      storage: "1Gi"
      interfaces:
        - type: ethernet
    components:
      - name: "sensor-dashboard-compose-simple"
        properties:
          repository: "oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard"
          revision: "<compose_tag>-simple"
          wait: true
          timeout: "5m0s"
      - name: "sensor-dashboard-compose-addon-sensor-daemon"
        properties:
          repository: "oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard"
          revision: "<compose_tag>-addon-sensor-daemon"
          wait: true
          timeout: "5m0s"
      - name: "sensor-dashboard-compose-addon-mosquitto"
        properties:
          repository: "oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard"
          revision: "<compose_tag>-addon-mosquitto"
          wait: true
          timeout: "5m0s"

  - id: "quadlet-v1"
    type: "quadlet"
    description: "Systemd-native deployment using Podman Quadlet unit files.
      Designed for edge devices and single-machine environments with systemd.
      Supports amd64 and arm64 including Raspberry Pi."
    requiredResources:
      cpu:
        cores: 0.1
        architectures:
          - amd64
          - arm64
      memory: "256Mi"
      storage: "1Gi"
      interfaces:
        - type: ethernet
    components:
      - name: "sensor-dashboard-quadlet"
        properties:
          repository: "oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard"
          revision: "<quadlet_tag>"
          wait: true
          timeout: "5m0s"

  - id: "quadlet-v1-simple"
    type: "quadlet"
    description: "Minimal quadlet deployment with dashboard only, no broker or
      sensor-daemon. Requires an external MQTT broker."
    requiredResources:
      cpu:
        cores: 0.1
        architectures:
          - amd64
          - arm64
      memory: "256Mi"
      storage: "1Gi"
      interfaces:
        - type: ethernet
    components:
      - name: "sensor-dashboard-quadlet-simple"
        properties:
          repository: "oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard"
          revision: "<quadlet_tag>-simple"
          wait: true
          timeout: "5m0s"

  - id: "quadlet-v1-modular"
    type: "quadlet"
    description: "Modular quadlet deployment. Core dashboard plus optional
      add-on components (sensor-daemon, mosquitto) selected at deploy time."
    requiredResources:
      cpu:
        cores: 0.1
        architectures:
          - amd64
          - arm64
      memory: "256Mi"
      storage: "1Gi"
      interfaces:
        - type: ethernet
    components:
      - name: "sensor-dashboard-quadlet-simple"
        properties:
          repository: "oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard"
          revision: "<quadlet_tag>-simple"
          wait: true
          timeout: "5m0s"
      - name: "sensor-dashboard-quadlet-addon-sensor-daemon"
        properties:
          repository: "oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard"
          revision: "<quadlet_tag>-addon-sensor-daemon"
          wait: true
          timeout: "5m0s"
      - name: "sensor-dashboard-quadlet-addon-mosquitto"
        properties:
          repository: "oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard"
          revision: "<quadlet_tag>-addon-mosquitto"
          wait: true
          timeout: "5m0s"

parameters:
  mqttBroker:
    value: "host.containers.internal"
    targets:
      - pointer: "mqtt.broker"
        components:
          - sensor-dashboard-helm
      - pointer: "MQTT_BROKER"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple
      - pointer: "SENSOR_DAEMON_MQTT_BROKER"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-addon-sensor-daemon
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-addon-sensor-daemon

  mqttPort:
    value: 1883
    targets:
      - pointer: "mqtt.port"
        components:
          - sensor-dashboard-helm
      - pointer: "MQTT_PORT"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-addon-mosquitto
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-addon-mosquitto
          - sensor-dashboard-quadlet-simple
      - pointer: "SENSOR_DAEMON_MQTT_PORT"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-addon-sensor-daemon
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-addon-sensor-daemon

  mqttTopic:
    value: "sensors/vl53l0x/#"
    targets:
      - pointer: "mqtt.topic"
        components:
          - sensor-dashboard-helm
      - pointer: "MQTT_TOPIC"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  dashboardPort:
    value: 3000
    targets:
      - pointer: "service.port"
        components:
          - sensor-dashboard-helm
      - pointer: "DASHBOARD_PORT"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  logLevel:
    value: "info"
    targets:
      - pointer: "LOG_LEVEL"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  historySize:
    value: 1000
    targets:
      - pointer: "HISTORY_SIZE"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  virtualSensorsEnabled:
    value: true
    targets:
      - pointer: "virtualSensors.enabled"
        components:
          - sensor-dashboard-helm
      - pointer: "VIRTUAL_SENSORS_ENABLED"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  virtualSensorsCount:
    value: 4
    targets:
      - pointer: "virtualSensors.count"
        components:
          - sensor-dashboard-helm
      - pointer: "VIRTUAL_SENSORS_COUNT"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  virtualSensorsRateHz:
    value: 10
    targets:
      - pointer: "virtualSensors.rateHz"
        components:
          - sensor-dashboard-helm
      - pointer: "VIRTUAL_SENSORS_RATE_HZ"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  sensorDaemonMode:
    value: "synthetic"
    targets:
      - pointer: "SENSOR_DAEMON_MODE"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-addon-sensor-daemon
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-addon-sensor-daemon

  sensorDaemonSensorName:
    value: "sensor-0"
    targets:
      - pointer: "SENSOR_DAEMON_SYNTHETIC_SENSOR_NAME"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-addon-sensor-daemon
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-addon-sensor-daemon

  sensorDaemonLogLevel:
    value: "INFO"
    targets:
      - pointer: "SENSOR_DAEMON_LOG_LEVEL"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-addon-sensor-daemon
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-addon-sensor-daemon

  otelEnabled:
    value: false
    targets:
      - pointer: "OTEL_ENABLED"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  otelEndpoint:
    value: "http://grafana:4318"
    targets:
      - pointer: "OTEL_EXPORTER_OTLP_ENDPOINT"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  otelServiceName:
    value: "sensor-dashboard"
    targets:
      - pointer: "OTEL_SERVICE_NAME"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  otelServiceVersion:
    value: "1.0.0"
    targets:
      - pointer: "OTEL_SERVICE_VERSION"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  otelDeploymentEnvironment:
    value: "edge"
    targets:
      - pointer: "OTEL_DEPLOYMENT_ENVIRONMENT"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  otelDeviceId:
    value: ""
    targets:
      - pointer: "OTEL_DEVICE_ID"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  otelLogLevel:
    value: "WARN"
    targets:
      - pointer: "OTEL_LOG_LEVEL"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  otelExporterHeaders:
    value: ""
    targets:
      - pointer: "OTEL_EXPORTER_OTLP_HEADERS"
        components:
          - sensor-dashboard-compose
          - sensor-dashboard-compose-simple
          - sensor-dashboard-quadlet
          - sensor-dashboard-quadlet-simple

  serviceNodePort:
    value: 30305
    targets:
      - pointer: "service.nodePort"
        components:
          - sensor-dashboard-helm

  replicaCount:
    value: 1
    targets:
      - pointer: "replicaCount"
        components:
          - sensor-dashboard-helm

configuration:
  sections:
    - name: "MQTT"
      settings:
        - parameter: mqttBroker
          name: "Broker"
          immutable: false
          schema: mqttBrokerSchema

        - parameter: mqttPort
          name: "Port"
          immutable: true
          schema: mqttPortSchema

        - parameter: mqttTopic
          name: "Topic Pattern"
          immutable: false
          schema: mqttTopicSchema

    - name: "Dashboard"
      settings:
        - parameter: dashboardPort
          name: "HTTP Port"
          immutable: false
          schema: dashboardPortSchema

        - parameter: logLevel
          name: "Log Level"
          immutable: false
          schema: logLevelSchema

        - parameter: historySize
          name: "History Buffer Size"
          immutable: false
          schema: historySizeSchema

    - name: "Virtual Sensors"
      settings:
        - parameter: virtualSensorsEnabled
          name: "Enable Virtual Sensors"
          immutable: false
          schema: virtualSensorsEnabledSchema

        - parameter: virtualSensorsCount
          name: "Sensor Count"
          immutable: false
          schema: virtualSensorsCountSchema

        - parameter: virtualSensorsRateHz
          name: "Update Rate (Hz)"
          immutable: false
          schema: virtualSensorsRateHzSchema

    - name: "Sensor Daemon"
      settings:
        - parameter: sensorDaemonMode
          name: "Mode"
          immutable: false
          schema: sensorDaemonModeSchema

        - parameter: sensorDaemonSensorName
          name: "Sensor Name"
          immutable: false
          schema: sensorDaemonSensorNameSchema

        - parameter: sensorDaemonLogLevel
          name: "Sensor Daemon Log Level"
          immutable: false
          schema: sensorDaemonLogLevelSchema

    - name: "OpenTelemetry"
      settings:
        - parameter: otelEnabled
          name: "Enable"
          immutable: false
          schema: otelEnabledSchema

        - parameter: otelEndpoint
          name: "OTLP Endpoint"
          immutable: false
          schema: otelEndpointSchema

        - parameter: otelServiceName
          name: "Service Name"
          immutable: false
          schema: otelServiceNameSchema

        - parameter: otelServiceVersion
          name: "Service Version"
          immutable: false
          schema: otelServiceVersionSchema

        - parameter: otelDeploymentEnvironment
          name: "Deployment Environment"
          immutable: false
          schema: otelDeploymentEnvironmentSchema

        - parameter: otelDeviceId
          name: "Device ID"
          immutable: false
          schema: otelDeviceIdSchema

        - parameter: otelLogLevel
          name: "SDK Log Level"
          immutable: false
          schema: otelLogLevelSchema

        - parameter: otelExporterHeaders
          name: "Exporter Headers"
          immutable: false
          schema: otelExporterHeadersSchema

    - name: "Kubernetes"
      settings:
        - parameter: serviceNodePort
          name: "Service NodePort"
          immutable: false
          schema: nodePortSchema

        - parameter: replicaCount
          name: "Replica Count"
          immutable: false
          schema: replicaCountSchema

  schema:
    - name: mqttBrokerSchema
      dataType: string
      allowEmpty: false

    - name: mqttPortSchema
      dataType: integer
      minValue: 1
      maxValue: 65535
      allowEmpty: false

    - name: mqttTopicSchema
      dataType: string
      allowEmpty: false

    - name: dashboardPortSchema
      dataType: integer
      minValue: 1
      maxValue: 65535
      allowEmpty: false

    - name: logLevelSchema
      dataType: string
      allowEmpty: false
      options:
        - error
        - warn
        - info
        - debug

    - name: historySizeSchema
      dataType: integer
      minValue: 10
      allowEmpty: false

    - name: virtualSensorsEnabledSchema
      dataType: boolean
      allowEmpty: false

    - name: virtualSensorsCountSchema
      dataType: integer
      minValue: 1
      maxValue: 20
      allowEmpty: false

    - name: virtualSensorsRateHzSchema
      dataType: integer
      minValue: 1
      maxValue: 50
      allowEmpty: false

    - name: sensorDaemonModeSchema
      dataType: string
      allowEmpty: false
      options:
        - synthetic
        - gpio

    - name: sensorDaemonSensorNameSchema
      dataType: string
      allowEmpty: false
      maxLength: 64

    - name: sensorDaemonLogLevelSchema
      dataType: string
      allowEmpty: false
      options:
        - DEBUG
        - INFO
        - WARNING
        - ERROR

    - name: otelEnabledSchema
      dataType: boolean
      allowEmpty: false

    - name: otelEndpointSchema
      dataType: string
      allowEmpty: true

    - name: otelServiceNameSchema
      dataType: string
      allowEmpty: true

    - name: otelServiceVersionSchema
      dataType: string
      allowEmpty: true

    - name: otelDeploymentEnvironmentSchema
      dataType: string
      allowEmpty: true

    - name: otelDeviceIdSchema
      dataType: string
      allowEmpty: true

    - name: otelLogLevelSchema
      dataType: string
      allowEmpty: false
      options:
        - ERROR
        - WARN
        - INFO
        - DEBUG

    - name: otelExporterHeadersSchema
      dataType: string
      allowEmpty: true

    - name: nodePortSchema
      dataType: integer
      minValue: 30000
      maxValue: 32767
      allowEmpty: false

    - name: replicaCountSchema
      dataType: integer
      minValue: 1
      allowEmpty: false
"""

SENSOR_DASHBOARD_MARGO_YAML = """apiVersion: v1
id: sensor-dashboard
name: Sensor Dashboard
description: Real-time sensor monitoring dashboard
version: 1.0.0
repository: public.ecr.aws/g2n4p2m7/margo
compose:
  directory: margo
  version: 1.0.0
"""


@fixture
def sensor_dashboard_project(tmp_path: Path, monkeypatch: Any) -> Path:
    """Create a project with sensor-dashboard descriptor."""
    (tmp_path / "margo.yaml").write_text(SENSOR_DASHBOARD_MARGO_YAML, encoding="utf-8")
    (tmp_path / "margo").mkdir()
    (tmp_path / "margo" / "app.yaml").write_text(SENSOR_DASHBOARD_APP_YAML, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestDescribeSensorDashboardFixture:
    """E2E tests for margot describe against the real sensor-dashboard descriptor."""

    def test_sensor_dashboard_describe_renders_all_sections(self, sensor_dashboard_project: Path) -> None:
        """Should describe the real sensor-dashboard descriptor and exit 0."""
        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # Verify identity/apiVersion is present
        assert "margo.org" in plain

    def test_sensor_dashboard_deployment_profiles_count(self, sensor_dashboard_project: Path) -> None:
        """Should show exactly 7 profiles and 9 distinct components."""
        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # Check for the profile and component counts in the title
        assert "7 profiles" in plain
        assert "9 components" in plain

    def test_sensor_dashboard_configuration_sections_and_settings(self, sensor_dashboard_project: Path) -> None:
        """Should show 6 configuration sections and 22 settings."""
        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # Check for section and setting counts
        assert "6 sections" in plain
        assert "22 settings" in plain

    def test_sensor_dashboard_author_absent_marker(self, sensor_dashboard_project: Path) -> None:
        """Should render author as em-dash when absent (catalog has only organization)."""
        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # Author should be rendered with em-dash marker (—)
        assert "author" in plain
        # The em-dash (—) should appear in context of author
        # Check that both author label and em-dash are present
        assert "\u2014" in plain or "–" in plain  # em-dash or en-dash

    def test_sensor_dashboard_quadlet_type_verbatim(self, sensor_dashboard_project: Path) -> None:
        """Should render 'quadlet' type verbatim, not validate or reject it."""
        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # Check that 'quadlet' appears (showing no validation rejection)
        assert "quadlet" in plain
        # Ensure it appears at least 3 times (for quadlet-v1, quadlet-v1-simple, quadlet-v1-modular)
        quadlet_count = plain.count("quadlet")
        assert quadlet_count >= 3

    def test_sensor_dashboard_mqtt_port_bare_integer(self, sensor_dashboard_project: Path) -> None:
        """Should render mqttPort default as bare 1883, not quoted '1883'."""
        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # Check for bare integer on the Parameter line (inline, not "Default:")
        # Format is "Parameter: mqttPort  1883"
        assert "Parameter: mqttPort" in plain
        assert "1883" in plain
        # Ensure quoted version is NOT present
        assert 'mqttPort  "1883"' not in plain

    def test_sensor_dashboard_otel_device_id_empty_string(self, sensor_dashboard_project: Path) -> None:
        """Should render otelDeviceId as explicit empty string marker '""'."""
        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # Check for explicit empty string marker on Parameter line
        # Format is "Parameter: otelDeviceId  """
        assert "Parameter: otelDeviceId" in plain
        assert '""' in plain

    def test_sensor_dashboard_mqtt_port_pointer_ratio(self, sensor_dashboard_project: Path) -> None:
        """Should show MQTT_PORT pointer targeting 6 out of 9 components."""
        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # Check for the ratio (6/9) in context of MQTT_PORT pointer
        assert "(6/9" in plain

    def test_sensor_dashboard_no_unreferenced_parameters(self, sensor_dashboard_project: Path) -> None:
        """Should have no unreferenced-parameters subtree (all 22 params referenced by settings)."""
        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        # The unreferenced parameters heading should NOT appear
        # Check for the exact heading text
        assert "Unreferenced parameters" not in plain
