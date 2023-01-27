
from fontTools.fontBuilder import FontBuilder

async def createFontBuilder(rcjkfont, family_name, style, glyphs):
    upem = await rcjkfont.getUnitsPerEm()

    glyphOrder = ['.notdef'] + list(glyphs.keys())
    revCmap = await rcjkfont.getReverseCmap()
    cmap = {}
    for glyph in glyphs.values():
        for unicode in revCmap[glyph.name]:
            # Font has duplicate Unicodes unfortunately :(
            #assert unicode not in cmap, (hex(unicode), glyphname, cmap[unicode])
            cmap[unicode] = glyph.name

    metrics = {'.notdef': (upem, 0)}
    for glyphname in glyphOrder[1:]:
        glyph = await rcjkfont.getGlyph(glyphname)
        assert glyph.sources[0].name == "<default>"
        assert glyph.sources[0].layerName == "foreground"
        assert glyph.layers[0].name == "foreground"
        advance = glyph.layers[0].glyph.xAdvance
        metrics[glyphname] = (max(advance,0), 0) # TODO lsb

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
    ascent = int(upem * .8) # TODO
    descent = -int(upem * .2) # TODO
    fb.setupHorizontalHeader(ascent=ascent, descent=descent)
    #fb.setupOS2(sTypoAscender=os2.sTypoAscender, usWinAscent=os2.usWinAscent, usWinDescent=os2.usWinDescent)
    fb.setupPost(keepGlyphNames=False)

    return fb

