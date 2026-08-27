---
inclusion: auto
description: >
  Rules for rendering data that came from a file, a registry, or a user into rich
  Panels, Trees, Tables and Text. Use this when writing or reviewing any code that
  displays descriptor, manifest or config values — it prevents markup injection,
  ambiguous scalars and misaligned trees.
---

# Rich Rendering Rules

Applies to any code that puts **external data** on screen — YAML descriptors, OCI
manifests, registry responses, user input. All of it goes through `margot.console`
(see `code-conventions.md`); this file covers what to do *before* it gets there.

## 1. Never interpolate external data into a markup string

Rich reads `[...]` as markup. `array[string]` is a documented Margo `dataType` value, and
`[Container]` is a literal quadlet section header — both silently disappear if passed as
markup.

```python
# correct — data lives in a Text object, style applied separately
from rich.text import Text

line = Text("dataType  ", style="dim")
line.append(value)                      # value is never parsed

# also correct — explicit escape when a string is unavoidable
from rich.markup import escape
console.print_renderable(Panel(f"[bold]{escape(value)}[/bold]"))

# wrong — a value of "array[string]" renders as nothing
console.print_renderable(Panel(f"[bold]{value}[/bold]"))
```

Rule of thumb: **styles are code, values are data.** If a value reaches an f-string that
also contains `[`, it is a bug.

## 2. Render scalars in literal form, never coerced

`1883` and `"1883"` are different facts about a document. Preserve the distinction:

| Value | Rendered |
|---|---|
| `"host.containers.internal"` | `"host.containers.internal"` (quoted) |
| `1883`, `0.1` | `1883`, `0.1` (bare) |
| `true`, `false` | `true`, `false` (bare, lowercase — YAML form) |
| `""` | `""` |
| missing / `None` | `—` |

An empty string that the author wrote deliberately and a field that is absent are not the
same thing, and `—` for both hides a real difference.

## 3. Never truncate — wrap

Rich word-wraps for free. A folded URL is reviewable; an elided one is not.

```python
# correct
table.add_column("repository", overflow="fold")

# wrong — the reviewer now has to open the file anyway
table.add_column("repository", overflow="ellipsis", max_width=40)
```

Do not compute layouts from a hardcoded terminal width, and prefer stacked full-width
panels over `Columns`: side-by-side blocks introduce a width threshold that has to be
tuned and tested at every size.

## 4. Keep trees shallow; put modifiers on the parent line

Every `Tree` level costs indentation before any text appears. Before adding a level, ask
whether the information is a single token — if so it belongs on the parent's line.

```text
Port [Setting]  immutable                 # correct: one bit, no level
Schema: portSchema  integer · 1..65535    # correct: rules ride along

Port [Setting]                            # wrong: a level per fact
├── Immutable
└── Schema
    ├── name: portSchema
    └── dataType: integer
```

Align sibling key/value leaves by padding keys to the widest key **among those siblings**,
not to a global constant.

## 5. Compose with ` · `, never `,`

Values can contain commas (a `options` list, a description). Joining facts with `,`
makes the boundary between them unreadable. Use ` · `.

```python
"integer · 1..65535 · allowEmpty false"
```

## 6. Counts belong in titles

A panel over a long collection states its size up front: `Deployment profiles (7 profiles
· 9 components)`. Cheap to compute, and it is the first thing a reviewer wants.

When a count is a ratio, define the denominator explicitly and deduplicate identity-based
sets — the same component name declared in two deployment profiles is one component.

## 7. Layering

`domain/` builds display dataclasses and does the joins — no `rich` import, no `console`
import. `commands/` is the only layer that constructs `Panel`, `Tree`, `Table` or `Text`,
and it prints them through `console.print_renderable` / `console.print_table`. No file I/O
in `commands/`, no `rich` outside it.
