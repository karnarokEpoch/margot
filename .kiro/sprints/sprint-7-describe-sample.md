# Sprint 7 — `describe` output, full sample

Reference output for the design locked in [`sprint-7.md`](sprint-7.md), rendered from a
real descriptor: `sensor-app/margo/margo.yaml` (7 deployment profiles, 11 component
entries over 9 distinct names, 22 parameters, 22 settings in 6 sections, 22 schemas, no
`author`, `type: quadlet`).

Produced at 100 columns with colour disabled. Nothing here is hand-written — it is the
locked layout applied to real data, so it doubles as the acceptance target for
`tests/e2e/test_describe_cli.py`.

What this sample demonstrates, block by block:

- `apiVersion` as the identity panel title, `kind` absent, resolved path as the subtitle.
- `author` missing renders `—`, while `Default: ""` (`otelDeviceId`, `otelExporterHeaders`)
  renders as an explicit empty string — two different facts, two different glyphs.
- `[Section]` and `[Setting]` survive as literal text. Passed as markup they would have
  vanished; every value goes through a `Text` object.
- Per-profile `requiredResources`, and `type: quadlet` printed verbatim.
- `Default: 1883` bare vs `Default: "sensors/vl53l0x/#"` quoted.
- `immutable` as a tag on the `Port [Setting]` line, not a child node.
- Per-pointer ratios against the 9 distinct components — `(6/9)` for `MQTT_PORT`,
  `(1/9)` for the helm-only pointers.
- No unreferenced-parameters subtree: this descriptor's 22 parameters and 22 settings are
  exactly 1:1. It would appear here if any parameter went unreferenced.

