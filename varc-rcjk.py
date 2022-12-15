# pip install git+https://github.com/BlackFoundryCom/fontra.git
# pip install git+https://github.com/BlackFoundryCom/fontra-rcjk.git

# See src/fontra/core/classes.py in the fontra repo for the data structure
# PackedPath objects have a drawPoints method that takes a point pen


from fontTools.fontBuilder import FontBuilder
from fontTools.pens.recordingPen import RecordingPen
import argparse
import asyncio
from dataclasses import asdict
import json
import sys
from fontra_rcjk.backend_fs import RCJKBackend


async def createFontBuilder(rcjkfont, family_name, style, glyphs):
    upem = await rcjkfont.getUnitsPerEm()

    glyphOrder = list(glyphs.keys())
    cmap = {}
    for glyph in glyphs.values():
        for unicode in glyph.unicodes:
            # Font has duplicate Unicodes unfortunately :(
            #assert unicode not in cmap, (hex(unicode), glyphname, cmap[unicode])
            cmap[unicode] = glyph.name

    metrics = {}
    for glyphname in glyphOrder:
        glyph = await rcjkfont.getGlyph(glyphname)
        assert glyph.sources[0].name == "<default>"
        assert glyph.sources[0].layerName == "foreground"
        assert glyph.layers[0].name == "foreground"
        advance = glyph.layers[0].glyph.xAdvance
        metrics[glyphname] = (advance, 0) # TODO lsb

    nameStrings = dict(
        familyName=dict(en=family_name),
        styleName=dict(en=style),
    )

    fb = FontBuilder(upem, isTTF=True)
    #fb.setupHead(unitsPerEm=upem, created=rcjkfont.created, modified=rcjkfont.modified)
    fb.setupNameTable(nameStrings)
    fb.setupGlyphOrder(glyphOrder)
    fb.setupCharacterMap(cmap)
    fb.setupHorizontalMetrics(metrics)
    ascent = upem * .8 # TODO
    descent = upem * .2 # TODO
    fb.setupHorizontalHeader(ascent=ascent, descent=descent)
    #fb.setupOS2(sTypoAscender=os2.sTypoAscender, usWinAscent=os2.usWinAscent, usWinDescent=os2.usWinDescent)
    fb.setupPost(keepGlyphNames=False)

    return fb

def tuplifyLocation(loc):
    return tuple(sorted(loc.items()))

async def loadGlyph(glyphname, rcjkfont):
    glyph = await rcjkfont.getGlyph(glyphname)

    glyph.masters = {}

    layerLocationByName = {}
    for source in glyph.sources:
        locationTuple = tuplifyLocation(source.location)
        layerLocationByName[source.layerName] = locationTuple
    for layer in glyph.layers:
        if layer.name in layerLocationByName:
            glyph.masters[layerLocationByName[layer.name]] = layer

    return glyph


async def buildFlatFont(rcjkfont, glyphs):
    fb = await createFontBuilder(rcjkfont, "rcjk-flat", "regular", glyphs)



async def main(verify=True):
    parser = argparse.ArgumentParser()
    parser.add_argument("rcjk_path")
    args = parser.parse_args()
    rcjkfont = RCJKBackend.fromPath(args.rcjk_path)
    revCmap = await rcjkfont.getReverseCmap()

    glyphs = {}
    for glyphname in revCmap.keys():
        glyph = await loadGlyph(glyphname, rcjkfont)
        glyphs[glyphname] = glyph

        if verify:
            # Check that glyph does not mix contours and components
            for layer in glyph.masters.values():
                assert not layer.glyph.path.coordinates or not layer.glyph.components

    font = await buildFlatFont(rcjkfont, glyphs)

if __name__ == "__main__":
    asyncio.run(main())
