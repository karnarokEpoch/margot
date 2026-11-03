# Fix — `auth login` password entry: `--password`, hidden prompt, no hang on a terminal

**Status:** planned
**Type:** fix (no sprint number; lands on its own branch in any release, see `sprint-workflow`)
**Owner:** python-dev
**Release:** next fix release (TBD)

---

## 1. Goal

Make `margot auth login` usable by a person at a terminal. Today the only way to give a password is a
pipe (`echo -n … | margot auth login … --password-stdin`). Add a `--password` option, add a hidden
interactive prompt, and stop `--password-stdin` from hanging when stdin is a terminal.

---

## 2. Context

Bug report (manual testing, 2026-11-03), against `release/0.11.0`:

```text
$ margot auth login --username admin yourpassword localhost:15000
Error: Got unexpected extra argument(s) (localhost:15000)                       # (1)

$ margot auth login --username admin localhost:15000
Error: Password required. Use --password-stdin.                                 # (2)

$ margot auth login --username admin --password-stdin localhost:15000
yourpassword                                                                    # (3)
^C                                                                              # nothing happens on Enter

$ echo -n "yourpassword" | margot auth login --username admin --password-stdin localhost:15000
Logged in to localhost:15000.                                                   # only this works
```

Findings, from `src/margot/commands/auth.py::login` and `src/margot/console.py::read_stdin`:

1. **No way to pass the password as an option.** The command has no `--password`. The bare token in
   example (1) is read as a second positional argument, and `REGISTRY` is the only one, so Typer exits 2.
   A positional password stays unsupported (see Non-goals); `--password` is the added form.
2. **No interactive prompt.** Without `--password-stdin` the command exits 2 with
   `Password required. Use --password-stdin.` There is nothing to type a password into.
   `docs/commands/auth.md` describes `--password-stdin` as "Read the password from stdin **instead of
   a prompt**". That prompt does not exist, so the docs promise behavior the code does not have.
3. **`--password-stdin` on a terminal looks hung.** `console.read_stdin()` is `sys.stdin.read()`, which
   blocks until EOF. On a terminal, Enter does not end it; only Ctrl-D does. The user pressed Ctrl-C.
4. **The typed password is echoed** on the terminal in case 3 (`yourpassword` is visible), so it also
   lands in scrollback and screen recordings.

Authoritative references: `.kiro/steering/code-conventions.md` (all stdin/stdout/stderr access goes
through `console.py`; exit-code taxonomy; selective imports), `docs/commands/auth.md`, Sprint 4
(introduced `auth login`).

---

## 3. Authoritative Design

### Scope

**In scope:**

- `commands/auth.py::login` — new `--password` option and the password resolution below.
- `console.py` — two small helpers that own the terminal access: one tells whether stdin is a
  terminal, one reads a secret without echo, writing the prompt text to stderr.
- Updated error and flag help text.
- `docs/commands/auth.md` — document the four ways to provide a password and the risk of `--password`.

**Not in scope:**

- Any change to `auth_service.login`, credential storage, expiry detection or `--expiry-hours`.
- `auth logout`, `auth status`.
- See Non-goals.

### User-visible behavior

New option: `--password VALUE` — registry password or token. **Insecure**: the value is visible in shell
history and in the process list. Prefer the prompt or `--password-stdin`.

Password resolution in `margot auth login`, evaluated top to bottom, first match wins:

| `--password` | `--password-stdin` | stdin is | Behavior |
|---|---|---|---|
| given | given | any | Exit 2: `--password and --password-stdin are mutually exclusive.` |
| given | absent | any | Use the value. Emit `console.warning` on stderr that a password on the command line is visible in shell history and process lists, and name the alternatives. |
| absent | given | not a terminal (pipe, redirect) | Unchanged. Read all of stdin, strip surrounding whitespace. |
| absent | given | a terminal | Read **one line** with echo off, prompting `Password:` on stderr. Enter submits. No Ctrl-D needed. |
| absent | absent | a terminal | Same hidden prompt as the row above. |
| absent | absent | not a terminal | Exit 2: `Password required. Use --password, --password-stdin, or run in a terminal to be prompted.` |

Other rules:

- An empty password, from `--password ""`, the pipe or the prompt, exits 2 (`Empty password received.`).
  The text names the source in use where that is cheap to do.
- The prompt text goes to **stderr** so stdout stays clean for scripts. The password value is never
  echoed, logged (`console.debug`), or included in any error message, whatever its source.
- `--username` stays required, exit 2 when missing (unchanged).
- `--password-stdin` help text: `Read the password from stdin (piped input). On a terminal, prompts
  without echo.` The docs flag-table row is updated to match; the "instead of a prompt" wording goes.
- All failure paths keep their exit codes: usage errors 2, registry/auth failures 4, unexpected 1.

### Contracts

`console.py` (the only module allowed to touch `sys.stdin`; see `code-conventions.md`):

- `is_stdin_tty() -> bool` — `sys.stdin.isatty()`, evaluated at call time so test runners can swap the
  stream.
