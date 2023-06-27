from font import createFontBuilder, fixLsb
from decompose import decomposeLayer
from rcjkTools import *

from fontTools.varLib.models import normalizeLocation, VariationModel
from fontTools.pens.recordingPen import RecordingPen, RecordingPointPen
from fontTools.pens.pointPen import PointToSegmentPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.cu2quPen import Cu2QuMultiPen
from fontTools.pens.boundsPen import ControlBoundsPen
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from functools import partial


def replayCommandsThroughCu2QuMultiPen(commands, cu2quPen):
    for ops in zip(*commands):
        opNames = [op[0] for op in ops]
        opArgs = [op[1] for op in ops]
        opName = opNames[0]
        assert all(name == opName for name in opNames)
        if len(opArgs[0]):
            getattr(cu2quPen, opName)(opArgs)
        else:
            getattr(cu2quPen, opName)()


async def buildFlatGlyph(rcjkfont, glyph, axesNameToTag=None):
    axes = {
        axis.name: (axis.minValue, axis.defaultValue, axis.maxValue)
        for axis in glyph.axes
    }

    glyph_masters = glyphMasters(glyph)

    shapes = {}
    for loc, layer in glyph_masters.items():

        loc = dictifyLocation(loc)
        loc = normalizeLocation(loc, axes)
        loc = {k: v for k, v in loc.items() if v != 0}
        loc = tuplifyLocation(loc)

        rspen = RecordingPen()
        pspen = PointToSegmentPen(rspen, outputImpliedClosingLine=True)
        rppen = RecordingPointPen()
        rppen.value = (await decomposeLayer(layer, rcjkfont)).value
        rppen.replay(pspen)

        shapes[loc] = rspen.value

    pens = [TTGlyphPen() for i in range(len(glyph_masters))]
    cu2quPen = Cu2QuMultiPen(pens, 1)
    # Pass all shapes through Cu2QuMultiPen
    replayCommandsThroughCu2QuMultiPen(shapes.values(), cu2quPen)
    pens = [pen.glyph() for pen in pens]

    # default master
    assert () == list(shapes.keys())[0]
    fbGlyph = pens[0]

    # variations

    fbVariations = []

    masterCoords = [pen.coordinates for pen in pens]

    masterLocs = list(dictifyLocation(l) for l in glyph_masters.keys())
    masterLocs = [normalizeLocation(m, axes) for m in masterLocs]

    model = VariationModel(masterLocs, list(axes.keys()))

    deltas, supports = model.getDeltasAndSupports(
        masterCoords, round=partial(GlyphCoordinates.__round__, round=round)
    )

    fbGlyph.coordinates = deltas[0]
    for delta, support in zip(deltas[1:], supports[1:]):

        delta.extend([(0, 0), (0, 0), (0, 0), (0, 0)])  # TODO Phantom points
        if axesNameToTag is not None:
            support = {axesNameToTag[k]: v for k, v in support.items()}
        tv = TupleVariation(support, delta)
        fbVariations.append(tv)

    return fbGlyph, fbVariations


async def buildFlatFont(rcjkfont, glyphs):

    print("Building flat.ttf")

    revCmap = await rcjkfont.getGlyphMap()
    charGlyphs = {g: v for g, v in glyphs.items() if revCmap[g]}

    fb = await createFontBuilder(rcjkfont, "rcjk", "flat", charGlyphs)

    fbGlyphs = {".notdef": Glyph()}
    fbVariations = {}
    glyphRecordings = {}
    for glyph in charGlyphs.values():
        fbGlyphs[glyph.name], fbVariations[glyph.name] = await buildFlatGlyph(
            rcjkfont, glyph
        )

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

    fb.setupFvar(fvarAxes, [])
    fb.setupGlyf(fbGlyphs)
    fb.setupGvar(fbVariations)
    fixLsb(fb)
    fb.save("flat.ttf")
