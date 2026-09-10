# margot fetch

Fetch and display the manifest of an OCI artifact without downloading layers.

```
margot fetch <uri>
```

!!! note
    `fetch` is a lightweight debugging/inspection command, modeled after `oras manifest fetch`. It fetches and prints the raw OCI manifest for a given tag — nothing more. No layers are downloaded, nothing is written to disk. Use `margot pull` when you need the artifact layers on disk.

## Arguments

| Argument | Description |
|---|---|
| `<uri>` | Full OCI reference: `registry/repository:tag`. Example: `public.ecr.aws/g2n4p2m7/margo:1.0.0` |

## What it does

`fetch` retrieves the OCI manifest for the given artifact and pretty-prints it as JSON.
No layers are downloaded, nothing is written to disk.

No SemVer validation: `fetch` inspects arbitrary existing artifacts, including legacy tags.
SemVer enforcement is scoped to `build` and `push` only.

## Output

Raw manifest JSON, pretty-printed to stdout via `rich`. No table, no filtering — whatever
the registry returns is shown as-is.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Manifest fetched and printed. |
| 1 | Invalid URI, manifest fetch failed, or registry error. |

## Example

```bash
# Inspect a margo artifact manifest
margot fetch public.ecr.aws/g2n4p2m7/margo:1.0.0

# Inspect a compose variant manifest
margot fetch public.ecr.aws/g2n4p2m7/margo:1.0.0_compose-default
```

## Tip

Use `margot pull` when you need the actual artifact layers on disk. Use `margot fetch`
for a quick remote inspection of what a tag contains.