```text
╭─────────────────────────────────────── margo.org/v1alpha1 ───────────────────────────────────────╮
│ id    sensor-dashboard  version  <margo_version>                                                 │
│ name  Sensor Dashboard                                                                           │
│                                                                                                  │
│ Description: Real-time sensor monitoring dashboard for Industrial IoT applications with MQTT     │
│              integration and OpenTelemetry instrumentation                                       │
│ Catalog:                                                                                         │
│     tagline          Simple, Real-Time Industrial Sensor Monitoring                              │
│     site             https://github.com/bhng/sensor-dashboard                                    │
│     icon             resources/icon.png                                                          │
│     descriptionFile  resources/description.md                                                    │
│     licenseFile      resources/license.txt                                                       │
│     releaseNotes     resources/release-notes.md                                                  │
│     tags             iot, industrial, mqtt, monitoring, sensors, edge-computing                  │
│     author           —                                                                           │
│     organization     Belden Inc. — https://www.belden.com                                        │
╰─────────────────────── /home/louis/work/margo/sensor-app/margo/margo.yaml ───────────────────────╯

╭──────────────────────── Deployment profiles (7 profiles · 9 components) ─────────────────────────╮
│ helm  helm-v2                                                                                    │
│ ├── Kubernetes deployment using Helm v2 chart. Designed for k3s and standard Kubernetes          │
│ │   clusters. Supports multi-architecture (amd64/arm64) for edge devices including Raspberry Pi. │
│ ├── resources    cpu 0.1 cores (amd64, arm64) · memory 256Mi · storage 1Gi                       │
│ ├── interfaces   ethernet                                                                        │
│ └── components                                                                                   │
│     └── sensor-dashboard-helm                                                                    │
│         ├── repository  oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard                       │
│         ├── revision    <helm_chart_tag>                                                         │
│         ├── wait        true                                                                     │
│         └── timeout     5m0s                                                                     │
│                                                                                                  │
│ compose  compose-v1                                                                              │
│ ├── Compose deployment for single-machine environments without Kubernetes. Suitable for edge     │
│ │   devices, development workstations, and demo environments. Includes built-in virtual sensors  │
│ │   for standalone operation.                                                                    │
│ ├── resources    cpu 0.1 cores (amd64, arm64) · memory 256Mi · storage 1Gi                       │
│ ├── interfaces   ethernet                                                                        │
│ └── components                                                                                   │
│     └── sensor-dashboard-compose                                                                 │
│         ├── repository  oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard                       │
│         ├── revision    <compose_tag>                                                            │
│         ├── wait        true                                                                     │
│         └── timeout     5m0s                                                                     │
│                                                                                                  │
│ compose  compose-v1-simple                                                                       │
│ ├── Minimal compose deployment with dashboard only, no broker or sensor-daemon. Requires an      │
│ │   external MQTT broker.                                                                        │
│ ├── resources    cpu 0.1 cores (amd64, arm64) · memory 256Mi · storage 1Gi                       │
│ ├── interfaces   ethernet                                                                        │
│ └── components                                                                                   │
│     └── sensor-dashboard-compose-simple                                                          │
│         ├── repository  oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard                       │
│         ├── revision    <compose_tag>-simple                                                     │
│         ├── wait        true                                                                     │
│         └── timeout     5m0s                                                                     │
│                                                                                                  │
│ compose  compose-v1-modular                                                                      │
│ ├── Modular compose deployment. Core dashboard plus optional add-on components (sensor-daemon,   │
│ │   mosquitto) selected at deploy time.                                                          │
│ ├── resources    cpu 0.1 cores (amd64, arm64) · memory 256Mi · storage 1Gi                       │
│ ├── interfaces   ethernet                                                                        │
│ └── components                                                                                   │
│     ├── sensor-dashboard-compose-simple                                                          │
│     │   ├── repository  oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard                       │
│     │   ├── revision    <compose_tag>-simple                                                     │
│     │   ├── wait        true                                                                     │
│     │   └── timeout     5m0s                                                                     │
│     ├── sensor-dashboard-compose-addon-sensor-daemon                                             │
│     │   ├── repository  oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard                       │
│     │   ├── revision    <compose_tag>-addon-sensor-daemon                                        │
│     │   ├── wait        true                                                                     │
│     │   └── timeout     5m0s                                                                     │
│     └── sensor-dashboard-compose-addon-mosquitto                                                 │
│         ├── repository  oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard                       │
│         ├── revision    <compose_tag>-addon-mosquitto                                            │
│         ├── wait        true                                                                     │
│         └── timeout     5m0s                                                                     │
│                                                                                                  │
│ quadlet  quadlet-v1                                                                              │
│ ├── Systemd-native deployment using Podman Quadlet unit files. Designed for edge devices and     │
│ │   single-machine environments with systemd. Supports amd64 and arm64 including Raspberry Pi.   │
│ ├── resources    cpu 0.1 cores (amd64, arm64) · memory 256Mi · storage 1Gi                       │
│ ├── interfaces   ethernet                                                                        │
│ └── components                                                                                   │
│     └── sensor-dashboard-quadlet                                                                 │
│         ├── repository  oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard                       │
│         ├── revision    <quadlet_tag>                                                            │
│         ├── wait        true                                                                     │
│         └── timeout     5m0s                                                                     │
│                                                                                                  │
│ quadlet  quadlet-v1-simple                                                                       │
│ ├── Minimal quadlet deployment with dashboard only, no broker or sensor-daemon. Requires an      │
│ │   external MQTT broker.                                                                        │
│ ├── resources    cpu 0.1 cores (amd64, arm64) · memory 256Mi · storage 1Gi                       │
│ ├── interfaces   ethernet                                                                        │
│ └── components                                                                                   │
│     └── sensor-dashboard-quadlet-simple                                                          │
│         ├── repository  oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard                       │
│         ├── revision    <quadlet_tag>-simple                                                     │
│         ├── wait        true                                                                     │
│         └── timeout     5m0s                                                                     │
│                                                                                                  │
│ quadlet  quadlet-v1-modular                                                                      │
│ ├── Modular quadlet deployment. Core dashboard plus optional add-on components (sensor-daemon,   │
│ │   mosquitto) selected at deploy time.                                                          │
│ ├── resources    cpu 0.1 cores (amd64, arm64) · memory 256Mi · storage 1Gi                       │
│ ├── interfaces   ethernet                                                                        │
│ └── components                                                                                   │
│     ├── sensor-dashboard-quadlet-simple                                                          │
│     │   ├── repository  oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard                       │
│     │   ├── revision    <quadlet_tag>-simple                                                     │
│     │   ├── wait        true                                                                     │
│     │   └── timeout     5m0s                                                                     │
│     ├── sensor-dashboard-quadlet-addon-sensor-daemon                                             │
│     │   ├── repository  oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard                       │
│     │   ├── revision    <quadlet_tag>-addon-sensor-daemon                                        │
│     │   ├── wait        true                                                                     │
│     │   └── timeout     5m0s                                                                     │
│     └── sensor-dashboard-quadlet-addon-mosquitto                                                 │
│         ├── repository  oci://public.ecr.aws/g2n4p2m7/dev/sensor-dashboard                       │
│         ├── revision    <quadlet_tag>-addon-mosquitto                                            │
│         ├── wait        true                                                                     │
│         └── timeout     5m0s                                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯

╭──────────────────────────── Configuration (6 sections · 22 settings) ────────────────────────────╮
│ MQTT  [Section]                                                                                  │
│ ├── Broker  [Setting]                                                                            │
│ │   ├── Schema: mqttBrokerSchema  string · allowEmpty false                                      │
│ │   └── Parameter: mqttBroker                                                                    │
│ │       ├── Default: "host.containers.internal"                                                  │
│ │       ├── Pointer: "mqtt.broker"  (1/9 components)                                             │
│ │       │   └── sensor-dashboard-helm                                                            │
│ │       ├── Pointer: "MQTT_BROKER"  (4/9 components)                                             │
│ │       │   ├── sensor-dashboard-compose                                                         │
│ │       │   ├── sensor-dashboard-compose-simple                                                  │
│ │       │   ├── sensor-dashboard-quadlet                                                         │
│ │       │   └── sensor-dashboard-quadlet-simple                                                  │
│ │       └── Pointer: "SENSOR_DAEMON_MQTT_BROKER"  (4/9 components)                               │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-addon-sensor-daemon                                     │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-addon-sensor-daemon                                     │
│ ├── Port  [Setting]  immutable                                                                   │
│ │   ├── Schema: mqttPortSchema  integer · 1..65535 · allowEmpty false                            │
│ │   └── Parameter: mqttPort                                                                      │
│ │       ├── Default: 1883                                                                        │
│ │       ├── Pointer: "mqtt.port"  (1/9 components)                                               │
│ │       │   └── sensor-dashboard-helm                                                            │
│ │       ├── Pointer: "MQTT_PORT"  (6/9 components)                                               │
│ │       │   ├── sensor-dashboard-compose                                                         │
│ │       │   ├── sensor-dashboard-compose-addon-mosquitto                                         │
│ │       │   ├── sensor-dashboard-compose-simple                                                  │
│ │       │   ├── sensor-dashboard-quadlet                                                         │
│ │       │   ├── sensor-dashboard-quadlet-addon-mosquitto                                         │
│ │       │   └── sensor-dashboard-quadlet-simple                                                  │
│ │       └── Pointer: "SENSOR_DAEMON_MQTT_PORT"  (4/9 components)                                 │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-addon-sensor-daemon                                     │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-addon-sensor-daemon                                     │
│ └── Topic Pattern  [Setting]                                                                     │
│     ├── Schema: mqttTopicSchema  string · allowEmpty false                                       │
│     └── Parameter: mqttTopic                                                                     │
│         ├── Default: "sensors/vl53l0x/#"                                                         │
│         ├── Pointer: "mqtt.topic"  (1/9 components)                                              │
│         │   └── sensor-dashboard-helm                                                            │
│         └── Pointer: "MQTT_TOPIC"  (4/9 components)                                              │
│             ├── sensor-dashboard-compose                                                         │
│             ├── sensor-dashboard-compose-simple                                                  │
│             ├── sensor-dashboard-quadlet                                                         │
│             └── sensor-dashboard-quadlet-simple                                                  │
│                                                                                                  │
│ Dashboard  [Section]                                                                             │
│ ├── HTTP Port  [Setting]                                                                         │
│ │   ├── Schema: dashboardPortSchema  integer · 1..65535 · allowEmpty false                       │
│ │   └── Parameter: dashboardPort                                                                 │
│ │       ├── Default: 3000                                                                        │
│ │       ├── Pointer: "service.port"  (1/9 components)                                            │
│ │       │   └── sensor-dashboard-helm                                                            │
│ │       └── Pointer: "DASHBOARD_PORT"  (4/9 components)                                          │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-simple                                                  │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-simple                                                  │
│ ├── Log Level  [Setting]                                                                         │
│ │   ├── Schema: logLevelSchema  string · one of: error, warn, info, debug · allowEmpty false     │
│ │   └── Parameter: logLevel                                                                      │
│ │       ├── Default: "info"                                                                      │
│ │       └── Pointer: "LOG_LEVEL"  (4/9 components)                                               │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-simple                                                  │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-simple                                                  │
│ └── History Buffer Size  [Setting]                                                               │
│     ├── Schema: historySizeSchema  integer · ≥10 · allowEmpty false                              │
│     └── Parameter: historySize                                                                   │
│         ├── Default: 1000                                                                        │
│         └── Pointer: "HISTORY_SIZE"  (4/9 components)                                            │
│             ├── sensor-dashboard-compose                                                         │
│             ├── sensor-dashboard-compose-simple                                                  │
│             ├── sensor-dashboard-quadlet                                                         │
│             └── sensor-dashboard-quadlet-simple                                                  │
│                                                                                                  │
│ Virtual Sensors  [Section]                                                                       │
│ ├── Enable Virtual Sensors  [Setting]                                                            │
│ │   ├── Schema: virtualSensorsEnabledSchema  boolean · allowEmpty false                          │
│ │   └── Parameter: virtualSensorsEnabled                                                         │
│ │       ├── Default: true                                                                        │
│ │       ├── Pointer: "virtualSensors.enabled"  (1/9 components)                                  │
│ │       │   └── sensor-dashboard-helm                                                            │
│ │       └── Pointer: "VIRTUAL_SENSORS_ENABLED"  (4/9 components)                                 │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-simple                                                  │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-simple                                                  │
│ ├── Sensor Count  [Setting]                                                                      │
│ │   ├── Schema: virtualSensorsCountSchema  integer · 1..20 · allowEmpty false                    │
│ │   └── Parameter: virtualSensorsCount                                                           │
│ │       ├── Default: 4                                                                           │
│ │       ├── Pointer: "virtualSensors.count"  (1/9 components)                                    │
│ │       │   └── sensor-dashboard-helm                                                            │
│ │       └── Pointer: "VIRTUAL_SENSORS_COUNT"  (4/9 components)                                   │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-simple                                                  │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-simple                                                  │
│ └── Update Rate (Hz)  [Setting]                                                                  │
│     ├── Schema: virtualSensorsRateHzSchema  integer · 1..50 · allowEmpty false                   │
│     └── Parameter: virtualSensorsRateHz                                                          │
│         ├── Default: 10                                                                          │
│         ├── Pointer: "virtualSensors.rateHz"  (1/9 components)                                   │
│         │   └── sensor-dashboard-helm                                                            │
│         └── Pointer: "VIRTUAL_SENSORS_RATE_HZ"  (4/9 components)                                 │
│             ├── sensor-dashboard-compose                                                         │
│             ├── sensor-dashboard-compose-simple                                                  │
│             ├── sensor-dashboard-quadlet                                                         │
│             └── sensor-dashboard-quadlet-simple                                                  │
│                                                                                                  │
│ Sensor Daemon  [Section]                                                                         │
│ ├── Mode  [Setting]                                                                              │
│ │   ├── Schema: sensorDaemonModeSchema  string · one of: synthetic, gpio · allowEmpty false      │
│ │   └── Parameter: sensorDaemonMode                                                              │
│ │       ├── Default: "synthetic"                                                                 │
│ │       └── Pointer: "SENSOR_DAEMON_MODE"  (4/9 components)                                      │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-addon-sensor-daemon                                     │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-addon-sensor-daemon                                     │
│ ├── Sensor Name  [Setting]                                                                       │
│ │   ├── Schema: sensorDaemonSensorNameSchema  string · ≤64 chars · allowEmpty false              │
│ │   └── Parameter: sensorDaemonSensorName                                                        │
│ │       ├── Default: "sensor-0"                                                                  │
│ │       └── Pointer: "SENSOR_DAEMON_SYNTHETIC_SENSOR_NAME"  (4/9 components)                     │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-addon-sensor-daemon                                     │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-addon-sensor-daemon                                     │
│ └── Sensor Daemon Log Level  [Setting]                                                           │
│     ├── Schema: sensorDaemonLogLevelSchema  string · one of: DEBUG, INFO, WARNING, ERROR ·       │
│     │   allowEmpty false                                                                         │
│     └── Parameter: sensorDaemonLogLevel                                                          │
│         ├── Default: "INFO"                                                                      │
│         └── Pointer: "SENSOR_DAEMON_LOG_LEVEL"  (4/9 components)                                 │
│             ├── sensor-dashboard-compose                                                         │
│             ├── sensor-dashboard-compose-addon-sensor-daemon                                     │
│             ├── sensor-dashboard-quadlet                                                         │
│             └── sensor-dashboard-quadlet-addon-sensor-daemon                                     │
│                                                                                                  │
│ OpenTelemetry  [Section]                                                                         │
│ ├── Enable  [Setting]                                                                            │
│ │   ├── Schema: otelEnabledSchema  boolean · allowEmpty false                                    │
│ │   └── Parameter: otelEnabled                                                                   │
│ │       ├── Default: false                                                                       │
│ │       └── Pointer: "OTEL_ENABLED"  (4/9 components)                                            │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-simple                                                  │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-simple                                                  │
│ ├── OTLP Endpoint  [Setting]                                                                     │
│ │   ├── Schema: otelEndpointSchema  string · allowEmpty true                                     │
│ │   └── Parameter: otelEndpoint                                                                  │
│ │       ├── Default: "http://grafana:4318"                                                       │
│ │       └── Pointer: "OTEL_EXPORTER_OTLP_ENDPOINT"  (4/9 components)                             │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-simple                                                  │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-simple                                                  │
│ ├── Service Name  [Setting]                                                                      │
│ │   ├── Schema: otelServiceNameSchema  string · allowEmpty true                                  │
│ │   └── Parameter: otelServiceName                                                               │
│ │       ├── Default: "sensor-dashboard"                                                          │
│ │       └── Pointer: "OTEL_SERVICE_NAME"  (4/9 components)                                       │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-simple                                                  │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-simple                                                  │
│ ├── Service Version  [Setting]                                                                   │
│ │   ├── Schema: otelServiceVersionSchema  string · allowEmpty true                               │
│ │   └── Parameter: otelServiceVersion                                                            │
│ │       ├── Default: "1.0.0"                                                                     │
│ │       └── Pointer: "OTEL_SERVICE_VERSION"  (4/9 components)                                    │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-simple                                                  │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-simple                                                  │
│ ├── Deployment Environment  [Setting]                                                            │
│ │   ├── Schema: otelDeploymentEnvironmentSchema  string · allowEmpty true                        │
│ │   └── Parameter: otelDeploymentEnvironment                                                     │
│ │       ├── Default: "edge"                                                                      │
│ │       └── Pointer: "OTEL_DEPLOYMENT_ENVIRONMENT"  (4/9 components)                             │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-simple                                                  │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-simple                                                  │
│ ├── Device ID  [Setting]                                                                         │
│ │   ├── Schema: otelDeviceIdSchema  string · allowEmpty true                                     │
│ │   └── Parameter: otelDeviceId                                                                  │
│ │       ├── Default: ""                                                                          │
│ │       └── Pointer: "OTEL_DEVICE_ID"  (4/9 components)                                          │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-simple                                                  │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-simple                                                  │
│ ├── SDK Log Level  [Setting]                                                                     │
│ │   ├── Schema: otelLogLevelSchema  string · one of: ERROR, WARN, INFO, DEBUG · allowEmpty false │
│ │   └── Parameter: otelLogLevel                                                                  │
│ │       ├── Default: "WARN"                                                                      │
│ │       └── Pointer: "OTEL_LOG_LEVEL"  (4/9 components)                                          │
│ │           ├── sensor-dashboard-compose                                                         │
│ │           ├── sensor-dashboard-compose-simple                                                  │
│ │           ├── sensor-dashboard-quadlet                                                         │
│ │           └── sensor-dashboard-quadlet-simple                                                  │
│ └── Exporter Headers  [Setting]                                                                  │
│     ├── Schema: otelExporterHeadersSchema  string · allowEmpty true                              │
│     └── Parameter: otelExporterHeaders                                                           │
│         ├── Default: ""                                                                          │
│         └── Pointer: "OTEL_EXPORTER_OTLP_HEADERS"  (4/9 components)                              │
│             ├── sensor-dashboard-compose                                                         │
│             ├── sensor-dashboard-compose-simple                                                  │
│             ├── sensor-dashboard-quadlet                                                         │
│             └── sensor-dashboard-quadlet-simple                                                  │
│                                                                                                  │
│ Kubernetes  [Section]                                                                            │
│ ├── Service NodePort  [Setting]                                                                  │
│ │   ├── Schema: nodePortSchema  integer · 30000..32767 · allowEmpty false                        │
│ │   └── Parameter: serviceNodePort                                                               │
│ │       ├── Default: 30305                                                                       │
│ │       └── Pointer: "service.nodePort"  (1/9 components)                                        │
│ │           └── sensor-dashboard-helm                                                            │
│ └── Replica Count  [Setting]                                                                     │
│     ├── Schema: replicaCountSchema  integer · ≥1 · allowEmpty false                              │
│     └── Parameter: replicaCount                                                                  │
│         ├── Default: 1                                                                           │
│         └── Pointer: "replicaCount"  (1/9 components)                                            │
│             └── sensor-dashboard-helm                                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```
