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
    glyphset = args[1:]

    rcjkfont = RCJKBackend.fromPath(rcjk_path)
    revCmap = await rcjkfont.getGlyphMap()

    glyphs = {}
    for glyphname in revCmap.keys() if not glyphset else glyphset:
        print("Loading glyph", glyphname)
        glyph = await rcjkfont.getGlyph(glyphname)
        glyph_masters = glyphMasters(glyph)
        glyphs[glyphname] = glyph

    await buildVarcFont(rcjkfont, glyphs)
    await buildFlatFont(rcjkfont, glyphs)


if __name__ == "__main__":
    import sys

    asyncio.run(main(sys.argv[1:]))
