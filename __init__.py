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

    count = 10000000

    rcjk_path = args[0]
    glyphset = None
    if len(args) == 2:
        try:
            count = int(args[1])
        except ValueError:
            glyphset = args[1:]
    else:
        glyphset = args[1:]

    rcjkfont = RCJKBackend.fromPath(rcjk_path)
    revCmap = await rcjkfont.getReverseCmap()

    glyphs = {}
    for glyphname in list(revCmap.keys())[:count] if not glyphset else glyphset:

        glyph = await rcjkfont.getGlyph(glyphname)
        glyph_masters = glyphMasters(glyph)
        glyphs[glyphname] = glyph

        # Check that glyph does not mix contours and components
        for layer in glyph_masters.values():
            assert not layer.glyph.path.coordinates or not layer.glyph.components

    await buildVarcFont(rcjkfont, glyphs)
    await buildFlatFont(rcjkfont, glyphs)


if __name__ == "__main__":
    import sys

    asyncio.run(main(sys.argv[1:]))
