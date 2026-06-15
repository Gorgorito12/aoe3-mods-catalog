# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **data catalog**, not an application. It holds one `mod.json` manifest (plus optional images) per Age of Empires III mod under `mods/<id>/`. A separate **launcher** application (not in this repo) reads these manifests at runtime via `raw.githubusercontent.com` to know what to install, download, and execute. There is nothing to build or run here — the repo's "logic" is the CI that gates pull requests.

Because the launcher trusts these files to decide what to download and execute on a user's machine, **the PR-classification tiers are a security boundary**, not a convenience. Treat any field that controls download/execution as untrusted-until-reviewed.

## Validating locally

CI runs these on every PR; run them the same way before pushing:

```bash
# JSON Schema (matches the ajv invocation in auto-merge.yml)
npm install -g ajv-cli@5 ajv-formats@3
ajv validate -s schema/mod.schema.json -d "mods/**/mod.json" -c ajv-formats --strict=false

# Image specs (icon/banner/hero dimensions + size, scans every mod folder)
pip install Pillow
python .github/scripts/validate_images.py

# Tier classification — needs a base ref + head sha, run from a PR diff context
BASE_REF=main HEAD_SHA=$(git rev-parse HEAD) python .github/scripts/classify_pr.py
```

`validate_images.py` and `classify_pr.py` both assume the working directory is the repo root.

## Architecture: the three-tier auto-merge gate

The entire repo exists to let cosmetic and version-bump PRs merge themselves while forcing a human to review anything dangerous. The pipeline is in `.github/workflows/auto-merge.yml`: **classify → validate → (block | auto_merge | request_review)**.

`classify_pr.py` is the brain. It diffs the PR against the base and emits a `tier` to `GITHUB_OUTPUT`:

- **invalid** — touched files outside a single `mods/<id>/` folder, multiple mods at once, or an unrecognised filename → workflow comments and exits 1, branch protection blocks the merge.
- **tier1** — only cosmetic top-level fields changed (`TIER_1_FIELDS`), or assets-only with `mod.json` untouched → auto-merge after validation.
- **tier2** — only `approvedReleaseTag` bumped (`TIER_2_FIELDS`), possibly alongside tier1 fields → auto-merge after validation.
- **tier3** — any critical field changed (`TIER_3_FIELDS`: `id`, `sourceRepo`, `install`, `update`, `translations`), an unknown file in the folder, **or any first-time mod submission** → labelled `needs-manual-review`, no auto-merge.

Classification rules that are easy to get wrong:
- The workflow **enables** auto-merge (`gh pr merge --auto`); it never approves. Merges happen because branch protection requires the status checks to be green. Required approvals must be 0 (see README setup) — `GITHUB_TOKEN` cannot approve PRs by design.
- Comparison is on **top-level JSON keys only** (`diff_keys`). A nested change inside `install` or `update` registers as that whole key changing → tier3, which is the intended safe behaviour.
- Any schema-valid field not listed in one of the three `TIER_*_FIELDS` sets falls through to tier3 (the conservative default).

### Adding or reclassifying a schema field

Two files must stay in sync, plus the classifier:
1. `schema/mod.schema.json` — the field definition and validation (`additionalProperties: false`, so undeclared fields fail validation).
2. `classify_pr.py` — add the field to exactly one of `TIER_1_FIELDS` / `TIER_2_FIELDS` / `TIER_3_FIELDS`. Omitting it means PRs touching it always go tier3.

**Only ever move a field *up* in tier freely. Moving a field down (3→2, 2→1) weakens the security boundary** — anything that affects what the launcher downloads or executes (`install`, `update`, `sourceRepo`, `id`) must stay tier3.

### Image specs (single source of truth: `validate_images.py`)

Dimensions are enforced **exactly** (a 257×257 icon fails). Keep these in sync with the schema field descriptions and any CONTRIBUTING.md:

- `icon.png` — 256×256, PNG **with alpha**, ≤100 KB. Required if `mod.json` declares `icon`.
- `banner.png`/`.jpg` — 1200×300, PNG/JPEG, ≤500 KB. Workshop card thumbnail.
- `hero.png`/`.jpg` — 1920×1080, PNG/JPEG, ≤2 MB. Dashboard background; keep the subject in the **right half** (left is covered by title + PLAY button).

## Manifest conventions (`mod.json`)

- `id` must match the folder name under `mods/` and the pattern `^[a-z][a-z0-9-]{1,30}$`.
- `install.type`: `IsolatedFolder` (mod in its own cloned folder, e.g. WoL) vs `InPlaceOverlay` (files extracted over AoE3, e.g. Improvement Mod).
- `update.mechanism`: `WolPatcher` (UpdateInfo.xml + patches), `DelegatedExternal` (mod's own patcher), `GitHubReleases`, or `Manual`.
- HTTP is tolerated for legacy `updateInfoUrl` / `officialWebsite` (e.g. aoe3wol.com); payload download URLs **must be HTTPS** — they are the highest-risk asset. `payloadSha256` arrays are parallel to the URL arrays and let the launcher reject tampered downloads.
