"""Write a side-by-side saved-solid/feature-rebuild image for local checks.

    python tools/render_compare.py PARTS... [--out out/check-images] [--jobs 20]

Only a geometrically accepted rebuild with solid-making features is rendered. An imported solid
is never reused as the rebuild. Images are written below the ignored output folder, overwriting
older renders; private model names never leave the local output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def image_folder(part: str, out: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.splitext(os.path.basename(part))[0]).strip("._") or "part"
    digest = hashlib.sha256(os.path.abspath(part).encode("utf-8")).hexdigest()[:8]
    return os.path.join(out, f"{name}-{digest}")


def feature_rebuild(design) -> bool:
    """A design that builds its solid from features, not just the saved-solid import."""
    return isinstance(design, dict) and not design.get("pending") and any(
        isinstance(f, dict) and not f.get("suppressed") and f.get("type") in ("extrude", "revolve", "sweep")
        for f in design.get("features", []))


def discard_stale(part: str, out: str) -> None:
    try:
        os.remove(os.path.join(image_folder(part, out), "comparison.png"))
    except FileNotFoundError:
        pass


def render_part(part: str, out: str, built=None, reference=None, cli=None) -> str | None:
    sys.path.insert(0, ROOT)
    from sw2sc import features, solidcraft, verify
    from sw2sc.swfile import SwFile
    cli = cli or verify.find_cli()
    if not cli:
        discard_stale(part, out)
        return None
    if reference is None:
        reference, _ = solidcraft.convert(part, feature_tree=False)
    if built is None:
        built = verify.rebuild(features.read(SwFile(part)), reference, os.path.splitext(os.path.basename(part))[0], cli)
    if not feature_rebuild(built):
        discard_stale(part, out)
        return None
    folder = image_folder(part, out)
    os.makedirs(folder, exist_ok=True)
    saved = []
    for name, design in (("reference", reference), ("rebuilt", built)):
        design_path = os.path.join(folder, name + ".solidcraft")
        with open(design_path, "w", encoding="utf-8") as fh:
            json.dump(design, fh)
        image = os.path.join(folder, name + ".png")
        subprocess.run([cli, "snapshot", design_path, "--out", image, "--width", "1000", "--height", "800",
                        "--view", "iso", "--no-grid", "--no-axes"], check=True, capture_output=True, timeout=180)
        saved.append(image)
    from PIL import Image, ImageDraw
    left = Image.open(saved[0]).convert("RGB")
    right = Image.open(saved[1]).convert("RGB")
    width = left.width + right.width
    height = max(left.height, right.height) + 50
    comparison = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(comparison)
    draw.text((20, 15), "Saved solid reference", fill="black")
    draw.text((left.width + 20, 15), "Feature-tree rebuild", fill="black")
    comparison.paste(left, (0, 50))
    comparison.paste(right, (left.width, 50))
    result = os.path.join(folder, "comparison.png")
    comparison.save(result)
    return result


def one(args) -> str | None:
    return render_part(*args)


def main(argv=None) -> int:
    from rebuild_set import parts_of
    parser = argparse.ArgumentParser()
    parser.add_argument("parts", nargs="+")
    parser.add_argument("--out", default=os.path.join("out", "check-images"))
    parser.add_argument("--jobs", type=int, default=20)
    args = parser.parse_args(argv)
    paths = parts_of(args.parts)
    jobs = max(1, min(args.jobs, len(paths)))
    work = [(path, args.out) for path in paths]
    with ProcessPoolExecutor(jobs) as pool:
        for path, image in zip(paths, pool.map(one, work)):
            print(f"{os.path.basename(path)}: {image or 'no matching rebuild'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
