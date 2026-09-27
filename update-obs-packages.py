#!/usr/bin/env python3
"""Regenerate the static package lists in the desktop-specific OBS recipes."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
RECIPES = {
    "gnome": REPO_ROOT / "mkosi.obs" / "gnome.conf",
    "kde": REPO_ROOT / "mkosi.obs" / "kde.conf",
}
IMAGES = {
    "gnome": ("base", "default-initrd", "GNOME"),
    "kde": ("base", "default-initrd", "KDE"),
}
PACKAGE_FIELDS = ("Packages", "BuildPackages", "InitrdPackages")
# Required by the host-side mkosi tooling in OBS, not installed into an image.
EXTRA_PACKAGES = {"python3-pefile"}


def load_summary() -> dict[str, dict]:
    env = os.environ.copy()
    env["PATH"] = f"{env.get('PATH', '')}:/usr/sbin"
    output = subprocess.run(
        ["mkosi", "--architecture=x86-64", "summary", "--json"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {image["Image"]: image for image in json.loads(output)["Images"]}


def packages_for(summary: dict[str, dict], flavor: str) -> list[str]:
    missing = set(IMAGES[flavor]) - summary.keys()
    if missing:
        sys.exit(f"Missing mkosi images for {flavor}: {', '.join(sorted(missing))}")

    packages = set(EXTRA_PACKAGES)
    for name in IMAGES[flavor]:
        image = summary[name]
        for field in PACKAGE_FIELDS:
            packages.update(image.get(field, []))
    return sorted(packages, key=str.casefold)


def render_recipe(path: Path, packages: list[str]) -> str:
    current = path.read_text()
    package_block = "Packages=\n" + "".join(f"    {package}\n" for package in packages)
    updated, count = re.subn(
        r"^Packages=.*\n(?:(?:[ \t]+.*|#.*)\n)*",
        package_block,
        current,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        sys.exit(f"Could not find exactly one Packages= block in {path}")
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if a recipe's generated package list is not current",
    )
    args = parser.parse_args()

    summary = load_summary()
    stale = False
    for flavor, recipe in RECIPES.items():
        packages = packages_for(summary, flavor)
        rendered = render_recipe(recipe, packages)
        if rendered == recipe.read_text():
            print(f"{recipe.relative_to(REPO_ROOT)} is current ({len(packages)} packages)")
            continue
        if args.check:
            print(f"{recipe.relative_to(REPO_ROOT)} needs regeneration", file=sys.stderr)
            stale = True
        else:
            recipe.write_text(rendered)
            print(f"Updated {recipe.relative_to(REPO_ROOT)} with {len(packages)} packages")

    if stale:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
