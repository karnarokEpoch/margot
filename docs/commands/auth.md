# margot auth

Manage OCI registry credentials.

```
margot auth login REGISTRY [--username USER] [--password-stdin] [--expiry-hours N]
margot auth logout REGISTRY
margot auth status
```

## margot auth login

Authenticate with an OCI registry and persist credentials.

```
margot auth login REGISTRY [--username USER] [--password-stdin] [--expiry-hours N]
```

### Arguments

| Argument | Description |
|---|---|
| `REGISTRY` | OCI registry hostname, e.g. `public.ecr.aws`. |

### Flags

| Flag | Default | Description |
| --- | --- | --- |
| `--username` | — | Registry username. |
| `--password-stdin` | off | Read the password from stdin instead of a prompt. |
| `--expiry-hours` | — | Hours until the credentials expire. Overrides auto-detected expiry (see [Credential expiry tracking](#credential-expiry-tracking)) and saves the resulting timestamp to `~/.config/margot/credentials.toml`. |

### How it works

margot delegates the full OCI auth challenge-response flow to oras-py.
Credentials are stored via the configured credential store (same as Docker/Podman).
This means, it also read credentials already configure for Docker/Podman.

### AWS ECR

Pass `--username AWS` and the token from `aws ecr get-login-password` (or
`aws ecr-public get-login-password`) as the password:

```bash
aws ecr-public get-login-password --region us-east-1 \
  | margot auth login public.ecr.aws --username AWS --password-stdin --expiry-hours 12
```

oras-py's ECR backend handles the challenge-response automatically. No boto3 dependency
in margot.

!!! note
    ECR tokens are typically auto-detected (they embed their own expiry), so
    `--expiry-hours` is optional here — it overrides the detected value rather than being
    required to enable tracking. Passing it is a reasonable habit when you know the token's
    validity window, but omitting it still records an expiry as long as the token carries one.

### Credential expiry tracking

By default, margot tries to **auto-detect** the expiry from the token itself (e.g. an ECR
token embeds its own expiry) and, if detected, persists it automatically — no flag
required. `--expiry-hours` only needs to be passed to **override** that auto-detected
value, or to supply one when the token carries no expiry information of its own.

Resolution order: an explicit `--expiry-hours` always wins over auto-detection.

Either way, the resolved expiry is written to `~/.config/margot/credentials.toml`:

```toml
[registries."public.ecr.aws"]
expires_at = "2026-06-26T23:00:00Z"
```

and echoed on a successful login (`Token expires in ...`). If neither auto-detection nor
`--expiry-hours` resolves an expiry, no timestamp is saved — `margot auth status` then
shows that registry as `UNKNOWN` rather than tracking a real expiry.

Every command that calls the registry checks this file before the operation. If the
credentials expire within one hour, a warning is printed. If already expired, the
command fails with a clear message and a `margot auth login` hint.

## margot auth logout

Remove stored credentials for a registry.

```
margot auth logout REGISTRY
```

Removes the expiry entry from `~/.config/margot/credentials.toml`.

### Arguments

| Argument | Description |
|---|---|
| `REGISTRY` | OCI registry hostname to log out from. |

## margot auth status

Show credential status for all tracked OCI registries.

```
margot auth status
```

No arguments, no flags.

Reads margot's credentials file (`~/.config/margot/credentials.toml`) and the
oras-py/Docker credential store, then prints a table with one row per registry.

### Output table

Expiry is classified using the same one-hour warning threshold as the pre-operation
credential check: within the last hour before expiry the status becomes `EXPIRING`;
past expiry it becomes `EXPIRED`.

Registries present in the oras-py/Docker credential store but not tracked in margot's
credentials file (i.e. logged in without `--expiry-hours`) appear in the same table with
`Expires At: -`, `Remaining: present but expiry unknown`, and `Status: UNKNOWN` (cyan).

When no credentials are tracked at all, no table is shown:

```
No credentials tracked.
```

### Example

```bash
margot auth status
```

```
              Registry Credential Status
┌──────────────────┬──────────────────────┬───────────────────────────┬──────────┐
│ Registry         │ Expires At           │ Remaining                 │ Status   │
├──────────────────┼──────────────────────┼───────────────────────────┼──────────┤
│ public.ecr.aws   │ 2026-06-27T01:00:00Z │ 11h 42m                   │ VALID    │
│ ghcr.io          │ -                    │ present but expiry unknown │ UNKNOWN  │
└──────────────────┴──────────────────────┴───────────────────────────┴──────────┘
```

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Login/logout/status succeeded. |
| 1 | Authentication failed, registry unreachable, or invalid arguments. |

## Example

```bash
# Log in to AWS ECR public registry
aws ecr-public get-login-password --region us-east-1 \
  | margot auth login public.ecr.aws --username AWS --password-stdin --expiry-hours 12

# Check credential status
margot auth status

# Log out
margot auth logout public.ecr.aws
```
