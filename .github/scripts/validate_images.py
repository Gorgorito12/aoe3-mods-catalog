"""
Validate that icon.png, banner.png and hero.png in every mod folder meet
the spec documented in CONTRIBUTING.md.

Specs (kept here as the single source of truth — keep CONTRIBUTING.md in sync):

  icon.png   (REQUIRED if the mod.json declares "icon")
    - PNG with alpha channel
    - exactly 256x256 px
    - <= 100 KB on disk

  banner.png/banner.jpg   (OPTIONAL)
    - PNG or JPEG
    - exactly 1200x300 px
    - <= 500 KB on disk
    - Use case: horizontal mod card thumbnail in the Workshop browser

  hero.png/hero.jpg   (OPTIONAL — declared as "heroImage")
    - PNG or JPEG
    - exactly 1920x1080 px
    - <= 2 MB on disk
    - Use case: large background image painted behind the title +
      PLAY button on the launcher's dashboard panel
    - Composition tip: keep the important subject on the RIGHT half;
      the left half is covered by the title and PLAY button

  screenshots[]   (OPTIONAL — gallery shown in the Workshop detail panel)
    - PNG, JPEG or GIF (animated GIFs allowed HERE ONLY)
    - NO fixed dimensions (captures vary)
    - <= 2 MB on disk each
    - The declared extension must match the actual format (a .gif file must
      really be a GIF, etc.)

Image specs are enforced strictly — the workflow fails the PR if anything is
out of spec, with a list of every violation across every changed asset.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image


# Dimension/weight specs. (width, height, max_bytes, allowed_formats)
ICON_SPEC = (256, 256, 100 * 1024, {"PNG"})
BANNER_SPEC = (1200, 300, 500 * 1024, {"PNG", "JPEG"})
HERO_SPEC = (1920, 1080, 2 * 1024 * 1024, {"PNG", "JPEG"})

# Screenshots have NO fixed dimensions; only a size cap + format check.
SCREENSHOT_MAX_BYTES = 2 * 1024 * 1024
SCREENSHOT_FORMATS = {"PNG", "JPEG", "GIF"}


def check_icon(path: Path) -> list[str]:
    """Return a list of human-readable error strings (empty list = pass)."""
    width, height, max_bytes, formats = ICON_SPEC
    errors: list[str] = []

    size = path.stat().st_size
    if size > max_bytes:
        errors.append(
            f"{path}: file size {size:,} bytes exceeds limit of {max_bytes:,}"
        )

    try:
        img = Image.open(path)
    except Exception as e:
        errors.append(f"{path}: cannot open image — {e}")
        return errors

    if img.format not in formats:
        errors.append(
            f"{path}: format {img.format!r} not in allowed {sorted(formats)}"
        )

    if img.size != (width, height):
        errors.append(
            f"{path}: dimensions {img.size} != required ({width}, {height})"
        )

    # Icons are rendered against a dark background — the mod looks broken
    # without transparency. Catch this up front rather than at runtime.
    if "A" not in img.getbands():
        errors.append(f"{path}: PNG must have an alpha channel for transparency")

    return errors


def check_banner(path: Path) -> list[str]:
    width, height, max_bytes, formats = BANNER_SPEC
    errors: list[str] = []

    size = path.stat().st_size
    if size > max_bytes:
        errors.append(
            f"{path}: file size {size:,} bytes exceeds limit of {max_bytes:,}"
        )

    try:
        img = Image.open(path)
    except Exception as e:
        errors.append(f"{path}: cannot open image — {e}")
        return errors

    if img.format not in formats:
        errors.append(
            f"{path}: format {img.format!r} not in allowed {sorted(formats)}"
        )

    if img.size != (width, height):
        errors.append(
            f"{path}: dimensions {img.size} != required ({width}, {height})"
        )

    return errors


def check_hero(path: Path) -> list[str]:
    """Validate the dashboard hero background image.

    Larger than the Workshop banner because it covers the entire hero
    panel of the launcher (~1920x900) rather than just a card thumbnail.
    """
    width, height, max_bytes, formats = HERO_SPEC
    errors: list[str] = []

    size = path.stat().st_size
    if size > max_bytes:
        errors.append(
            f"{path}: file size {size:,} bytes exceeds limit of {max_bytes:,}"
        )

    try:
        img = Image.open(path)
    except Exception as e:
        errors.append(f"{path}: cannot open image — {e}")
        return errors

    if img.format not in formats:
        errors.append(
            f"{path}: format {img.format!r} not in allowed {sorted(formats)}"
        )

    if img.size != (width, height):
        errors.append(
            f"{path}: dimensions {img.size} != required ({width}, {height})"
        )

    return errors


def check_screenshot(path: Path) -> list[str]:
    """Validate a gallery screenshot: size + format only (no dimensions).

    Animated GIFs are allowed. The file extension must match the real format so
    the launcher's gif-vs-static branch (by extension) is trustworthy.
    """
    errors: list[str] = []

    size = path.stat().st_size
    if size > SCREENSHOT_MAX_BYTES:
        errors.append(
            f"{path}: file size {size:,} bytes exceeds limit of {SCREENSHOT_MAX_BYTES:,}"
        )

    try:
        img = Image.open(path)
    except Exception as e:
        errors.append(f"{path}: cannot open image — {e}")
        return errors

    if img.format not in SCREENSHOT_FORMATS:
        errors.append(
            f"{path}: format {img.format!r} not in allowed {sorted(SCREENSHOT_FORMATS)}"
        )

    # Extension must match the actual format (.gif <-> GIF, .png <-> PNG, .jpg/.jpeg <-> JPEG).
    ext = path.suffix.lower()
    expected = {".gif": "GIF", ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}.get(ext)
    if expected and img.format and img.format != expected:
        errors.append(
            f"{path}: extension {ext!r} does not match actual format {img.format!r}"
        )

    return errors


def main() -> int:
    mods_root = Path("mods")
    if not mods_root.is_dir():
        print("No mods/ folder yet — nothing to validate.")
        return 0

    all_errors: list[str] = []

    for mod_dir in sorted(p for p in mods_root.iterdir() if p.is_dir()):
        manifest_path = mod_dir / "mod.json"
        if not manifest_path.exists():
            # Schema validation in the same workflow run catches this; here
            # we just skip so the report is focused on image issues.
            continue

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Likewise — leave the JSON parse error to the schema step.
            continue

        # Icon: required if declared.
        icon_name = manifest.get("icon")
        if icon_name:
            icon_path = mod_dir / icon_name
            if not icon_path.exists():
                all_errors.append(
                    f"{manifest_path}: declares icon {icon_name!r} but file is missing"
                )
            else:
                all_errors.extend(check_icon(icon_path))

        # Banner: optional.
        banner_name = manifest.get("banner")
        if banner_name:
            banner_path = mod_dir / banner_name
            if not banner_path.exists():
                all_errors.append(
                    f"{manifest_path}: declares banner {banner_name!r} but file is missing"
                )
            else:
                all_errors.extend(check_banner(banner_path))

        # Hero image: optional.
        hero_name = manifest.get("heroImage")
        if hero_name:
            hero_path = mod_dir / hero_name
            if not hero_path.exists():
                all_errors.append(
                    f"{manifest_path}: declares heroImage {hero_name!r} but file is missing"
                )
            else:
                all_errors.extend(check_hero(hero_path))

        # Screenshots: optional gallery (0..8 images/GIFs, no fixed dimensions).
        for shot_name in (manifest.get("screenshots") or []):
            shot_path = mod_dir / shot_name
            if not shot_path.exists():
                all_errors.append(
                    f"{manifest_path}: declares screenshot {shot_name!r} but file is missing"
                )
            else:
                all_errors.extend(check_screenshot(shot_path))

    if all_errors:
        print("Image validation FAILED — fix these issues:")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    print("All images pass spec validation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
