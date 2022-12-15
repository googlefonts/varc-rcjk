# pip install git+https://github.com/BlackFoundryCom/fontra.git
# pip install git+https://github.com/BlackFoundryCom/fontra-rcjk.git

# See src/fontra/core/classes.py in the fontra repo for the data structure
# PackedPath objects have a drawPoints method that takes a point pen


from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuMultiPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.recordingPen import RecordingPen, RecordingPointPen
from fontTools.pens.pointPen import PointToSegmentPen
from fontTools.pens.transformPen import TransformPointPen
from fontTools.misc.transform import Transform, Identity
from fontTools.varLib.models import normalizeLocation, VariationModel
from fontTools.varLib.errors import VariationModelError
import argparse
import asyncio
from dataclasses import asdict
import math
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
    ascent = int(upem * .8) # TODO
    descent = int(upem * .2) # TODO
    fb.setupHorizontalHeader(ascent=ascent, descent=descent)
    #fb.setupOS2(sTypoAscender=os2.sTypoAscender, usWinAscent=os2.usWinAscent, usWinDescent=os2.usWinDescent)
    fb.setupPost(keepGlyphNames=False)

    return fb

def tuplifyLocation(loc):
    return tuple(sorted(loc.items()))

def dictifyLocation(loc):
    return {k:v for k,v in loc}

async def loadGlyph(glyphname, rcjkfont):
    glyph = await rcjkfont.getGlyph(glyphname)

    glyph.masters = {}

    layersByName = {}
    for layer in glyph.layers:
        layersByName[layer.name] = layer

    for source in glyph.sources:
        locationTuple = tuplifyLocation(source.location)
        glyph.masters[locationTuple] = layersByName[source.layerName]

    return glyph

def composeTransform(
    translateX: float,
    translateY: float,
    rotation: float,
    scaleX: float,
    scaleY: float,
    skewX: float,
    skewY: float,
    tCenterX: float,
    tCenterY: float,
) -> Transform:
    """Compose a decomposed transform into an Affine transform."""
    t = Transform()
    t = t.translate(tCenterX, tCenterY)
    t = t.translate(translateX, translateY)
    t = t.rotate(math.radians(rotation))
    t = t.scale(scaleX, scaleY)
    t = t.skew(-math.radians(skewX), math.radians(skewY))
    t = t.translate(-tCenterX, -tCenterY)
    return t

class MathRecording:

    def __init__(self, value):
        self.value = list(value)

    def __mul__(self, scalar):
        out = []
        for v in self.value:
            if v[0] != "addPoint":
                out.append(v)
                continue
            op, (pt, segmentType, smooth, name), kwargs = v
            pt = (pt[0] * scalar, pt[1] * scalar)
            out.append((op, (pt, segmentType, smooth, name), kwargs))

        return MathRecording(out)

    def __isub__(self, other):
        assert len(self.value) == len(other.value)
        out = []
        for v,o in zip(self.value, other.value):
            assert v[0] == o[0]
            if v[0] != "addPoint":
                out.append(v)
                continue
            op0, (pt0, segmentType0, smooth0, name0), kwargs0 = v
            op1, (pt1, segmentType1, smooth1, name1), kwargs0 = o
            assert segmentType0 == segmentType1
            #assert smooth0 == smooth1
            pt0 = (pt0[0] - pt1[0], pt0[1] - pt1[1])
            out.append((op0, (pt0, segmentType0, smooth0, name0), kwargs0))

        self.value = out
        return self

    def __iadd__(self, other):
        assert len(self.value) == len(other.value)
        out = []
        for v,o in zip(self.value, other.value):
            assert v[0] == o[0]
            if v[0] != "addPoint":
                out.append(v)
                continue
            op0, (pt0, segmentType0, smooth0, name0), kwargs0 = v
            op1, (pt1, segmentType1, smooth1, name1), kwargs0 = o
            assert segmentType0 == segmentType1
            #assert smooth0 == smooth1
            pt0 = (pt0[0] + pt1[0], pt0[1] + pt1[1])
            out.append((op0, (pt0, segmentType0, smooth0, name0), kwargs0))

        self.value = out
        return self

