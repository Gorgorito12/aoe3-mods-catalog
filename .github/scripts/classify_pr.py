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

  owner        -> Change by an authorized maintainer of this mod (or a repo
                  maintainer). Auto-merge after validation, regardless of field.
  tier3        -> Manual review by a maintainer: a first-time mod submission, an
                  unrecognised file, or a NON-owner proposing a critical/unknown
                  field change. Labelled, never auto-merged.
  unauthorized -> A non-owner trying to change a mod's cosmetic/release fields.
                  The script exits non-zero so the required "Classify" check
                  fails and branch protection blocks the merge for everyone.
  invalid      -> Structural problems (files outside a single mods/<id>/, multiple
                  mods, no files). Blocked with an explanatory comment.

The other three GITHUB_OUTPUT values are `mod_id`, `reason`, and the process exit
code (0 for every outcome except `unauthorized`, which is 1).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
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
    """Run a git command, return stdout, raise on non-zero exit."""
    result = subprocess.run(
        ("git", *args), capture_output=True, text=True, check=True
    )
    return result.stdout


def changed_files(base_ref: str, head_sha: str) -> list[Path]:
    """List paths changed between origin/<base_ref> and the head commit."""
    output = git("diff", "--name-only", f"origin/{base_ref}...{head_sha}")
    return [Path(line) for line in output.strip().splitlines() if line]


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


# -------- Main classification ------------------------------------------------


def main() -> int:
    base_ref = os.environ["BASE_REF"]
    head_sha = os.environ["HEAD_SHA"]
    pr_author = os.environ.get("PR_AUTHOR", "")

    files = changed_files(base_ref, head_sha)
    if not files:
        write_output("invalid", "", "PR has no changed files")
        return 0

    # Constraint 1: every changed path must live under mods/<single-id>/.
    # This catches the common abuse vectors of touching workflows, schema, or
    # multiple mods at once.
    mod_folders: set[str] = set()
    for f in files:
        parts = f.parts
        if len(parts) < 3 or parts[0] != "mods":
            write_output(
                "invalid",
                "",
                f"File outside mods/<id>/: {f}. PRs may only touch a single mod folder.",
            )
            return 0
        mod_folders.add(parts[1])

    if len(mod_folders) > 1:
        write_output(
            "invalid",
            "",
            f"PR touches multiple mod folders: {sorted(mod_folders)}. "
            "Open one PR per mod.",
        )
        return 0

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

    # Ownership: read the mod's maintainers from the BASE manifest (the state on
    # the target branch), NEVER the PR's own copy — a PR must not be able to
    # authorize itself by adding its author to `maintainers` (that change is a
    # tier3 field and, from a non-owner, lands in manual review below).
    base_text = file_at_revision(f"origin/{base_ref}", mod_json_path)
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
    new_text = Path(mod_json_path).read_text(encoding="utf-8")

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

    try:
        old_json = json.loads(base_text)
        new_json = json.loads(new_text)
    except json.JSONDecodeError as e:
        write_output("tier3", mod_id, f"Invalid JSON in mod.json: {e}")
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
    sys.exit(main())
