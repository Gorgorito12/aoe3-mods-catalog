# aoe3-mods-catalog template

This folder is **scaffolding for a separate GitHub repo** — `papillo12/aoe3-mods-catalog` (or whatever you call it). It is not meant to live inside the launcher repo. Copy these files into a fresh repo when you're ready.

---

## What's inside

```
aoe3-mods-catalog-template/
├── .github/
│   ├── scripts/
│   │   ├── classify_pr.py          PR change classifier (owner/tier3/…)
│   │   └── validate_images.py      Icon and banner spec checks
│   └── workflows/
│       ├── auto-merge.yml          classify → validate (read-only token)
│       └── auto-merge-apply.yml    merge / label / comment (writable token)
└── schema/
    └── mod.schema.json             JSON Schema every mod.json is checked against
```

The workflow runs on every PR. It classifies the diff by **what changed** AND **who is
changing it** (per-mod ownership), and emits one of these outcomes:

| Outcome | When | Action |
|---|---|---|
| **owner** | The PR author is a maintainer of the mod it touches (or a repo-wide maintainer) — **any field, including `install`/`update`** | Auto-merge after schema + image validation passes |
| **tier3** | A first-time mod submission, an unknown file, a deleted manifest, a **folder rename**, unparseable JSON, or a **non-owner** proposing a critical/unknown-field change | Labelled `needs-manual-review`; you approve manually |
| **unauthorized** | A **non-owner** trying to change a mod's cosmetic/release fields | **Blocked** — the classify check fails, branch protection stops the merge |
| **invalid** | Files outside `/mods/`, multiple mods at once, or a genuinely empty diff | **Blocked** the same way — `classify` exits non-zero — plus an explanatory comment |
| **infra** | A **repo-wide maintainer** changing only repo infrastructure (workflows, scripts, schema, docs) | Nothing to auto-merge, but not blocked either — otherwise this repo's own CI could never be updated through a PR |
| **already-merged** | The head commit is already contained in the base branch, so the diff is empty | Nothing. Happens when a PR is merged by hand while the run is queued |
| **error** | The classifier itself crashed | Fail-closed: nothing merges and `classify` goes red with the reason |

Note that `invalid` exits non-zero on purpose. A job that merely goes red does **not** stop
branch protection unless it is a required check — and a *skipped* required check counts as
passing — so every blocking outcome has to come out of `classify` itself.

The intent is two-fold: **each mod's own maintainer(s) self-serve their whole folder** without
bothering you, while **nobody can change a mod they don't own**. You only see the PRs that
genuinely need a human decision (new mods, and outside proposals to someone else's mod).

### Ownership — who can change a mod

A mod's owners are the GitHub usernames in its `maintainers` array (in `mods/<id>/mod.json`),
plus the repo-wide maintainers hard-coded in `classify_pr.py` (`REPO_MAINTAINERS`). The
classifier reads `maintainers` from **the exact commit the PR targets**
(`github.event.pull_request.base.sha`), never the PR's own copy, so a PR can't authorize itself.
Pinning to that SHA rather than to the live `origin/main` tip also matters when a PR is merged by
hand while its run is queued: at that moment `origin/main` *is* the PR content, so reading the tip
would read `maintainers` straight out of the PR. An owner has **full autonomy over their folder** —
even the download URLs and
executable (`install.*` / `update.*`) auto-merge, still gated by schema + image validation.

- **This is a deliberate trust grant.** Giving a modder auto-merge over `install`/`update` means:
  if their account is compromised or they act in bad faith, they can publish what runs on their
  users' machines with no human in the loop. Only add someone to a mod's `maintainers` if you
  trust them with that mod.
- **To onboard a modder:** their first submission is `tier3` (you review it); when you accept it,
  add their username to that mod's `maintainers`. Changing `maintainers` is itself a critical
  (tier3) field, so an outsider can never self-grant ownership.
- **Ownership is per-mod and folder-scoped.** A maintainer of `wol` can't touch any other mod (a
  PR touching two mods is `invalid`).

---

## One-time setup checklist

After copying this folder into a new repo:

### 1. Create the repo
- Make it public (so the launcher can pull `mod.json` files via `raw.githubusercontent.com` without auth).
- Initialise with the contents of this template.

### 2. Branch protection on `main`
Settings → Branches → Add rule for `main`:
- ✅ **Require a pull request before merging**
- ✅ **Require status checks to pass before merging**
  - Add the workflow job names as required checks (after the workflow runs once and registers them):
    - `Validate and auto-merge / Classify changes`
    - `Validate and auto-merge / Validate manifest and assets`
  - ⚠️ Do **not** add `Apply catalog PR decision / Apply decision`. It runs *after* those two
    checks and only in order to enable auto-merge; requiring it would deadlock the merge it exists
    to perform. At least one required check must exist, or `gh pr merge --auto` is rejected outright.
