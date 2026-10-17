# -*- coding: utf-8 -*-
"""Contact sheet of one frame per segment (or of a directory of images).

Usage:
    python contact_sheet.py SRC_DIR OUT.png [--prefix g] [--cols 8] [--cw 320]

Typical use: render preview/g<NN>_p85.png for every segment at about p=0.85
(the page at its fullest) and read the sheet for rhythm, alignment, and palette
drift before rendering the whole film.
"""
import os, sys

from PIL import Image


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "preview"
    out = sys.argv[2] if len(sys.argv) > 2 else "sheet.png"
    prefix, cols, cw = "g", 8, 320
    for a in sys.argv[3:]:
        if a.startswith("--prefix"):
            prefix = a.split("=", 1)[1]
        if a.startswith("--cols"):
            cols = int(a.split("=", 1)[1])
        if a.startswith("--cw"):
            cw = int(a.split("=", 1)[1])
    fs = sorted(f for f in os.listdir(src) if f.startswith(prefix) and f.lower().endswith(".png"))
    if not fs:
        print("no files matching %s*.png in %s" % (prefix, src))
        return 1
    first = Image.open(os.path.join(src, fs[0]))
    ch = int(cw * first.height / float(first.width))
    rows = (len(fs) + cols - 1) // cols
    sheet = Image.new("RGB", (cw * cols, ch * rows), (70, 70, 70))
    for i, f in enumerate(fs):
        sheet.paste(Image.open(os.path.join(src, f)).resize((cw, ch), Image.LANCZOS),
                    ((i % cols) * cw, (i // cols) * ch))
    sheet.save(out)
    print("sheet %s  %d tiles  <- %s" % (sheet.size, len(fs), src))
    return 0


if __name__ == "__main__":
    sys.exit(main())
