# aoe3-mods-catalog template

This folder is **scaffolding for a separate GitHub repo** — `papillo12/aoe3-mods-catalog` (or whatever you call it). It is not meant to live inside the launcher repo. Copy these files into a fresh repo when you're ready.

---

## What's inside

```
aoe3-mods-catalog-template/
├── .github/
│   ├── scripts/
│   │   ├── classify_pr.py          PR change classifier (tier1/2/3/invalid)
│   │   └── validate_images.py      Icon and banner spec checks
│   └── workflows/
│       └── auto-merge.yml          Orchestrates classify → validate → decide
└── schema/
    └── mod.schema.json             JSON Schema every mod.json is checked against
```

The workflow runs on every PR. It classifies the diff by **what changed** AND **who is
changing it** (per-mod ownership), and emits one of these outcomes:

| Outcome | When | Action |
|---|---|---|
| **owner** | The PR author is a maintainer of the mod it touches (or a repo-wide maintainer) — **any field, including `install`/`update`** | Auto-merge after schema + image validation passes |
| **tier3** | A first-time mod submission, an unknown file, or a **non-owner** proposing a critical/unknown-field change | Labelled `needs-manual-review`; you approve manually |
| **unauthorized** | A **non-owner** trying to change a mod's cosmetic/release fields | **Blocked** — the classify check fails, branch protection stops the merge |
| **invalid** | Files outside `/mods/`, multiple mods at once, or no files | Blocked with an explanatory comment |

The intent is two-fold: **each mod's own maintainer(s) self-serve their whole folder** without
bothering you, while **nobody can change a mod they don't own**. You only see the PRs that
genuinely need a human decision (new mods, and outside proposals to someone else's mod).

### Ownership — who can change a mod

A mod's owners are the GitHub usernames in its `maintainers` array (in `mods/<id>/mod.json`),
plus the repo-wide maintainers hard-coded in `classify_pr.py` (`REPO_MAINTAINERS`). The
classifier reads `maintainers` from the **base branch** (never the PR's own copy), so a PR can't
authorize itself. An owner has **full autonomy over their folder** — even the download URLs and
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

**If modders contribute from a fork** (the usual public model — they don't have write access),
also enable **Settings → Actions → General → Fork pull request workflows → "Send write tokens to
workflows from fork pull requests"**. Without it, `gh pr merge --auto` gets a read-only token on
fork PRs and the owner's auto-merge never completes (the PR just waits). The *ownership block*
works regardless of this setting; only the *auto-merge of an owner's* fork PR depends on it.
(Alternative: add the modder as a repo collaborator so they push a branch in-repo — but that's
broader access than a fork + this toggle.)

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

### 6. Add `CONTRIBUTING.md` for modders
A short doc telling them:
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
       ▼
┌────────────────┐
│   classify     │   git diff vs base
│ (Python script)│
└──────┬─────────┘
       │
       ├─── invalid ──────▶ comment + fail workflow ─▶ branch protection blocks merge
       │
       ├─── unauthorized ─▶ classify exits 1 (required check red) + comment
       │                    ─▶ branch protection blocks merge (non-owner)
       ▼
┌────────────────┐
│   validate     │   ajv validate + Pillow image checks
└──────┬─────────┘
       │   (runs for owner / tier3)
       ▼
   ┌───┴───────────────────────┐
   │                           │
owner ──▶ auto_merge           tier3 ──▶ request_review
   │                           │
   ▼                           ▼
 gh pr merge --auto        label + comment
   │                           │
 status checks pass            (you approve manually)
   │                           │
 PR squash-merges              ▼
                        you click merge
```

The `unauthorized` block is guaranteed because **`classify` is a required check**: the script
`exit 1`s, so the check goes red and branch protection stops the merge for everyone (fork or
collaborator), with no extra branch-protection config.

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
- **The classifier runs from the base branch.** The workflow pins `classify_pr.py` to the base ref before running it, so a fork PR can't rewrite the classifier to bypass the ownership check.
- **The classifier reads the diff, not the contents of the new mod.json alone.** A PR that only changes `accentColor` from `#ff0000` to `#ff0001` is tier 1; a PR that "rewrites" the same `accentColor` value (no actual change) doesn't trigger anything. This matters because some clients write a no-op diff when the file is touched but content is unchanged — those are no-ops by construction.
- **Image validation is strict on dimensions.** A 257×257 icon fails. If you want to allow tolerance (e.g. ±2 px), edit `validate_images.py`.
