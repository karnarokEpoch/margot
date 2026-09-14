# CI/CD Integration

margot is a plain CLI tool — it works on any CI system that can run a shell command.
This guide covers the two gate primitives designed for CI use, a suggested pipeline
shape, and how to handle credentials.

## Gate primitives

### Schema validation gate: `margot verify --strict`

`margot verify` validates `app.yaml` (or a rendered `app.yaml.jinja`) against the
upstream Margo spec schema and exits 0 on pass, 1 on any error. Adding `--strict` turns
the optional recommended-schema pass into a contract: any finding at any severity level
fails the run.

```bash
# Validate against the spec schema only
margot verify

# Validate against the spec schema, plus run the recommended schema as a warning
margot verify --recommend

# Validate against both; fail on any recommended finding too
margot verify --recommend --strict

# Validate against the recommended schema only
margot verify --only-recommend --strict
```

For the full behaviour matrix — which schema runs, what drives the exit code in each
combination — see [`margot verify`](../commands/verify.md).

### Registry write-access gate: `margot push --dry-run`

`margot push --dry-run` performs the same checks as a real push (OCI tag / SemVer
validation, built-artifact-exists-on-disk check, credential expiry check), plus a live
write-access probe against the registry. No artifact content is ever inspected or
uploaded.

The probe opens an OCI blob-upload session (`POST /v2/<repository>/blobs/uploads/`),
reads the response code, and immediately cancels the session. A `202 Accepted` confirms
write access; `401`/`403` is reported as a clear error with exit code 1.

The probe runs once per unique `(registry, repository)` pair per invocation — pushing
`--type all --variant all` against components that share one repository triggers the
probe exactly once.

```bash
margot push --dry-run
```

On success each target is reported:

```
Dry run OK: public.ecr.aws/g2n4p2m7/margo:1.0.0
```

## Suggested pipeline shape

A four-stage pipeline that catches failures early:

```
Stage 1 — verify
  margot verify --recommend --strict

Stage 2 — build
  margot build --type all

Stage 3 — dry-run push (registry gate)
  margot push --dry-run --type all

Stage 4 — push
  margot push --type all
```

**Why this order:**

- `verify` is fast, local, and needs no build artefacts — it catches descriptor errors
  before any registry contact.
- `build` produces the artefacts that `push` consumes. Running it before the dry-run
  means the dry run also confirms the artefacts exist on disk.
- `push --dry-run` confirms registry access and credentials before committing to an
  actual upload. A credential failure at this stage is cheap to retry.
- `push` does the real upload only after all earlier gates pass.

In practice, stages 3 and 4 can be collapsed into a single `margot push` if your CI
already validated credentials in a previous step (e.g. the verify stage or a dedicated
auth step). The dry-run stage is most valuable when credential expiry is uncertain or
when the pipeline runs on a fresh runner.

## Exit codes

margot uses exit code `0` for success and `1` for any failure. CI systems treat
non-zero exit codes as step failures automatically.

For the exact conditions that produce exit code `1` per command, see the exit-code tables
in:

- [`margot verify` — Exit codes](../commands/verify.md#exit-codes)
- [`margot push` — Exit codes](../commands/push.md#exit-codes)
- [`margot build` — Exit codes](../commands/build.md#exit-codes)

## Credential handling

See [Authentication](authentication.md) for the full expiry lifecycle and ECR token
retrieval walkthrough.

The key points for CI:

- Log in at the start of the job with `margot auth login`. For AWS ECR, pipe the token
  from `aws ecr-public get-login-password` (or `aws ecr get-login-password`) directly
  into `--password-stdin`.
- ECR tokens are valid for 12 hours. For pipelines that run longer, schedule a re-login
  step or split the job.
- Use `margot auth status` after login to confirm the credential state before moving to
  build/push stages.
- Optionally run `margot auth logout` at the end of the job to clean up credentials on
  shared runners.

Inject registry credentials as CI secrets (environment variables or a secret store) —
never hard-code them in pipeline configuration files.
