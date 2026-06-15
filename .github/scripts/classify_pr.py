"""
Classify a pull request's changes into tier1 / tier2 / tier3 / invalid.

Tier semantics (set in stone — auto-merge logic depends on this):

  tier1  -> Cosmetic changes only. Auto-merge after schema + image validation.
            Examples: displayName, subtitle, description, accentColor, icon.png,
            banner.png. The user-visible parts of the mod, but nothing that
            changes what the launcher executes or downloads.

  tier2  -> approvedReleaseTag bump and nothing else of substance. Auto-merge
            after extra checks (the new tag exists, its mod.json still passes
            schema, etc.).

  tier3  -> Critical changes. Manual review required by a maintainer; the
            workflow only labels the PR and comments — no auto-merge.
            Examples: install.* fields, update.* URLs, sourceRepo change,
            id change, or any net-new mod submission.

  invalid -> Structural problems with the PR itself: files outside /mods/, more
             than one mod folder touched, malformed JSON. The workflow blocks
             the PR with an explanatory comment.

The workflow consumes the four output values written to GITHUB_OUTPUT:
  tier=<tier1|tier2|tier3|invalid>
  mod_id=<the single mod folder touched, or empty if invalid>
  reason=<short human-readable explanation>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# -------- Field categories ---------------------------------------------------

# Cosmetic-only fields. Changes to these are tier 1.
TIER_1_FIELDS = {
    "displayName",
    "subtitle",
    "description",
    "accentColor",
    "author",
    "officialWebsite",
    "icon",
    "banner",
    "heroImage",
    "screenshots",
}

# Release-pin fields. Changes to ONLY these are tier 2 (auto-merge with extra
# verification that the tag exists and its contents are still valid).
TIER_2_FIELDS = {"approvedReleaseTag"}

# Critical fields. Any change here forces tier 3 (manual review).
# These control what the launcher downloads and executes — they MUST NOT
# auto-merge under any circumstance.
TIER_3_FIELDS = {
    "id",
    "sourceRepo",
    "install",
    "update",
    "translations",
}

# Files allowed inside a mod folder. Anything else is suspicious enough to
# force manual review.
ALLOWED_ASSETS = {
    "icon.png",
    "banner.png", "banner.jpg", "banner.jpeg",
    "hero.png", "hero.jpg", "hero.jpeg",
    "mod.json",
    # Gallery screenshots use a FIXED naming convention (screenshot1..screenshot8)
    # so that asset-only screenshot PRs can auto-merge (tier1). Any other filename
    # falls through to tier3 (manual review) — a safe default for a security gate.
    *(f"screenshot{i}.{ext}"
      for i in range(1, 9)
      for ext in ("png", "jpg", "jpeg", "gif")),
}


# -------- Helpers ------------------------------------------------------------


def write_output(tier: str, mod_id: str, reason: str) -> None:
    """Emit GitHub Actions outputs and exit cleanly."""
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


# -------- Main classification ------------------------------------------------


def main() -> int:
    base_ref = os.environ["BASE_REF"]
    head_sha = os.environ["HEAD_SHA"]

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

    # If the mod.json itself wasn't changed, the PR is asset-only — tier 1.
    mod_json_path = f"mods/{mod_id}/mod.json"
    json_was_touched = any(str(f) == mod_json_path for f in files)

    if not json_was_touched:
        write_output(
            "tier1",
            mod_id,
            "Asset-only changes (icon and/or banner). Manifest unchanged.",
        )
        return 0

    # The mod.json was touched — diff its content to decide tier 1/2/3.
    old_text = file_at_revision(f"origin/{base_ref}", mod_json_path)
    new_text = Path(mod_json_path).read_text(encoding="utf-8")

    if old_text is None:
        # Brand-new mod submission. Always tier 3 (the maintainer must vet
        # any first-time submission, regardless of what the manifest says).
        write_output(
            "tier3",
            mod_id,
            "New mod submission — first-time review required by a maintainer.",
        )
        return 0

    try:
        old_json = json.loads(old_text)
        new_json = json.loads(new_text)
    except json.JSONDecodeError as e:
        write_output("tier3", mod_id, f"Invalid JSON in mod.json: {e}")
        return 0

    # Compare top-level keys.
    changed = diff_keys(old_json, new_json)

    # tier3 trumps everything: any critical field change demands manual review.
    critical_changed = changed & TIER_3_FIELDS
    if critical_changed:
        write_output(
            "tier3",
            mod_id,
            f"Critical fields changed: {sorted(critical_changed)}",
        )
        return 0

    # tier2: only the release tag bumped (and nothing else of substance).
    # Any field that is neither tier1 nor tier2 falling here would be a
    # schema-allowed-but-unrecognised key — escalate to tier3 conservatively.
    unrecognised = changed - TIER_1_FIELDS - TIER_2_FIELDS
    if unrecognised:
        write_output(
            "tier3",
            mod_id,
            f"Unrecognised field changes: {sorted(unrecognised)}. "
            "Update classify_pr.py if this is a new field.",
        )
        return 0

    if changed & TIER_2_FIELDS:
        # tier2 — approvedReleaseTag changed. May also have tier1 cosmetic
        # changes alongside, that's fine.
        old_tag = old_json.get("approvedReleaseTag")
        new_tag = new_json.get("approvedReleaseTag")
        write_output(
            "tier2",
            mod_id,
            f"Release tag bumped: {old_tag!r} -> {new_tag!r}",
        )
        return 0

    # Otherwise: only tier1 fields changed.
    write_output(
        "tier1",
        mod_id,
        f"Cosmetic changes only: {sorted(changed)}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
