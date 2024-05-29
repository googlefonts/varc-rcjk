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

    rcjk_path = args[0]
    status = None
    i = 1
    if len(args) > i and args[i][0] == "-":
        status = int(args[i][1:])
        i += 1
    glyphset = args[i:]

    rcjkfont = RCJKBackend.fromPath(rcjk_path)
    revCmap = await rcjkfont.getGlyphMap()

    glyphs = {}
    for glyphname in revCmap.keys() if not glyphset else glyphset:
        print("Loading glyph", glyphname)
        glyph = await rcjkfont.getGlyph(glyphname)
        glyph_masters = glyphMasters(glyph)
        if status is not None:
            if not any(source.customData.get("fontra.development.status", status) == status for source in glyph.sources):
                print("Skipping glyph", glyphname)
                continue

        glyphs[glyphname] = glyph

    await buildVarcFont(rcjkfont, glyphs)
    await buildFlatFont(rcjkfont, glyphs)


if __name__ == "__main__":
    import sys

    asyncio.run(main(sys.argv[1:]))
