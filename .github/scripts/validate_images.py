"""
Validate that icon.png, banner, hero and screenshot images in every mod folder
meet the spec documented in CONTRIBUTING.md.

Dimensions are validated by ASPECT RATIO + a WIDTH RANGE (not a single exact
size), so any resolution up to 4K passes as long as the shape is right — e.g. a
hero can be 1920x1080, 2560x1440 or 3840x2160. File-weight caps are generous to
allow 4K source images (use JPEG for photographic 4K — a 4K PNG can be 10 MB+).

Specs (kept here as the single source of truth — keep CONTRIBUTING.md in sync):

  icon.png   (REQUIRED if the mod.json declares "icon")
    - PNG with alpha channel
    - square (1:1), width 256-1024 px
    - <= 1 MB on disk

  banner.png/banner.jpg   (OPTIONAL)
    - PNG or JPEG
    - 4:1 aspect, width 1200-4800 px (e.g. 1200x300, 2400x600, 4800x1200)
    - <= 2 MB on disk
    - Use case: horizontal mod card thumbnail in the Workshop browser

  hero.png/hero.jpg   (OPTIONAL — declared as "heroImage")
  heroImages[]        (OPTIONAL — rotating dashboard heroes; each same spec)
    - PNG or JPEG
    - 16:9 aspect, width 1920-3840 px (1080p up to 4K)
    - <= 5 MB on disk each
    - Use case: large background image painted behind the title + PLAY button
      on the launcher's dashboard panel. When "heroImages" lists 2+, the
      dashboard rotates through them with a crossfade.
    - Composition tip: keep the important subject on the RIGHT half; the left
      half is covered by the title and PLAY button.

  screenshots[]   (OPTIONAL — gallery shown in the Workshop detail panel)
    - PNG, JPEG or GIF (animated GIFs allowed HERE ONLY)
    - NO fixed dimensions (captures vary)
    - <= 5 MB on disk each
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


# Dimension/weight specs.
# (target_aspect, min_width, max_width, aspect_tolerance, max_bytes, formats, needs_alpha)
ICON_SPEC = (1.0, 256, 1024, 0.02, 1 * 1024 * 1024, {"PNG"}, True)
BANNER_SPEC = (4.0, 1200, 4800, 0.03, 2 * 1024 * 1024, {"PNG", "JPEG"}, False)
HERO_SPEC = (16 / 9, 1920, 3840, 0.03, 5 * 1024 * 1024, {"PNG", "JPEG"}, False)

# Screenshots have NO fixed dimensions; only a size cap + format check.
SCREENSHOT_MAX_BYTES = 5 * 1024 * 1024
SCREENSHOT_FORMATS = {"PNG", "JPEG", "GIF"}

# Rotating-hero gallery cap (must match the launcher's MaxHeroes).
MAX_HEROES = 6


def check_image(path: Path, spec) -> list[str]:
    """Validate one image against an (aspect + width range + weight + format) spec.

    Returns a list of human-readable error strings (empty list = pass).
    """
    target_aspect, min_w, max_w, tol, max_bytes, formats, needs_alpha = spec
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

    width, height = img.size
    if not (min_w <= width <= max_w):
        errors.append(
            f"{path}: width {width}px outside allowed range {min_w}-{max_w}px"
        )
    if height <= 0 or abs((width / height) - target_aspect) / target_aspect > tol:
        example_h = round(min_w / target_aspect)
        errors.append(
            f"{path}: dimensions {width}x{height} (aspect {width / max(height, 1):.3f}) "
            f"not within {tol * 100:.0f}% of {target_aspect:.3f} "
            f"(e.g. {min_w}x{example_h})"
        )

    # Icons are rendered against a dark background — the mod looks broken
    # without transparency. Catch this up front rather than at runtime.
    if needs_alpha and "A" not in img.getbands():
        errors.append(f"{path}: PNG must have an alpha channel for transparency")

    return errors


def check_icon(path: Path) -> list[str]:
    return check_image(path, ICON_SPEC)


def check_banner(path: Path) -> list[str]:
    return check_image(path, BANNER_SPEC)


def check_hero(path: Path) -> list[str]:
    """Validate a dashboard hero background image (single or one of heroImages[])."""
    return check_image(path, HERO_SPEC)


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

        # Hero image: optional single.
        hero_name = manifest.get("heroImage")
        if hero_name:
            hero_path = mod_dir / hero_name
            if not hero_path.exists():
                all_errors.append(
                    f"{manifest_path}: declares heroImage {hero_name!r} but file is missing"
                )
            else:
                all_errors.extend(check_hero(hero_path))

        # Hero images: optional rotating gallery (each same spec as heroImage).
        hero_list = manifest.get("heroImages") or []
        if len(hero_list) > MAX_HEROES:
            all_errors.append(
                f"{manifest_path}: heroImages has {len(hero_list)} entries; max is {MAX_HEROES}"
            )
        for hero_name in hero_list[:MAX_HEROES]:
            hero_path = mod_dir / hero_name
            if not hero_path.exists():
                all_errors.append(
                    f"{manifest_path}: declares heroImages entry {hero_name!r} but file is missing"
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
