from font import *
from rcjkTools import *
from flatFont import buildFlatGlyph
from component import *

from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates
from fontTools.varLib.models import normalizeLocation, VariationModel
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from functools import partial
import struct


async def closureGlyph(rcjkfont, glyphs, glyph):
    assert glyph.sources[0].name == "<default>"
    assert glyph.sources[0].layerName == "foreground"
    layer = glyph.layers["foreground"]
    for component in layer.glyph.components:
        if component.name not in glyphs:
            componentGlyph = await rcjkfont.getGlyph(component.name)
            glyphs[component.name] = componentGlyph
            await closureGlyph(rcjkfont, glyphs, componentGlyph)


async def closureGlyphs(rcjkfont, glyphs):

    for glyph in list(glyphs.values()):
        await closureGlyph(rcjkfont, glyphs, glyph)


def setupFvarAxes(rcjkfont, glyphs):
    fvarAxes = []
    for axis in rcjkfont.designspace["axes"]:
        fvarAxes.append(
            (
                axis["tag"],
                axis["minValue"],
                axis["defaultValue"],
                axis["maxValue"],
                axis["name"],
            )
        )

    maxAxes = 0
    for glyph in glyphs.values():
        axes = {
            axis.name: (axis.minValue, axis.defaultValue, axis.maxValue)
            for axis in glyph.axes
        }
        maxAxes = max(maxAxes, len(axes))

    for i in range(maxAxes):
        tag = "%4d" % i
        fvarAxes.append((tag, -1, 0, 1, tag))

    return fvarAxes


async def buildVarcFont(rcjkfont, glyphs):

    print("Building varc.ttf")

    await closureGlyphs(rcjkfont, glyphs)

    publicAxes = set()
    for axis in rcjkfont.designspace["axes"]:
        publicAxes.add(axis["tag"])
    fvarAxes = setupFvarAxes(rcjkfont, glyphs)
    fvarTags = [axis[0] for axis in fvarAxes]

    fb = await createFontBuilder(rcjkfont, "rcjk", "varc", glyphs)
    reverseGlyphMap = fb.font.getReverseGlyphMap()

    fbGlyphs = {".notdef": Glyph()}
    fbVariations = {}

    for glyph in glyphs.values():

        glyph_masters = glyphMasters(glyph)

        axes = {
            axis.name: (axis.minValue, axis.defaultValue, axis.maxValue)
            for axis in glyph.axes
        }
        axesMap = {}
        for i, name in enumerate(axes.keys()):
            axesMap[name] = "%4d" % i if name not in fvarTags else name

        if glyph_masters[()].glyph.path.coordinates:

            # Simple glyph...

            fbGlyphs[glyph.name], fbVariations[glyph.name] = await buildFlatGlyph(
                rcjkfont, glyph, axesMap
            )
            continue

        # VarComposite glyph...

        componentAnalysis = analyzeComponents(glyph_masters, axes, publicAxes)

        #
        # Build glyph data
        #

        b = 0, 0, 0, 0
        data = bytearray(
            struct.pack(">hhhhh", -2, b[0], b[1], b[2], b[3])
        )  # Glyph header

        layer = next(iter(glyph_masters.values()))  # Default master
        for ci, component in enumerate(layer.glyph.components):
            rec = buildComponentRecord(
                component,
                glyphs[component.name],
                componentAnalysis[ci],
                fvarTags,
                reverseGlyphMap,
            )
            data.extend(rec)

        ttGlyph = Glyph()
        ttGlyph.data = bytes(data)
        fbGlyphs[glyph.name] = ttGlyph

        #
        # Build variations
        #

        # Build master points

        masterPoints = []
        for loc, layer in glyph_masters.items():

            points = []
            for ci, component in enumerate(layer.glyph.components):

                pts = buildComponentPoints(
                    rcjkfont, component, glyphs[component.name], componentAnalysis[ci]
                )
                points.extend(pts)

            masterPoints.append(GlyphCoordinates(points))

        # Get deltas and supports

        masterLocs = list(dictifyLocation(l) for l in glyph_masters.keys())
        masterLocs = [normalizeLocation(m, axes) for m in masterLocs]
        masterLocs = [{axesMap[k]: v for k, v in loc.items()} for loc in masterLocs]

        model = VariationModel(masterLocs, list(axes.keys()))

        deltas, supports = model.getDeltasAndSupports(
            masterPoints, round=partial(GlyphCoordinates.__round__, round=round)
        )

        # Build tuple variations

        fbVariations[glyph.name] = []
        for delta, support in zip(deltas[1:], supports[1:]):

            # Allow encoding 32768 by nudging it down.
            for i, (x, y) in enumerate(delta):
                if x == 32768:
                    delta[i] = 32767, y
                if y == 32768:
                    delta[i] = x, 32767

            delta.extend([(0, 0), (0, 0), (0, 0), (0, 0)])  # TODO Phantom points
            tv = TupleVariation(support, delta)
            fbVariations[glyph.name].append(tv)

    fb.setupFvar(fvarAxes, [])
    fb.setupGlyf(fbGlyphs)
    fb.setupGvar(fbVariations)
    recalcSimpleGlyphBounds(fb)
    fixLsb(fb)
    fb.font.recalcBBoxes = False
    fb.save("varc.ttf")
