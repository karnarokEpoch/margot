# Exit codes

`margot` uses a small, stable set of exit codes for command failures. Successful commands
exit with code `0`. Scripts can branch on the code without parsing the human-readable error
message written to stderr.

| Code | Meaning | Typical causes |
| --- | --- | --- |
| `0` | Success | The command completed successfully. |
| `1` | Generic or unexpected failure | An uncategorized exception or an internal failure. |
| `2` | Usage error | An invalid flag value or an incompatible flag combination detected before work begins. |
| `3` | Validation or semantic input failure | A malformed or semantically invalid URI, descriptor, version, package selection, or local build output. |
| `4` | Remote or authentication failure | Registry access, credential expiry or rejection, authentication, or permission failures. |

Errors retain the normal human-readable form and are written to stderr, prefixed with
`Error:`. The exit code is the machine-readable part of the failure contract; messages may
provide additional diagnostic detail.

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
Unexpected failures that do not fit one of the specific categories return code `1`.