async def decomposeLayer(layer, rcjkfont, trans=Identity):

    pen = RecordingPointPen()
    tpen = TransformPointPen(pen, trans)
    layer.glyph.path.drawPoints(tpen)
    value = pen.value

    for component in layer.glyph.components:

        t = component.transformation
        componentTrans = composeTransform(t.translateX, t.translateY,
                                          t.rotation,
                                          t.scaleX, t.scaleY,
                                          t.skewX, t.skewY,
                                          t.tCenterX, t.tCenterY)
        composedTrans = componentTrans.transform(trans) # XXX ?

        componentGlyph = await loadGlyph(component.name, rcjkfont)

        # Interpolate component

        axes = {axis.name:(axis.minValue,axis.defaultValue,axis.maxValue)
                for axis in componentGlyph.axes}

        masterLocs = list(dictifyLocation(l)
                          for l in componentGlyph.masters.keys())
        masterLocs = [normalizeLocation(m, axes)
                      for m in masterLocs]

        model = VariationModel(masterLocs, list(axes.keys()))

        masterShapes = [await decomposeLayer(compLayer, rcjkfont, composedTrans)
                        for compLayer in componentGlyph.masters.values()]

        loc = normalizeLocation(component.location, axes)
        componentShape = model.interpolateFromMasters(loc, masterShapes)

        value.extend(componentShape.value)

    return MathRecording(value)


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


async def buildFlatFont(rcjkfont, glyphs):

    charGlyphs = {g:v for g,v in glyphs.items() if v.unicodes}

    fb = await createFontBuilder(rcjkfont, "rcjk-flat", "regular", charGlyphs)

    fbGlyphs = {}
    glyphRecordings = {}
    for glyph in charGlyphs.values():
        axes = {axis.name:(axis.minValue,axis.defaultValue,axis.maxValue) for axis in glyph.axes}

        shapes = {}
        for loc,layer in glyph.masters.items():

            loc = dictifyLocation(loc)
            loc = normalizeLocation(loc, axes, dropZeroes=True)
            loc = tuplifyLocation(loc)

            rspen = RecordingPen()
            pspen = PointToSegmentPen(rspen, outputImpliedClosingLine=True)
            rppen = RecordingPointPen()
            rppen.value = (await decomposeLayer(layer, rcjkfont)).value
            rppen.replay(pspen)

            shapes[loc] = rspen.value

        pens = [TTGlyphPen() for i in range(len(glyph.masters))]
        cu2quPen = Cu2QuMultiPen(pens, 1)
        # Pass all shapes through Cu2QuMultiPen
        replayCommandsThroughCu2QuMultiPen(shapes.values(), cu2quPen)

        assert () == list(shapes.keys())[0]
        fbGlyphs[glyph.name] = pens[0].glyph()

    fb.setupGlyf(fbGlyphs)
    fb.save("flat.ttf")




async def main(args):
    rcjk_path = args[0]
    count = 100000000
    if len(args) > 1:
        count = int(args[1])

    rcjkfont = RCJKBackend.fromPath(rcjk_path)
    revCmap = await rcjkfont.getReverseCmap()

    glyphs = {}
    for glyphname in list(revCmap.keys())[:count]:

        glyph = await loadGlyph(glyphname, rcjkfont)
        glyphs[glyphname] = glyph

        # Check that glyph does not mix contours and components
        for layer in glyph.masters.values():
            assert not layer.glyph.path.coordinates or not layer.glyph.components

    font = await buildFlatFont(rcjkfont, glyphs)

if __name__ == "__main__":
    import sys
    asyncio.run(main(sys.argv[1:]))
