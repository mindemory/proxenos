"""Shrink the README's screenshots: 128 colours with no dithering, then zopflipng if it's there.

    python3 scripts/shrink-png.py SRC_DIR OUT_DIR

Needs Pillow. The page is dark with a few accent colours, so 128 colours keep its text and its
accents at about a fifth of the size; median cut, or fewer colours, turns the accents grey.
"""

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

OCTREE = getattr(Image, "Quantize", Image).FASTOCTREE  # Pillow 9.1 moved these into enums
NO_DITHER = getattr(Image, "Dither", Image).NONE
COLOURS = 128


def main(src: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    zopfli = shutil.which("zopflipng")
    total = 0
    for png in sorted(src.glob("*.png")):
        image = Image.open(png).convert("RGB")
        small = image.quantize(COLOURS, method=OCTREE, dither=NO_DITHER)
        dest = out / png.name
        tmp = out / f".{png.name}"
        small.save(tmp, optimize=True)
        if zopfli:
            subprocess.run([zopfli, "-y", str(tmp), str(dest)], check=True, capture_output=True)
            tmp.unlink()
        else:
            tmp.replace(dest)
        total += dest.stat().st_size
        print(f"{dest}: {image.width}x{image.height}, {dest.stat().st_size // 1024} KB")
    print(f"{total // 1024} KB in all" + ("" if zopfli else " (zopflipng would make it smaller)"))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