- `prompt_secret(label: str) -> str` — reads one line without echo and prints `label` to stderr. Return
  the raw value; the caller strips it.

Implementation hint (the dev agent verifies, may choose differently): Typer's `prompt(...,
hide_input=True, err=True)` already does both, and `CliRunner` simulates hidden input from its `input`
argument. Use selective imports (`from typer import prompt`).

`commands/auth.py::login` gains one parameter, `password: str | None` (`--password`, no short flag).
Everything else in the signature is unchanged. `domain/` is not touched.

### Dependencies

None new.

### Non-goals

- **No positional password.** `login USER PASS REGISTRY` stays a usage error (exit 2). A positional
  secret is unlabelled and easy to confuse with the registry; `--password` is the explicit form.
- **No short flag for `--password`** (no `-p`), to keep the insecure form deliberate.
- **No `MARGOT_PASSWORD` environment variable.** Environment variables leak to child processes and
  `/proc`; CI keeps using `--password-stdin` with a pipe from the secret store. Revisit only if a
  concrete CI need appears.
- **No username prompt.** Owner decision pending: Docker prompts for it. Left out to keep this a
  password-only fix.
- **No password confirmation prompt** (login, not account creation).

---

## 4. Checkable Steps

Tests first (TDD). Test names for exit codes follow `…_exits_<code>` with matching docstrings.

- [ ] Unit tests for `console.is_stdin_tty` and `console.prompt_secret`: the value is returned
  unchanged, the label goes to stderr, nothing goes to stdout.
- [ ] E2E tests in `tests/e2e/test_auth_cli.py` (patch `console.is_stdin_tty` for the terminal cases;
  `CliRunner` stdin is not a terminal by default):
  - [ ] `--password VALUE`: reaches `auth_service.login` unchanged, exit 0, and a warning about the
    command-line password is on stderr (and not on stdout);
  - [ ] `--password VALUE` never reads stdin or prompts (`console.read_stdin` and the prompt are not
    called);
  - [ ] `--password VALUE --password-stdin` exits 2 (mutually exclusive), `auth_service.login` not called;
  - [ ] `--password ""` exits 2;
  - [ ] terminal + no flag: prompted password reaches `auth_service.login` stripped, exit 0;
  - [ ] terminal + `--password-stdin`: prompt is used, `console.read_stdin` is **not** called, exit 0;
  - [ ] pipe + `--password-stdin`: unchanged (existing test stays green);
  - [ ] pipe + no flag: exits 2, message mentions `--password`, `--password-stdin` and the terminal
    prompt (update `test_auth_login_without_password_stdin_exits_2`);
  - [ ] empty prompt input and empty pipe both exit 2;
  - [ ] the password string appears in neither stdout nor stderr in any case, including `--debug`
    (the warning must not echo the value);
  - [ ] a positional password (`login --username u secret host`) exits 2 (documents the contract).
- [ ] Implement the two `console.py` helpers.
- [ ] Add `--password` and rewrite the password branch in `commands/auth.py::login` per the table.
- [ ] Update the `--password-stdin` help text and add the `--password` help text (mark it insecure).
- [ ] Update `docs/commands/auth.md`: synopsis, flag table (both rows), a "Providing the password"
  section listing the prompt, `--password-stdin`, `--password` (with the warning) and CI guidance,
  keep the ECR example. Check `README.md` for the old wording.
- [ ] `make docs-check` passes.
- [ ] Manual check on a real terminal: prompt appears, input is hidden, Enter submits, Ctrl-C exits
  cleanly, `--password` logs in and warns, and `echo -n pw | margot auth login … --password-stdin`
  still works.
- [ ] Close-out, after the above passes: delete this file in its own commit
  `chore: close out fix auth-login-password`, remove the ROADMAP backlog entry for this fix, and check
  that no reference to `fix-auth-login-password` is left in `*.md` files.
- [ ] Each task committed as one or more commits (for example `test(auth): …`,
  `fix(auth): add --password and prompt for the password on a terminal`, `docs(auth): …`).

---

## 5. Definition of Done

- [ ] All checkable steps completed.
- [ ] `make check` passes (lint + unit + integration tests), apart from any known environment-only
  failure that fails the same way on the base branch.
- [ ] E2E tests pass.
- [ ] Docs updated and `make docs-check` passes.
- [ ] No TODOs left (or explicitly deferred with a `# TODO(kiro): …` comment and a ROADMAP backlog entry).
- [ ] Each task committed as one or more commits on the feature branch, no bulk end-of-work commit.
- [ ] Handed back for review (Gate 2). After approval the planner pushes; the owner opens the PR onto
  the release branch and merges. The agent does not push, open PRs, or manage worktrees.

---

## 6. Close-out Note

```text
(filled in after merge)
```

---

## References

- [sprint-workflow skill](../skills/sprint-workflow/SKILL.md) — fixes need no sprint number.
- [ROADMAP.md](../../ROADMAP.md)
- [code-conventions.md](../steering/code-conventions.md)
- [docs/commands/auth.md](../../docs/commands/auth.md)
