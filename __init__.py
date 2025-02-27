# pip install git+https://github.com/BlackFoundryCom/fontra.git
# pip install git+https://github.com/BlackFoundryCom/fontra-rcjk.git

from font import createFontBuilder
from rcjkTools import *
from flatFont import buildFlatFont
from varcFont import buildVarcFont

import argparse
import asyncio
import sys
from fontra_rcjk.backend_fs import RCJKBackend


async def main(args):
    print("Loading glyphs")

    parser = argparse.ArgumentParser(description="Build a fontra font")
    parser.add_argument("rcjk_path", type=str, help="Path to the RCJK font")
    parser.add_argument(
        "glyphs", type=str, nargs="*", help="List of glyphs to build (default: all)"
    )
    parser.add_argument(
        "--optimize-speed",
        action="store_true",
        help="Optimize the font for speed (default: False)",
    )
    parser.add_argument(
        "--status",
        type=int,
        help="Only build glyphs with the specified status (default: all)",
    )
    args = parser.parse_args(args)

    optimizeSpeed = args.optimize_speed or False

    rcjk_path = args.rcjk_path
    status = args.status
    glyphset = args.glyphs

    rcjkfont = RCJKBackend.fromPath(rcjk_path)
    revCmap = await rcjkfont.getGlyphMap()

    glyphs = {}
    for glyphname in revCmap.keys() if not glyphset else glyphset:
        print("Loading glyph", glyphname)
        glyph = await rcjkfont.getGlyph(glyphname)
        glyph_masters = glyphMasters(glyph)
        if status is not None:
            if not any(
                source.customData.get("fontra.development.status", status) == status
                for source in glyph.sources
            ):
                print("Skipping glyph", glyphname)
                continue

        glyphs[glyphname] = glyph

    await buildVarcFont(rcjkfont, glyphs, optimizeSpeed)
    await buildFlatFont(rcjkfont, glyphs)


if __name__ == "__main__":
    import sys

    asyncio.run(main(sys.argv[1:]))
