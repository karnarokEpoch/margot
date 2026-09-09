---
inclusion: auto
description: >
  Product purpose, users, delivered capability, and authoritative product references
  for margot.
---

<!-- markdownlint-disable-file MD041 -->

# Product Context

margot is a developer CLI for packaging, validating, publishing, and inspecting [Margo](https://margo.org) application
packages as OCI artifacts.

## Users and problems

- **Application developers** package a Margo application description and its deployment components reproducibly.
- **Platform engineers** publish, retrieve, validate, and review those artifacts from OCI registries without
  hand-assembling OCI manifests or registry requests.

margot makes the project descriptor (`margo.yaml`), local package build, OCI media metadata, registry authentication,
and descriptor inspection/validation work together through one CLI.

## Current product surface

The shipped CLI provides `build`, `push`, `pull`, `fetch`, `verify`, `describe`, and `auth`. It supports margo
application artifacts plus compose and quadlet components. `verify` is a schema-validation gate; `describe` is a
read-only human review view.

`FEATURES.md` is authoritative for user-visible behavior, command contracts, OCI media types, and configuration.
`ROADMAP.md` is authoritative for planned work and sequencing.
