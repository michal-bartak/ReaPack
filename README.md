# MXM Scripts — a ReaPack repository

All of my REAPER scripts, published as one ReaPack repository. Import it once
and install whichever packages you want.

## Install

In REAPER: *Extensions → ReaPack → Import repositories*, then paste:

```
https://github.com/michal-bartak/ReaPack/raw/main/index.xml
```

Then *Extensions → ReaPack → Browse packages* and install what you need.
Updates arrive through ReaPack from then on.

## What's in it

| Package | What it does | Source |
|---|---|---|
| **AutoColor** | Colours tracks, items, regions and markers from their names, using substring, glob or real regular expressions. | [Reaper-AutoColor](https://github.com/michal-bartak/Reaper-AutoColor) |
| **List of Instruments and Effects** | Lists every plugin used in a project, grouped into categories, and copies the report out as text, Markdown or BBCode. | [ListOfInstrumentsAndEffects](https://github.com/michal-bartak/ListOfInstrumentsAndEffects) |

## How this repository works

There is no source code here. Each script lives in its own repository and
carries its own ReaPack manifest, so the list of files that make up a package
is maintained next to the code it describes — never here.

Every source repository runs [`reapack-index`](https://github.com/cfillion/reapack-index)
itself and publishes its own `index.xml`. `merge-index.py` then fetches those
and re-roots each `<category>` under a single `<index name="MXM Scripts">`.
The download URLs inside a generated index are already absolute and point at
their own repository, so nothing is rewritten and no file is duplicated here.

```sh
./merge-index.py          # fetch the source indexes and rewrite index.xml
./merge-index.py --check  # verify index.xml is current; exits non-zero if not
```

**A source repository cutting a version does not reach anyone until this runs.**
ReaPack clients import the merged index from *this* repository; the per-repo
indexes are only inputs. So publishing is two steps, in two repositories.

The **Merge index** workflow (Actions -> Merge index -> Run workflow) does it on
demand: it regenerates `index.xml`, pushes only if it changed, and then verifies
the result with `--check`. It also runs weekly as a safety net for forgetting.

A source repository can trigger it directly instead, with a
`repository_dispatch` of type `reapack-index-updated`. That needs a PAT with
`contents:write` on this repository held as a secret over there -- a source
repo's own `GITHUB_TOKEN` cannot reach across.

Adding a script means adding its repository to `SOURCES` in `merge-index.py`
and re-running it. Duplicate packages across repositories are a hard error.

`index.xml` is generated — don't edit it by hand.
