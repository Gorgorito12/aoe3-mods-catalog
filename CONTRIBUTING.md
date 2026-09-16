# Contributing a mod to the catalog

This repo is a **data catalog**, not an application. Each mod is one folder under `mods/<id>/`
containing a `mod.json` manifest and its images. The Age of Empires III launcher reads these
manifests at runtime to decide what to download, install and execute, so every PR goes through an
automated gate before it can merge.

## The rules the CI enforces

A PR merges itself only if **all** of these hold.

1. **One mod folder per PR.** Every changed path must live under a single `mods/<id>/`. A PR that
   also touches workflows, the schema or documentation is rejected — open a separate PR for those.
2. **You maintain that mod.** Your GitHub username must already be in the mod's `maintainers` array
   on the target branch. If it is not, a maintainer has to review your PR (for a first submission)
   or it is blocked (for an edit to someone else's mod). Ask a repo maintainer to add you once your
   first submission is accepted; you cannot add yourself in the same PR.
3. **Only recognised filenames**, exactly these: `mod.json`, `icon.png`, `banner.png` / `banner.jpg`,
   `hero.png` / `hero.jpg`, and `screenshot1`…`screenshot8` with a `.png`, `.jpg`, `.jpeg` or `.gif`
   extension. Anything else — including an off-convention screenshot name — forces manual review.
4. **`mod.json` passes the schema** (`schema/mod.schema.json`) and the images pass the spec below.

## Writing `mod.json`

- **Save it as UTF-8 _without_ a BOM, with LF line endings.** A leading byte-order mark used to make
  the classifier read an empty `maintainers` list and silently lock a mod's own owners out of
  auto-merge, and made the image checks skip the mod while still reporting success. The scripts
  tolerate a BOM now, but do not add one. In VS Code the status bar must read `UTF-8`, not
  `UTF-8 with BOM`.
- `id` must equal the folder name and match `^[a-z][a-z0-9-]{1,38}$` (so at most **39** characters).
  The launcher compares the two **exactly** and skips any mod where they differ — it does not
  show up at all, and no check here will warn you. It is also the launcher's primary key: your
  users' saved install path, their collection entry and the uninstall registry key are all filed
  under it. Treat it as permanent.
- `previousIds` — if you ever do have to rename, rename the folder and the `id` in the **same**
  commit and list the old folder name here, e.g. `"previousIds": ["my-mod"]`. CI refuses a rename
  without it, because that is what lets the launcher move your users' install path onto the new id
  and recognise their existing install folder instead of offering them a fresh download. Never
  list an id that is not yours. Also pin `"installProductGuid": "<old-id>_launcher"` so their
  Add/Remove Programs entry survives. A rename always goes to manual review.
- `displayName` ≤ 50 characters, `subtitle` ≤ 50, `author` ≤ 100.
- `description` is a map of ISO-639-1 codes to strings, **each at most 500 characters**. `en` is the
  fallback the launcher uses when the user's language is missing.
- Payload download URLs must be **HTTPS**. (`officialWebsite` and legacy `updateInfoUrl` may be HTTP
  for old mod sites that still have no certificate.)
- Point your editor at the schema for live validation:
  `"$schema": "https://raw.githubusercontent.com/Gorgorito12/aoe3-mods-catalog/main/schema/mod.schema.json"`

## Image specs

`.github/scripts/validate_images.py` is the single source of truth; this table mirrors it.
Dimensions are checked as **aspect ratio + a width range**, not one exact size, so anything up to
4K passes as long as the shape is right. The declared extension must match the real format.

| File | Aspect | Width | Format | Max size |
|---|---|---|---|---|
| `icon.png` | 1:1 (±2%) | 256–1024 px | PNG **with alpha** | 1 MB |
| `banner.png` / `.jpg` | 4:1 (±3%) | 1200–4800 px | PNG / JPEG | 2 MB |
| `hero.png` / `.jpg` | 16:9 (±3%) | 1920–3840 px | PNG / JPEG | 5 MB |
| `heroImages[]` (2–6) | same as `hero` | same as `hero` | same as `hero` | 5 MB each |
| `screenshot1`…`screenshot8` | any | any | PNG / JPEG / GIF | 5 MB each |

Animated GIFs are allowed **only** for screenshots, never for a banner or hero. Keep the subject of
a hero image in its **right half** — the left is covered by the mod title and the PLAY button. Use
JPEG for 4K heroes; a 4K PNG easily exceeds the 5 MB cap.

## Checking your PR before you push

```bash
# Schema
npm install -g ajv-cli@5 ajv-formats@3
ajv validate -s schema/mod.schema.json -d "mods/**/mod.json" -c ajv-formats --strict=false

# Images
pip install Pillow
python .github/scripts/validate_images.py
```

Both assume the repo root as the working directory.

## What happens to your PR

The `Classify changes` check decides the outcome and comments it on the PR:

- **you maintain this mod** → auto-merge is enabled; it merges as soon as the checks are green.
- **first submission, or a change to a mod you don't maintain yet** → labelled
  `needs-manual-review`. A maintainer will look at it; please don't post pressure comments.
- **a change to someone else's mod** → blocked, with an explanation.
- **structurally not a catalog PR** (several mods, files outside `mods/`) → blocked, with an
  explanation.

If validation fails, push more commits to the same PR — the checks re-run and the decision is
recomputed on the new diff.
