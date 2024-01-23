from fontTools.fontBuilder import FontBuilder


async def createFontBuilder(rcjkfont, family_name, style, glyphs, glyphDataFormat=0):
    upem = await rcjkfont.getUnitsPerEm()

    glyphOrder = list(glyphs.keys())
    metrics = {}

    revCmap = await rcjkfont.getGlyphMap()
    cmap = {}
    for glyph in glyphs.values():
        for unicode in revCmap[glyph.name]:
            # Font has duplicate Unicodes unfortunately :(
            # assert unicode not in cmap, (hex(unicode), glyphname, cmap[unicode])
            cmap[unicode] = glyph.name

    for glyphname in glyphOrder:
        glyph = await rcjkfont.getGlyph(glyphname)
        assert glyph.sources[0].name == "<default>"
        assert glyph.sources[0].layerName == "foreground"
        advance = glyph.layers["foreground"].glyph.xAdvance
        metrics[glyphname] = (max(advance, 0), 0)  # TODO lsb

    if ".notdef" not in glyphOrder:
        glyphOrder.insert(0, ".notdef")
        metrics[".notdef"] = (upem, 0)

    nameStrings = dict(
        familyName=dict(en=family_name),
        styleName=dict(en=style),
    )

    fb = FontBuilder(upem, isTTF=True)
    fb.setupHead(
        unitsPerEm=upem, glyphDataFormat=glyphDataFormat
    )  # created=rcjkfont.created, modified=rcjkfont.modified)
    fb.setupNameTable(nameStrings)
    fb.setupGlyphOrder(glyphOrder)
    fb.setupCharacterMap(cmap)
    fb.setupHorizontalMetrics(metrics)
    ascent = int(upem * 0.8)  # TODO
    descent = -int(upem * 0.2)  # TODO
    fb.setupHorizontalHeader(ascent=ascent, descent=descent)
    # fb.setupOS2(sTypoAscender=os2.sTypoAscender, usWinAscent=os2.usWinAscent, usWinDescent=os2.usWinDescent)
    fb.setupPost(keepGlyphNames=False)

    return fb


def fixLsb(fb):
    metrics = fb.font["hmtx"].metrics
    glyf = fb.font["glyf"]
    for glyphname in glyf.keys():
        v = getattr(glyf.glyphs[glyphname], "xMin", 0)
        metrics[glyphname] = (metrics[glyphname][0], v)


def recalcSimpleGlyphBounds(fb):
    glyf = fb.font["glyf"]
    for glyphname in glyf.keys():
        glyph = glyf.glyphs[glyphname]
        if not hasattr(glyph, "data"):
            glyph.recalcBounds(glyf)
