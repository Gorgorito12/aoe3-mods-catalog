"""
Classify a pull request's changes into an OUTCOME the auto-merge workflow acts on.

Two questions decide the outcome: WHAT changed (the field tiers below) and WHO is
making the change (per-mod ownership). Ownership is the security boundary that
scopes auto-merge to a mod's own maintainers.

Field tiers (what changed):

  tier1  -> Cosmetic fields only (displayName, description, accentColor, icon,
            banner, hero, screenshots, ...). The user-visible parts of a mod.
  tier2  -> approvedReleaseTag bump and nothing else of substance.
  tier3  -> Critical fields (install.*, update.*, sourceRepo, id, translations,
            maintainers): what the launcher downloads/executes, or who owns the
            mod. MUST NOT auto-merge from a non-owner.

Ownership (who is changing it):

  A mod's `maintainers` array (GitHub logins, read from the BASE manifest — never
  the PR's own copy) plus the repo-wide REPO_MAINTAINERS list decide authority.
  An authorized author has FULL autonomy over THEIR mod folder — every field,
  including install/update — auto-merges (still gated by schema + image
  validation downstream). This is a deliberate trust grant the repo owner makes
  per mod by adding a login to that mod's `maintainers` (itself a reviewed
  change). A non-owner can NOT auto-merge cosmetic changes to a mod they don't
  own (that path is blocked).

Outcomes written to GITHUB_OUTPUT as `tier` (the workflow keys off these):

  owner          -> Change by an authorized maintainer of this mod (or a repo
                    maintainer). Auto-merge after validation, regardless of field.
  tier3          -> Manual review by a maintainer: a first-time mod submission, an
                    unrecognised file, a deleted manifest, a folder RENAME (see
                    classify_rename), unparseable JSON, or a NON-owner proposing a
                    critical/unknown field change. Labelled, never auto-merged.
  unauthorized   -> A non-owner trying to change a mod's cosmetic/release fields.
                    The script exits non-zero so the required "Classify" check
                    fails and branch protection blocks the merge for everyone.
  invalid        -> Structural problems (files outside a single mods/<id>/,
                    multiple mods, a genuinely empty diff). Also exits non-zero:
                    the `block` job's red X is NOT a required check, so returning 0
                    here would leave the merge unblocked.
  infra          -> A repo-wide maintainer changing repo infrastructure only
                    (workflows, scripts, schema, docs). Nothing to auto-merge, but
                    not blocked either — otherwise the repo's own CI and docs could
                    never be updated through a PR. Matches no job.
  already-merged -> The head commit is already contained in the base branch, so the
                    diff is empty. Happens when a PR is merged by hand while this
                    run is queued. Matches no job; the run stays green and silent.
  error          -> The classifier itself crashed. Fail-closed: matches no job and
                    exits non-zero.

BASE_SHA (github.event.pull_request.base.sha) pins both the diff and the ownership
read to the commit the PR targets. Without it a hand-merge landing mid-run makes
origin/<base> BE the PR content: the diff empties out and `maintainers` would be
read from the PR's own copy. It is optional locally and falls back to origin/<base>.

The other GITHUB_OUTPUT values are `mod_id` and `reason`. Exit code is 0 for
`owner`, `tier3`, `infra` and `already-merged`; 1 for `unauthorized`, `invalid`
and `error`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

# -------- Field categories ---------------------------------------------------

# Cosmetic-only fields. Changes to these (from an owner) are cosmetic.
TIER_1_FIELDS = {
    "displayName",
    "subtitle",
    "description",
    "accentColor",
    "author",
    "officialWebsite",
    # Community links (Discord / ModDB / forum / …). Cosmetic: the launcher only
    # opens them in a browser. The ownership gate is what keeps them honest — a
    # non-owner editing this array is blocked, same as any other tier1 field.
    "links",
    "icon",
    "banner",
    "heroImage",
    "screenshots",
}

# Release-pin field. A change to ONLY this is a version bump.
TIER_2_FIELDS = {"approvedReleaseTag"}

# Critical fields. These control what the launcher downloads and executes, or WHO
# owns the mod (`maintainers`). A non-owner changing any of these needs manual
# review; they MUST NOT auto-merge from a non-owner under any circumstance.
TIER_3_FIELDS = {
    "id",
    # Which EXISTING installation a manifest may adopt. A mod declaring another
    # mod's id here would inherit that mod's install folder and saved install path
    # on every user's machine, so it is exactly as critical as `id` itself.
    "previousIds",
    "sourceRepo",
    "install",
    "update",
    "translations",
    "maintainers",
}

# GitHub logins (lowercased) with repo-wide authority over EVERY mod. The repo
# owner(s). A login here is authorized for any mod folder, in addition to each
# mod's own `maintainers` list.
REPO_MAINTAINERS = {"gorgorito12"}

# Files allowed inside a mod folder. Anything else is suspicious enough to force
# manual review (kept even for owners — adding an unrecognised file isn't
# "editing your mod", it's a safety-net escalation).
ALLOWED_ASSETS = {
    "icon.png",
    "banner.png", "banner.jpg", "banner.jpeg",
    "hero.png", "hero.jpg", "hero.jpeg",
    "mod.json",
    # Gallery screenshots use a FIXED naming convention (screenshot1..screenshot8)
    # so that asset-only screenshot PRs can auto-merge. Any other filename falls
    # through to tier3 (manual review) — a safe default for a security gate.
    *(f"screenshot{i}.{ext}"
      for i in range(1, 9)
      for ext in ("png", "jpg", "jpeg", "gif")),
}


# -------- Helpers ------------------------------------------------------------


def write_output(tier: str, mod_id: str, reason: str) -> None:
    """Emit GitHub Actions outputs."""
    print(f"::notice::tier={tier} mod_id={mod_id} reason={reason}")
    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(f"tier={tier}\n")
            f.write(f"mod_id={mod_id}\n")
            # Reasons can contain newlines; collapse for the single-line output.
            f.write(f"reason={reason.replace(chr(10), ' | ')}\n")


def git(*args: str) -> str:
    """
    Run a git command, return stdout, raise on non-zero exit.

    Decoded explicitly as utf-8-sig instead of relying on `text=True`. `text=True`
    decodes with the LOCALE encoding (cp1252 on a Windows checkout, which mangles
    the non-ASCII descriptions on a local run) and it leaves a UTF-8 BOM in place
    as U+FEFF, which makes `json.loads` reject an otherwise perfectly valid
    manifest — and `read_maintainers` fail closed, silently voiding ownership.
    """
    result = subprocess.run(("git", *args), capture_output=True, check=True)
    return result.stdout.decode("utf-8-sig", errors="replace")


def git_succeeds(*args: str) -> bool:
    """Run a git command for its exit status only (no output, never raises)."""
    return subprocess.run(("git", *args), capture_output=True).returncode == 0


def changed_files(
    base_rev: str, head_sha: str, diff_filter: str | None = None
) -> list[Path]:
    """
    List paths changed between the base revision and the head commit.

    `--no-renames` is not a detail. With git's default rename detection ON, moving
    `mods/old/` to `mods/new/` reports ONLY the three new paths — so the diff looks
    like a single folder, the classifier sees a brand-new mod, and a repo maintainer's
    rename auto-merges as a first-time submission. That silently bypasses the
    delisting review below, and whether it happens at all depends on git's 50%
    similarity heuristic: edit the manifest a little more and the same PR flips to
    `invalid` instead. A security gate whose verdict turns on a heuristic is not one.
    """
    args = ["diff", "--no-renames", "--name-only"]
    if diff_filter:
        args.append(f"--diff-filter={diff_filter}")
    args.append(f"{base_rev}...{head_sha}")
    output = git(*args)
    return [Path(line) for line in output.strip().splitlines() if line]


def tree_is_empty(rev: str, folder: str) -> bool:
    """True when `folder` holds no tracked files at `rev`."""
    return not git("ls-tree", "-r", "--name-only", rev, "--", folder).strip()


def file_at_revision(rev: str, path: str) -> str | None:
    """Read a file's content at a specific git revision; None if it didn't exist."""
    try:
        return git("show", f"{rev}:{path}")
    except subprocess.CalledProcessError:
        return None


def diff_keys(old: dict, new: dict) -> set[str]:
    """Return top-level keys whose values differ between old and new."""
    changed: set[str] = set()
    for key in set(old) | set(new):
        if old.get(key) != new.get(key):
            changed.add(key)
    return changed


def normalize_login(login: str | None) -> str:
    """GitHub logins are case-insensitive; compare lowercased + trimmed."""
    return (login or "").strip().lower()


def read_maintainers(mod_json_text: str | None) -> set[str]:
    """
    Parse a mod.json's `maintainers` array into a set of lowercased logins.
    Robust to a missing field or malformed JSON (returns an empty set → the
    authorization check fails closed, so only REPO_MAINTAINERS are trusted).
    """
    if not mod_json_text:
        return set()
    try:
        data = json.loads(mod_json_text)
    except json.JSONDecodeError:
        return set()
    result: set[str] = set()
    for m in data.get("maintainers", []) or []:
        if isinstance(m, str):
            result.add(normalize_login(m))
    return result


def is_authorized(pr_author: str, base_maintainers: set[str]) -> bool:
    """
    True if the PR author may auto-merge changes to this mod: they're a repo-wide
    maintainer, or listed in the mod's own (BASE) maintainers. Fail-closed on an
    empty/unknown author.
    """
    author = normalize_login(pr_author)
    if not author:
        return False
    return author in REPO_MAINTAINERS or author in base_maintainers


def classify_rename(
    base_rev: str,
    head_sha: str,
    files: list[Path],
    mod_folders: set[str],
    pr_author: str,
) -> int | None:
    """
    Recognise a mod-folder RENAME and classify it, or return None so the caller falls
    through to `invalid`.

    A rename is two mod folders at once, which the multi-folder guard would otherwise
    reject outright — but it is also a legitimate thing a maintainer occasionally has
    to do, and hard-blocking it means the only way through is an admin bypass of the
    whole gate. So it is recognised, and recognised STRICTLY: anything that is not an
    exact, complete move of one folder onto another falls through untouched.

    Never `owner`, always `tier3`, even for a repo maintainer. A rename is a delisting
    plus a relisting, and delisting already needs a human for the reason stated below:
    it breaks every launcher client that has the mod installed. What makes the rename
    survivable is `previousIds`, so that is REQUIRED here — this is the only place that
    can enforce it, and enforcing it is most of the point of recognising renames at all.
    """
    if len(mod_folders) != 2:
        return None

    deleted = {p.as_posix() for p in changed_files(base_rev, head_sha, diff_filter="D")}
    added = {p.as_posix() for p in changed_files(base_rev, head_sha, diff_filter="A")}

    old_id: str | None = None
    new_id: str | None = None
    for candidate in sorted(mod_folders):
        prefix = f"mods/{candidate}/"
        paths = {f.as_posix() for f in files if f.as_posix().startswith(prefix)}
        if not paths:
            return None
        if paths <= deleted and old_id is None:
            old_id = candidate
        elif paths <= added and new_id is None:
            new_id = candidate
        else:
            # A folder that is partly modified, or a second folder of the same kind:
            # not a move. Let the multi-folder guard have it.
            return None

    if old_id is None or new_id is None:
        return None

    # A rename that also smuggles in an unrecognised file is not a clean rename.
    if any(f.name not in ALLOWED_ASSETS for f in files):
        return None

    # The old folder must be GONE, not merely thinned out. Without this, "delete two of
    # three files from A while adding B" would read as a rename.
    if not tree_is_empty(head_sha, f"mods/{old_id}/"):
        return None

    old_base_text = file_at_revision(base_rev, f"mods/{old_id}/mod.json")
    if old_base_text is None:
        return None
    if file_at_revision(base_rev, f"mods/{new_id}/mod.json") is not None:
        # The destination already exists on the base branch — this is a merge of one
        # mod into another, not a rename. Far beyond what a pattern match should bless.
        return None

    new_path = Path(f"mods/{new_id}/mod.json")
    if not new_path.exists():
        return None

    try:
        old_json = json.loads(old_base_text)
        new_json = json.loads(new_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None

    if old_json.get("id") != old_id or new_json.get("id") != new_id:
        return None

    previous_ids = new_json.get("previousIds") or []
    if not isinstance(previous_ids, list) or old_id not in previous_ids:
        write_output(
            "invalid",
            new_id,
            f"Renaming '{old_id}' to '{new_id}' without listing '{old_id}' in the new "
            "manifest's `previousIds`. Every user who already installed this mod has "
            "their install path filed under the old id, and their install folder is "
            "stamped with it — without `previousIds` the launcher cannot adopt either, "
            "so the rename silently orphans all of them.",
        )
        return 1

    # Ownership comes from the OLD folder's base manifest. The new folder has no base
    # copy at all, so reading its `maintainers` would let the PR authorize itself.
    if not is_authorized(pr_author, read_maintainers(old_base_text)):
        write_output(
            "unauthorized",
            new_id,
            f"@{pr_author} is not a maintainer of '{old_id}' and cannot rename it.",
        )
        return 1

    write_output(
        "tier3",
        new_id,
        f"Mod folder rename '{old_id}' -> '{new_id}' by @{pr_author}, declaring "
        f"previousIds={previous_ids}. A rename delists the old id for every installed "
        "client, so it is reviewed even from an owner.",
    )
    return 0


# -------- Main classification ------------------------------------------------


def main() -> int:
    base_ref = os.environ["BASE_REF"]
    head_sha = os.environ["HEAD_SHA"]
    pr_author = os.environ.get("PR_AUTHOR", "")
    # The commit the PR was opened against (github.event.pull_request.base.sha).
    # Pinning to it — rather than to the live origin/<base_ref> tip — is what makes
    # this immune to the base branch moving mid-run. If the PR is merged while this
    # job is queued, origin/<base_ref> BECOMES the PR content: the diff comes back
    # empty AND `maintainers` would be read from the PR's own copy, silently voiding
    # the ownership gate. Falls back to the tip so local runs work without it.
    base_sha = os.environ.get("BASE_SHA", "").strip()
    base_rev = base_sha or f"origin/{base_ref}"

    files = changed_files(base_rev, head_sha)
    if not files:
        # An empty diff almost always means the head is already contained in the
        # base branch (the PR was merged or superseded while this run was queued),
        # not that someone opened a structurally broken PR. Say so honestly — no job
        # acts on `already-merged`, so the run stays green and posts no comment.
        if git_succeeds("merge-base", "--is-ancestor", head_sha, f"origin/{base_ref}"):
            write_output(
                "already-merged",
                "",
                f"PR head {head_sha[:8]} is already contained in '{base_ref}' — "
                "nothing to classify.",
            )
            return 0
        write_output("invalid", "", "PR has no changed files")
        return 1

    # Constraint 1: every changed path must live under mods/<single-id>/.
    # This catches the common abuse vectors of touching workflows, schema, or
    # multiple mods at once.
    outside = [f for f in files if len(f.parts) < 3 or f.parts[0] != "mods"]
    if outside:
        # Repo infrastructure (workflows, scripts, schema, docs) changed by a
        # repo-wide maintainer. That is not a catalog change, so there is nothing to
        # auto-merge — but it must not be hard-blocked either, or the repo's own CI
        # and documentation could never be updated through a PR. `infra` matches no
        # job: the required checks stay green and the maintainer merges normally.
        touches_mods = any(f.parts[0] == "mods" for f in files)
        if not touches_mods and normalize_login(pr_author) in REPO_MAINTAINERS:
            write_output(
                "infra",
                "",
                f"Repo infrastructure change by @{pr_author} "
                f"({len(files)} file(s) outside mods/). No auto-merge.",
            )
            return 0
        write_output(
            "invalid",
            "",
            f"File outside mods/<id>/: {outside[0].as_posix()}. "
            "PRs may only touch a single mod folder.",
        )
        return 1

    mod_folders = {f.parts[1] for f in files}

    # A rename is two folders at once, so it has to be recognised before the
    # multi-folder guard rejects it. Returns None for anything that is not an exact
    # move, which then falls through to that guard unchanged.
    rename_verdict = classify_rename(base_rev, head_sha, files, mod_folders, pr_author)
    if rename_verdict is not None:
        return rename_verdict

    if len(mod_folders) > 1:
        write_output(
            "invalid",
            "",
            f"PR touches multiple mod folders: {sorted(mod_folders)}. "
            "Open one PR per mod.",
        )
        return 1

    mod_id = next(iter(mod_folders))

    # Constraint 2: only known asset filenames are allowed inside the mod folder.
    # Kept as a tier3 safety net even for owners.
    for f in files:
        if f.name not in ALLOWED_ASSETS:
            write_output(
                "tier3",
                mod_id,
                f"Unknown file in mod folder: {f}. "
                "Only mod.json, icon.png, banner.png/jpg, hero.png/jpg and "
                "screenshot1..8.png/jpg/gif are recognised.",
            )
            return 0

    mod_json_path = f"mods/{mod_id}/mod.json"
    # Compare as POSIX so the check is separator-agnostic (git emits forward
    # slashes; Path.str() would use backslashes on Windows).
    json_was_touched = any(f.as_posix() == mod_json_path for f in files)

    # Ownership: read the mod's maintainers from the BASE manifest (`base_rev`, the
    # commit the PR targets), NEVER the PR's own copy — a PR must not be able to
    # authorize itself by adding its author to `maintainers` (that change is a
    # tier3 field and, from a non-owner, lands in manual review below).
    base_text = file_at_revision(base_rev, mod_json_path)
    base_maintainers = read_maintainers(base_text)
    authorized = is_authorized(pr_author, base_maintainers)

    # --- Asset-only PR (mod.json untouched) ---
    if not json_was_touched:
        if base_text is None:
            # Assets for a mod with no manifest on the base branch — odd; review.
            write_output(
                "tier3",
                mod_id,
                f"Assets for '{mod_id}' but no mod.json on the base branch — manual review.",
            )
            return 0
        if authorized:
            write_output(
                "owner",
                mod_id,
                f"Owner asset-only change to '{mod_id}'.",
            )
            return 0
        write_output(
            "unauthorized",
            mod_id,
            f"@{pr_author} is not a maintainer of '{mod_id}', so cannot change its assets.",
        )
        return 1

    # --- mod.json touched ---
    mod_json_file = Path(mod_json_path)
    if not mod_json_file.exists():
        # The PR deletes the manifest. Delisting a mod breaks every launcher client
        # that already has it installed — a different thing from editing your own
        # folder — so it needs a human even from an owner.
        write_output(
            "tier3",
            mod_id,
            f"mod.json for '{mod_id}' is being deleted — delisting a mod needs "
            "manual review.",
        )
        return 0
    try:
        new_text = mod_json_file.read_text(encoding="utf-8-sig")
    except OSError as e:
        write_output("tier3", mod_id, f"Could not read {mod_json_path}: {e}")
        return 0

    if base_text is None:
        # Brand-new mod submission.
        if normalize_login(pr_author) in REPO_MAINTAINERS:
            write_output("owner", mod_id, "New mod added by a repo maintainer.")
            return 0
        write_output(
            "tier3",
            mod_id,
            "New mod submission — first-time review required by a maintainer.",
        )
        return 0

    # Parse the two sides separately so the reason says WHICH manifest is broken.
    # A manifest that is already corrupt on the base branch is a repo-health alarm,
    # not a contributor's typo: it also makes `read_maintainers` fail closed above,
    # which silently denies the mod's real owners. Make that case loud.
    try:
        old_json = json.loads(base_text)
    except json.JSONDecodeError as e:
        print(
            f"::warning::The BASE copy of {mod_json_path} does not parse ({e}). "
            "Ownership cannot be established for this mod until it is repaired."
        )
        write_output(
            "tier3",
            mod_id,
            f"Invalid JSON in the BASE copy of mod.json: {e}. Ownership can't be "
            "established — repair the manifest on the base branch first.",
        )
        return 0

    try:
        new_json = json.loads(new_text)
    except json.JSONDecodeError as e:
        write_output("tier3", mod_id, f"Invalid JSON in the PR's mod.json: {e}")
        return 0

    changed = diff_keys(old_json, new_json)

    # Authorized owner: FULL autonomy over their own folder — any field, including
    # install/update. Still gated by schema + image validation downstream, so a
    # malformed manifest or an out-of-spec image can't merge.
    if authorized:
        fields = sorted(changed) or ["<no field change>"]
        write_output(
            "owner",
            mod_id,
            f"Owner change to '{mod_id}'. Fields: {fields}.",
        )
        return 0

    # --- Not authorized (the PR author does not own this mod) ---
    critical_changed = changed & TIER_3_FIELDS
    unrecognised = changed - TIER_1_FIELDS - TIER_2_FIELDS
    if critical_changed or unrecognised:
        # A substantive proposal from a non-owner — a maintainer decides. Not a
        # hard block: it might be a legitimate community fix.
        detail = sorted(critical_changed) or sorted(unrecognised)
        write_output(
            "tier3",
            mod_id,
            f"@{pr_author} is not a maintainer of '{mod_id}'; "
            f"critical/unknown fields {detail} need manual review.",
        )
        return 0

    # Only cosmetic/release fields changed, but from a non-owner → block. Nobody
    # edits someone else's mod's look & feel without being one of its maintainers.
    write_output(
        "unauthorized",
        mod_id,
        f"@{pr_author} is not a maintainer of '{mod_id}'. "
        f"Only its maintainers can change it — ask a maintainer to add you.",
    )
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — fail closed, never silently
        # Any unhandled error must STILL produce a `tier`. Without this the step
        # dies with a bare traceback and writes no output at all, leaving every
        # downstream job keying off an empty string. `error` matches no job, so
        # nothing merges and nothing is labelled, and the non-zero exit turns the
        # required `classify` check red with a readable reason attached.
        traceback.print_exc()
        write_output("error", "", f"Classifier failed: {type(exc).__name__}: {exc}")
        sys.exit(1)
