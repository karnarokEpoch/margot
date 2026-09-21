# Authentication

This guide walks through OCI registry authentication in margot: which commands need it,
how to log in, how expiry is tracked, and how to rotate or remove credentials.

For the flag reference, see [`margot auth`](../commands/auth.md).

## Which commands require authentication

- **`margot push`** requires valid registry credentials. Pushing fails immediately if no
  credentials are present or if they have expired.
- **`margot pull`** and **`margot fetch`** work anonymously — they never use stored
  credentials. Passing `--username` / `--password-stdin` is not supported by these
  commands.
- **`margot build`**, **`margot verify`**, and **`margot describe`** are entirely local —
  no registry contact at all.

## Logging in

### Generic registry

```bash
margot auth login registry.example.com --username myuser --password-stdin
```

margot delegates the OCI auth challenge-response flow to oras-py. Credentials are stored
in the configured credential store (same as Docker/Podman), so logins you've already
done with Docker or Podman are visible to margot.

If you prefer not to pass the password via stdin, omitting `--password-stdin` prompts
you interactively.

### AWS ECR

ECR tokens are retrieved with the AWS CLI and piped directly into margot. The token acts
as the password; `--username AWS` is the fixed username the ECR API requires.

```bash
# Public ECR (us-east-1 is the only supported region for public.ecr.aws)
aws ecr-public get-login-password --region us-east-1 \
  | margot auth login public.ecr.aws --username AWS --password-stdin
```

```bash
# Private ECR (replace us-east-1 with your registry region)
aws ecr get-login-password --region us-east-1 \
  | margot auth login 123456789012.dkr.ecr.us-east-1.amazonaws.com \
      --username AWS --password-stdin
```

**Why `--username AWS`?** The ECR API requires this exact string as the username
regardless of the IAM identity behind the token — the token itself carries all the
authorization claims.

**Why the token is short-lived:** ECR tokens are valid for 12 hours. After that, any
push attempt will fail with an authentication error. margot tracks this automatically —
see the next section.

## Credential expiry lifecycle

### What gets persisted and where

When margot detects an expiry from the token (ECR tokens carry their own expiry), it
writes a timestamp to `~/.config/margot/credentials.toml`:

```toml
[registries."public.ecr.aws"]
expires_at = "2026-06-27T01:00:00Z"
```

This happens automatically — no flag needed. `--expiry-hours` only exists to **override**
the auto-detected value, or to supply one when the token itself carries no expiry. You do
not need to pass `--expiry-hours` to enable expiry tracking with ECR.

### What happens before each registry operation

Every command that contacts the registry (`margot push`) checks the credentials file
first:

- **More than 1 hour remaining:** proceeds normally.
- **Less than 1 hour remaining:** prints a warning and proceeds. You can still push, but
  refreshing now avoids a failure mid-build later.
- **Expired:** fails immediately with a message and a `margot auth login` hint. Nothing
  is pushed.

### Checking status proactively

Before pushing — especially in a new session or after an overnight break — check your
credential state:

```bash
margot auth status
```

This shows a table with expiry timestamps and current status (`VALID`, `EXPIRING`,
`EXPIRED`, or `UNKNOWN`) for all tracked registries. Catching a near-expiry here is
easier than diagnosing a mid-pipeline failure.

Registries logged in via Docker/Podman but without a margot-tracked expiry appear in the
table with `Status: UNKNOWN`. They can still be used for pushing — margot just has no
expiry information for them.

See [`margot auth`](../commands/auth.md#margot-auth-status) for the full table format.

## Logging out

```bash
margot auth logout public.ecr.aws
```

This removes the stored credentials from the credential store and deletes the expiry
entry from `~/.config/margot/credentials.toml`.

**When to log out:**

- **Rotating credentials** — log out, then log in again with a fresh token. Especially
  relevant for ECR's 12-hour tokens.
- **CI cleanup** — in a CI environment where you log in at the start of a job, logging
  out at the end avoids leaving credentials on a shared runner. If credentials are
  injected as environment variables for the job only, a logout step ensures they are not
  inadvertently cached.

## Credential handling in CI

See [CI/CD integration — Credential handling](ci-cd.md#credential-handling) for how to
structure authentication within a pipeline. The short version: log in at the start of
the job, use `margot auth status` to confirm state, push, and optionally log out at the
end.