- ✅ **Require branches to be up to date before merging**
- ❌ **Require approvals** — set to **0** (the workflow gates merges via required status checks instead, so manual approval isn't needed for tier1/2)
- ✅ **Restrict who can push to matching branches** — only your account
- ✅ **Do not allow bypassing the above settings** — even you go through PRs

### 3. Allow auto-merge
Settings → General → Pull Requests → ✅ **Allow auto-merge**.

### 4. Allow Actions to manage PRs
Settings → Actions → General → **Workflow permissions**:
- ✅ **Read and write permissions** (or scope to what `permissions:` already declares in the yml)
- ✅ **Allow GitHub Actions to create and approve pull requests** — needed so the workflow can comment / label

**Modders contributing from a fork is already handled — leave the fork write-token toggle OFF.**

Under `pull_request`, GitHub forces `GITHUB_TOKEN` to read-only on any PR from a fork, whatever
`permissions:` says. That is why the gate is split in two:

| Workflow | Trigger | Token | Runs PR code? |
|---|---|---|---|
| `auto-merge.yml` | `pull_request` | read-only | yes (`validate`) |
| `auto-merge-apply.yml` | `workflow_run` | writable | **never** |

`workflow_run` workflows are always taken from the **default branch** and get a writable token even
for a fork PR, so the second one can merge, label and comment. It reads the decision the first one
recorded as an artifact, treats every value in it as untrusted, and re-checks that the PR is still
open at the same head commit before acting.

Do **not** enable **Settings → Actions → General → Fork pull request workflows → "Send write tokens
to workflows from fork pull requests"**. It hands a write token to a run triggered by any fork PR
from anyone on the internet, and write access to this repo means publishing an
`install.payloadUrls` that the launcher downloads and executes on users' machines. The split above
achieves the same result without that exposure.

(Adding a modder as a repo collaborator also works — their PRs then come from in-repo branches with
a writable token — but it grants far more than auto-merging their own mod folder.)

### 5. Ownership is enforced by the classifier — `CODEOWNERS` is optional

Per-mod ownership is enforced **in `classify_pr.py`** via each mod's `maintainers` array (see
"Ownership" above), NOT by `CODEOWNERS`. In this setup `CODEOWNERS` would be **cosmetic**: branch
protection has **Required approvals = 0** and no "Require review from Code Owners", so a
`CODEOWNERS` entry assigns a reviewer but blocks nothing — and requiring code-owner review would
break self-serve anyway (a modder can't approve their own PR). So ownership lives in `maintainers`.

You *may* still add a `.github/CODEOWNERS` purely to auto-request yourself as a reviewer on
sensitive paths (advisory only):

```
# Advisory only — assigns a reviewer, does NOT gate the merge (approvals = 0).
# Real per-mod ownership is the `maintainers` array in each mod.json.
*                          @your-username
```

### 6. `CONTRIBUTING.md` for modders — already written
[`CONTRIBUTING.md`](CONTRIBUTING.md) covers the folder structure, the gate's rules, the manifest
constraints (including **save `mod.json` as UTF-8 without a BOM**), the image specs and the local
validation commands. Keep its image table in sync with `validate_images.py`, which is the single
source of truth. For reference, the specs it documents are:
- The folder structure (`mods/<id>/{mod.json, icon.png, banner.png, hero.jpg}`)
- The image specs:
  - **icon.png** — square (1:1), width 256–1024 px, PNG with alpha, ≤1 MB. Used in the Workshop tile.
  - **banner.png/jpg** — 4:1 aspect, width 1200–4800 px (e.g. 1200×300, 2400×600, 4800×1200), PNG/JPG, ≤2 MB. Used in the Workshop mod card (horizontal thumbnail). Declared in mod.json as `"banner": "banner.jpg"`.
  - **hero.png/jpg** — 16:9 aspect, width 1920–3840 px (1080p up to 4K), PNG/JPG, ≤5 MB (use JPEG for 4K — a 4K PNG can be 10 MB+). Used as the dashboard background painted behind the title + PLAY button. Important subject on the RIGHT half (the left half is covered by the title and PLAY button). Declared in mod.json as `"heroImage": "hero.jpg"`.
  - **heroImages** (rotating) — 2–6 hero images that cycle with a crossfade on the dashboard (~7 s each). Each follows the same spec as the single hero. Declared in mod.json as `"heroImages": ["hero1.jpg", "hero2.jpg", ...]` (takes precedence over `heroImage`).
- The schema URL to point their editor at
- That cosmetic and release-bump PRs auto-merge

The validation workflow + schema make this template enforce most of the rules automatically; CONTRIBUTING.md is mostly for ergonomics.

---

## How the auto-merge logic works (sequence)

```
PR opened/updated
       │
       ▼   ══ auto-merge.yml — `pull_request`, READ-ONLY token ══════════════
┌────────────────┐
│   classify     │   git diff base.sha...head.sha, + who the author is
│ (Python script)│   writes the decision to an artifact
└──────┬─────────┘
       │
       ├─── invalid / unauthorized / error ─▶ classify exits 1
       │       (required check red) ─▶ branch protection blocks the merge
       │
       ├─── infra / already-merged ─▶ nothing to do, checks stay green
       ▼
┌────────────────┐
│   validate     │   ajv validate + Pillow image checks
└──────┬─────────┘   (schema + validators pinned to the base branch)
       │   (runs for owner / tier3)
       ▼
       ═══ auto-merge-apply.yml — `workflow_run`, WRITABLE token ════════════
       │   reads the artifact, re-checks the PR is open at the same head SHA
   ┌───┴───────────────────────┐
   │                           │
owner                          tier3
   │                           │
   ▼                           ▼
 gh pr merge --auto        label + comment
   │                           │
 status checks pass            (you approve manually)
   │                           │
 PR squash-merges              ▼
                        you click merge
```

Every block is guaranteed by **`classify` being a required check**: the script `exit 1`s, so the
check goes red and branch protection stops the merge for everyone (fork or collaborator), with no
extra branch-protection config. Nothing relies on a non-required job going red, because branch
protection ignores those — and it treats a *skipped* required check as passing.

If any step fails, the PR stays open with status checks red. The author can push fixes; the workflow re-runs from scratch on the new diff.

---

## Tweaking the tier rules

The single source of truth for what counts as tier 1/2/3 is at the top of `.github/scripts/classify_pr.py`:

```python
TIER_1_FIELDS = {"displayName", "subtitle", "description", "accentColor",
                 "author", "officialWebsite", "icon", "banner", "heroImage",
                 "screenshots"}
TIER_2_FIELDS = {"approvedReleaseTag"}
TIER_3_FIELDS = {"id", "sourceRepo", "install", "update", "translations",
                 "maintainers"}

# GitHub logins with repo-wide authority over every mod (the repo owner(s)):
REPO_MAINTAINERS = {"gorgorito12"}
```

The field tiers now decide the outcome only **for a non-owner** (cosmetic/release → blocked as
`unauthorized`; critical/unknown → `tier3` review). An **owner** auto-merges any field. `maintainers`
is in tier 3 so an outsider can't self-grant ownership.

**Be conservative when reclassifying down (3 → 2 or 2 → 1).** Anything that controls what the launcher executes or downloads must stay in tier 3 — that's the security boundary for non-owners.

Adding new schema fields? Add them to one of the three sets here, otherwise the script falls through and labels a non-owner's PR tier 3 (safe default). To grant a modder auto-merge over their mod, add their username to that mod's `maintainers` (not here — `REPO_MAINTAINERS` is repo-wide).

---

## Limitations / caveats

- **The workflow doesn't approve PRs.** It enables auto-merge; the actual merge happens because branch protection requires status checks (not approvals). If you DO want approvals required, you'll need a separate bot account or a GitHub App, since `GITHUB_TOKEN` cannot approve PRs by design.
- **First-time mod submissions are always tier 3.** The script forces this regardless of what fields the manifest declares — a maintainer must vet new authors. After the first merge, add the author to that mod's `maintainers` so their later PRs classify as `owner` (auto-merge).
- **Owner autonomy includes download URLs.** By design, a mod's maintainer auto-merges `install`/`update` changes. Schema + image validation still run, but there is no human review of the payload URLs a trusted owner ships — that's the accepted trade-off of self-serve. Grant `maintainers` only to people you trust with that mod.
- **Never merge a catalog PR by hand.** It defeats the gate, and if the merge lands while the run is still queued the classifier sees an empty diff and reports `already-merged` — the checks never actually judged the change. If a PR needs to go in and the gate won't pass it, fix the cause (usually the manifest) rather than clicking merge.
- **The classifier and the validators run from the base branch.** The workflow pins `classify_pr.py`, `validate_images.py` and `schema/mod.schema.json` to the base ref before running them, so a fork PR can't rewrite the classifier to bypass the ownership check, nor ship a permissive schema alongside its own manifest.
- **The diff is taken with `--no-renames`, deliberately.** With git's default rename detection on, moving `mods/old/` to `mods/new/` reports only the *new* paths — so a rename looked like a brand-new mod and auto-merged for a repo maintainer, silently skipping the "delisting needs review" rule. Worse, whether it did depended on git's 50% similarity heuristic, so the same PR could classify `owner` or `invalid` depending on how much the manifest changed. `classify_rename` now recognises a rename explicitly, always sends it to `tier3`, and **refuses one that does not declare `previousIds`**.
- **Manifests must be saved as UTF-8 *without* a BOM.** A leading `U+FEFF` makes `json.loads` reject the file, which makes the classifier read an empty `maintainers` set (fail-closed) and quietly locks that mod's real owners out of auto-merge. The scripts now decode with `utf-8-sig` so a stray BOM is tolerated, but don't add one.
- **The classifier reads the diff, not the contents of the new mod.json alone.** A PR that only changes `accentColor` from `#ff0000` to `#ff0001` is tier 1; a PR that "rewrites" the same `accentColor` value (no actual change) doesn't trigger anything. This matters because some clients write a no-op diff when the file is touched but content is unchanged — those are no-ops by construction.
- **Image validation is strict on dimensions.** A 257×257 icon fails. If you want to allow tolerance (e.g. ±2 px), edit `validate_images.py`.
