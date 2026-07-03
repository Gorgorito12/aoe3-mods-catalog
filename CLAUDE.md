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

If the field references **new asset files** in the mod folder (like `screenshots`), you must ALSO add those filenames to `ALLOWED_ASSETS` in `classify_pr.py` — it's an exact-name allowlist, and any file not in it forces tier3 (manual review), which would break asset-only auto-merge. Screenshots use the fixed convention **`screenshot1..screenshot8`** (`.png/.jpg/.jpeg/.gif`) precisely so they can be enumerated in `ALLOWED_ASSETS`; off-convention names still pass schema validation but land in tier3.

**Only ever move a field *up* in tier freely. Moving a field down (3→2, 2→1) weakens the security boundary** — anything that affects what the launcher downloads or executes (`install`, `update`, `sourceRepo`, `id`) must stay tier3.

### Image specs (single source of truth: `validate_images.py`)

Dimensions are validated by **aspect ratio + a width range** (NOT a single exact size), so any resolution up to 4K passes as long as the shape is right — e.g. a hero can be 1920×1080, 2560×1440 or 3840×2160. Keep these in sync with the schema field descriptions and any CONTRIBUTING.md:

- `icon.png` — square (1:1, ±2%), width 256–1024 px, PNG **with alpha**, ≤1 MB. Required if `mod.json` declares `icon`.
- `banner.png`/`.jpg` — 4:1 (±3%), width 1200–4800 px, PNG/JPEG, ≤2 MB. Workshop card thumbnail.
- `hero.png`/`.jpg` — 16:9 (±3%), width 1920–3840 px (1080p up to 4K), PNG/JPEG, ≤5 MB (use JPEG for 4K — a 4K PNG can be 10 MB+). Dashboard background; keep the subject in the **right half** (left is covered by title + PLAY button).
- `heroImages[]` — optional rotating dashboard heroes (2–6), each the **same spec as `hero`**. When ≥2 are listed the launcher cycles them with a crossfade (~7 s); takes precedence over the single `heroImage`. Validated per-entry by `check_hero`, capped at `MAX_HEROES` (6, must match the launcher's `MaxHeroes`).
- `screenshot1.png`…`screenshot8.<ext>` — gallery shown in the Workshop detail panel. PNG/JPEG/**GIF** (animated GIFs allowed **here only**, not in banner/hero), **no fixed dimensions**, ≤5 MB each, max 8. Declared in `mod.json` as the `screenshots` array (a tier‑1 cosmetic field). The declared extension must match the real format. The fixed `screenshot<N>` naming is required for auto-merge (see `ALLOWED_ASSETS`).

## Manifest conventions (`mod.json`)

- `id` must match the folder name under `mods/` and the pattern `^[a-z][a-z0-9-]{1,30}$`.
- `install.type`: `IsolatedFolder` (mod in its own cloned folder, e.g. WoL) vs `InPlaceOverlay` (files extracted over AoE3, e.g. Improvement Mod).
- `update.mechanism`: `WolPatcher` (UpdateInfo.xml + patches), `DelegatedExternal` (mod's own patcher), `GitHubReleases`, or `Manual`.
- `update.github.followLatest` (boolean, optional): opt-in for `GitHubReleases` mods to follow the repo's **newest stable release** (`GET /releases/latest` — drafts and prereleases are excluded by the endpoint) instead of pinning to `approvedReleaseTag`. The modder publishes a release and users get it with **no catalog PR per version**. `approvedReleaseTag` STAYS required: it seeds a first offline install and is the fallback when the GitHub API is unreachable. Ignored when `externalAssetUrlTemplate` is set (its pinned SHA-256 only covers the approved tag). It lives inside `update`, so enabling it is Tier 3 (reviewed once) — the trade-off is that subsequent releases skip the per-version approval gate, so only trusted mods should opt in. No `classify_pr.py` change needed: nested `update.*` edits already classify as tier3.
- `update.github.deltaPatches` (boolean, optional): opt-in incremental delta patches for `GitHubReleases`. When true, the launcher applies a small `patch-<from>-to-<to>.zip` (only the changed files, generated by the launcher's in-app tool and uploaded to the modder's GitHub release alongside the full `.zip`) instead of re-downloading the full overlay on a single-hop update. Best-effort with a full fallback; ignored for external-hosted mods. **The patch assets live on the modder's GitHub release, NOT in this catalog**, so they don't affect `ALLOWED_ASSETS` / `validate_images.py`. It's a field inside `update`, so a change to it is Tier 3 like any other `update.*` change. See the launcher's `docs/MODDING.md`.
- HTTP is tolerated for legacy `updateInfoUrl` / `officialWebsite` (e.g. aoe3wol.com); payload download URLs **must be HTTPS** — they are the highest-risk asset. `payloadSha256` arrays are parallel to the URL arrays and let the launcher reject tampered downloads.
