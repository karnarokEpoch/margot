# Exit codes

`margot` uses a small, stable set of exit codes for command failures. Successful commands
exit with code `0`. Scripts can branch on the code without parsing the human-readable error
message written to stderr.

| Code | Meaning                              | Typical causes                                                                                          |
| ---- | ------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| `0`  | Success                              | The command completed successfully.                                                                     |
| `1`  | Generic or unexpected failure        | An uncategorized exception or an internal failure.                                                      |
| `2`  | Usage error                          | An invalid flag value or an incompatible flag combination detected before work begins.                  |
| `3`  | Validation or semantic input failure | A malformed or semantically invalid URI, descriptor, version, package selection, or local build output. |
| `4`  | Remote or authentication failure     | Registry access, credential expiry or rejection, authentication, or permission failures.                |

Errors retain the normal human-readable form and are written to stderr, prefixed with
`Error:`. The exit code is the machine-readable part of the failure contract; messages may
provide additional diagnostic detail.

Commands that support `--json` replace this prose only for machine-readable command output:
JSON results are written to stdout, while JSON error envelopes are written to stderr in the
form `{"error": true, "code": <int>, "message": "..."}`. The message is plain JSON data,
not Rich markup.

## Color controls

Use the global `--no-color` option to disable ANSI styling for one invocation:

```bash
margot --no-color describe
```

margot also honors the [`NO_COLOR` convention](https://no-color.org/): if the `NO_COLOR`
environment variable is present, regardless of its value, color is disabled. These controls
affect both stdout and stderr while preserving the normal output text and stream routing.

## install

| Code | Situation                                                                                                                             |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `0`  | Successful install, or `--dry-run` completed                                                                                          |
| `1`  | User declined confirmation ("Aborted: nothing was installed")                                                                         |
| `1`  | systemd user session is unusable                                                                                                      |
| `1`  | `daemon-reload` failed                                                                                                                |
| `1`  | Expected service unknown to systemd after `daemon-reload`                                                                             |
| `2`  | `URI` given with `--project-dir` or `--build-dir`                                                                                     |
| `2`  | `--build-dir` given outside project mode                                                                                              |
| `2`  | `--set NAME` without `=`                                                                                                              |
| `2`  | No terminal and neither `--yes` nor `--dry-run`                                                                                       |
| `3`  | No descriptor found (lists the paths tried)                                                                                           |
| `3`  | Unknown, non-installable, or ambiguous profile                                                                                        |
| `3`  | Component problem: no OCI coordinates, `packageLocation`, or unsafe name                                                              |
| `3`  | Archive missing, not a tar, no quadlet unit at root, or hostile archive                                                               |
| `3`  | Two components ship the same relative path                                                                                            |
| `3`  | Application directory exists without margot marker, or holds a different profile                                                      |
| `3`  | Parameter error: unknown `--set` name, reserved pointer, same pointer on two parameters, array value, or forbidden character in value |
| `3`  | Unit-name collision (file name or generated service name)                                                                             |
| `3`  | Quadlet generator rejected the unit files                                                                                             |
| `4`  | Registry or credential failure                                                                                                        |

## Examples

An invalid build type is a usage error:

```console
$ margot build --type invalid
Error: invalid --type 'invalid'. Must be one of: margo, compose, quadlet, all
$ echo $?
2
```

An invalid version is a validation failure:

```console
$ margot build --type margo --version not-semver
Error: 'not-semver' is not valid SemVer
$ echo $?
3
```

A registry permission failure is a remote/authentication failure and returns code `4`.

A registry that answers a remote read or an upload with an HTTP error status is a remote failure and returns
code `4`. Examples are `429 Too Many Requests`, a `5xx`
status, and a `404` for a tag that does not exist. The message names the status code, the
reason phrase, the method and the request URL. It never includes credentials or query strings.

```console
$ margot describe public.ecr.aws/g2n4p2m7/margo:9.9.9
Error: Registry returned 404 Not Found for GET https://public.ecr.aws/v2/g2n4p2m7/margo/manifests/9.9.9
$ echo $?
4
```

Unexpected failures that do not fit one of the specific categories return code `1`.
