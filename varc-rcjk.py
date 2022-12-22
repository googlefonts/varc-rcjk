# pip install git+https://github.com/BlackFoundryCom/fontra.git
# pip install git+https://github.com/BlackFoundryCom/fontra-rcjk.git

# See src/fontra/core/classes.py in the fontra repo for the data structure
# PackedPath objects have a drawPoints method that takes a point pen


from fontTools.misc.roundTools import otRound
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuMultiPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.recordingPen import RecordingPen, RecordingPointPen
from fontTools.pens.pointPen import PointToSegmentPen
from fontTools.pens.transformPen import TransformPointPen
from fontTools.misc.transform import Transform, Identity
from fontTools.misc.vector import Vector
from fontTools.misc.fixedTools import floatToFixed as fl2fi
from fontTools.varLib.models import normalizeLocation, VariationModel
from fontTools.varLib.errors import VariationModelError
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from functools import partial
import argparse
import asyncio
import struct
import math
import operator
import sys
from fontra_rcjk.backend_fs import RCJKBackend


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
    if hasattr(glyph, "masters"):
        return glyph

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

    def _iop(self, other, op):
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
            pt0 = (op(pt0[0], pt1[0]), op(pt0[1], pt1[1]))
            out.append((op0, (pt0, segmentType0, smooth0, name0), kwargs0))

        self.value = out
        return self

    def __isub__(self, other):
        return self._iop(other, operator.sub)

    def __iadd__(self, other):
        return self._iop(other, operator.add)

async def decomposeGlyph(glyph, rcjkfont, location=(), trans=Identity):
    value = []
    axes = {axis.name:(axis.minValue,axis.defaultValue,axis.maxValue)
            for axis in glyph.axes}

    masterLocs = list(dictifyLocation(l)
                      for l in glyph.masters.keys())
    masterLocs = [normalizeLocation(m, axes)
                  for m in masterLocs]

    model = VariationModel(masterLocs, list(axes.keys()))


    # Interpolate outline

    masterShapes = [await decomposeLayer(layer, rcjkfont, trans, shallow=True)
                    for layer in glyph.masters.values()]

    loc = normalizeLocation(location, axes)
    shape = model.interpolateFromMasters(loc, masterShapes)

    value.extend(shape.value)

    # Interpolate components

    numComps = len(next(iter(glyph.masters.values())).glyph.components)
    for compIndex in range(numComps):
        compTransforms = []
        compLocations = []
        name = None
        for layer in glyph.masters.values():
            compName = layer.glyph.components[compIndex].name
            if name is not None:
                assert name == compName
            name = compName
            compTransforms.append(layer.glyph.components[compIndex].transformation)
            compLocations.append(layer.glyph.components[compIndex].location)

        locKeys = list(compLocations[0].keys())
        locationVectors = []
        for locations in compLocations:
            assert locKeys == list(locations.keys())
            locationVectors.append(Vector(locations.values()))
        transformVectors = []
        for t in compTransforms:
            transformVectors.append(Vector((t.translateX, t.translateY,
                                            t.rotation,
                                            t.scaleX, t.scaleY,
                                            t.skewX, t.skewY,
                                            t.tCenterX, t.tCenterY)))

        locationVector = model.interpolateFromMasters(loc, locationVectors)
        transformVector = model.interpolateFromMasters(loc, transformVectors)

        location = {k:v for k,v in zip(locKeys, locationVector)}
        transform = composeTransform(*transformVector)
        composedTrans = trans.transform(transform)

        componentGlyph = await loadGlyph(name, rcjkfont)
        shape = await decomposeGlyph(componentGlyph, rcjkfont, location, composedTrans)
        value.extend(shape.value)

    return MathRecording(value)

async def decomposeLayer(layer, rcjkfont, trans=Identity, shallow=False):

    pen = RecordingPointPen()
    tpen = TransformPointPen(pen, trans)
    layer.glyph.path.drawPoints(tpen)
    value = pen.value

    if shallow:
        return MathRecording(value)

    for component in layer.glyph.components:

        t = component.transformation
        componentTrans = composeTransform(t.translateX, t.translateY,
                                          t.rotation,
                                          t.scaleX, t.scaleY,
                                          t.skewX, t.skewY,
                                          t.tCenterX, t.tCenterY)
        composedTrans = trans.transform(componentTrans)

        componentGlyph = await loadGlyph(component.name, rcjkfont)

        value.extend((await decomposeGlyph(componentGlyph, rcjkfont, component.location, composedTrans)).value)

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

async def buildFlatGlyph(rcjkfont, glyph, axesNameToTag=None):
    axes = {axis.name:(axis.minValue,axis.defaultValue,axis.maxValue) for axis in glyph.axes}

    shapes = {}
    for loc,layer in glyph.masters.items():

        loc = dictifyLocation(loc)
        loc = normalizeLocation(loc, axes)
        loc = {k:v for k,v in loc.items() if v != 0}
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
    pens = [pen.glyph() for pen in pens]

    # default master
    assert () == list(shapes.keys())[0]
    fbGlyph = pens[0]

    # variations

    fbVariations = []

    masterCoords = [pen.coordinates for pen in pens]

    masterLocs = list(dictifyLocation(l)
                      for l in glyph.masters.keys())
    masterLocs = [normalizeLocation(m, axes)
                  for m in masterLocs]

    model = VariationModel(masterLocs, list(axes.keys()))

    deltas, supports = model.getDeltasAndSupports(masterCoords,
        round=partial(GlyphCoordinates.__round__, round=round)
    )

    fbGlyph.coordinates = deltas[0]
    for delta, support in zip(deltas[1:], supports[1:]):

        delta.extend([(0,0), (0,0), (0,0), (0,0)]) # TODO Phantom points
        if axesNameToTag is not None:
            support = {axesNameToTag[k]:v for k,v in support.items()}
        tv = TupleVariation(support, delta)
        fbVariations.append(tv)

    return fbGlyph, fbVariations


async def buildFlatFont(rcjkfont, glyphs):

    print("Building flat.ttf")

    revCmap = await rcjkfont.getReverseCmap()
    charGlyphs = {g:v for g,v in glyphs.items() if revCmap[g]}

    fb = await createFontBuilder(rcjkfont, "rcjk", "flat", charGlyphs)

    fbGlyphs = {'.notdef': Glyph()}
    fbVariations = {}
    glyphRecordings = {}
    for glyph in charGlyphs.values():
        fbGlyphs[glyph.name], fbVariations[glyph.name] = await buildFlatGlyph(rcjkfont, glyph)

    fvarAxes = []
    for axis in rcjkfont.designspace['axes']:
        fvarAxes.append((axis['tag'], axis['minValue'], axis['defaultValue'], axis['maxValue'], axis['name']))

    fb.setupFvar(fvarAxes, [])
    fb.setupGlyf(fbGlyphs)
    fb.setupGvar(fbVariations)
    fb.save("flat.ttf")

async def closureGlyphs(rcjkfont, glyphs):
    changed = True
    while changed:
        changed = False
        for glyph in list(glyphs.values()):
            layer = next(iter(glyph.masters.values()))
            for component in layer.glyph.components:
                if component.name not in glyphs:
                    componentGlyph = await loadGlyph(component.name, rcjkfont)
                    glyphs[component.name] = componentGlyph
                    changed = True

async def buildVarcFont(rcjkfont, glyphs):

    print("Building varc.ttf")

    await closureGlyphs(rcjkfont, glyphs)

    fvarAxes = []
    for axis in rcjkfont.designspace['axes']:
        fvarAxes.append((axis['tag'], axis['minValue'], axis['defaultValue'], axis['maxValue'], axis['name']))

    maxAxes = 0
    for glyph in glyphs.values():
        axes = {axis.name:(axis.minValue,axis.defaultValue,axis.maxValue) for axis in glyph.axes}
        maxAxes = max(maxAxes, len(axes))

    fvarAxesOffset = len(fvarAxes)
    for i in range(maxAxes):
        tag = '%4d' % i
        fvarAxes.append((tag, -1, 0, 1, tag))
    fvarTags = [axis[0] for axis in fvarAxes]


    fb = await createFontBuilder(rcjkfont, "rcjk", "varc", glyphs)
    reverseGlyphMap = fb.font.getReverseGlyphMap()

    fbGlyphs = {'.notdef': Glyph()}
    fbVariations = {}
    for glyph in glyphs.values():
        axes = {axis.name:(axis.minValue,axis.defaultValue,axis.maxValue) for axis in glyph.axes}
        axesMap = {}
        for i,name in enumerate(axes.keys()):
            axesMap[name] = '%4d' % i if name not in fvarTags else name

        if glyph.masters[()].glyph.path.coordinates:
            fbGlyphs[glyph.name], fbVariations[glyph.name] = await buildFlatGlyph(rcjkfont, glyph, axesMap)
            continue

        # VarComposite glyph...

        coordinates = {}
        transforms = {}
        b = 0, 0, 0, 0
        data = bytearray(struct.pack(">hhhhh", -2, b[0], b[1], b[2], b[3]))
        masterPoints = []

        have_translate = False
        have_rotation = False
        have_scale = False
        have_skew = False
        have_tcenter = False
        for loc,layer in glyph.masters.items():
            for component in layer.glyph.components:
                t = component.transformation
                if t.translateX or t.translateY:    have_translate = True
                if t.rotation:                      have_rotation = True
                if t.scaleX != 1 or t.scaleY != 1:  have_scale = True
                if t.skewX or t.skewY:              have_skew = True
                if t.tCenterX or t.tCenterY:        have_tcenter = True

        for loc,layer in glyph.masters.items():

            points = []
            for component in layer.glyph.components:
                componentGlyph = await loadGlyph(component.name, rcjkfont)
                componentAxes = {axis.name:(axis.minValue,axis.defaultValue,axis.maxValue)
                                 for axis in componentGlyph.axes}
                coords = component.location
                coords = normalizeLocation(coords, componentAxes)

                t = component.transformation

                for coord in coords.values():
                    points.append((fl2fi(coord, 14), 0))
                if have_translate:  points.append((t.translateX, t.translateY))
                if have_rotation:   points.append((fl2fi(t.rotation / 180., 12), 0))
                if have_scale:      points.append((fl2fi(t.scaleX, 10), fl2fi(t.scaleY, 10)))
                if have_skew:       points.append((fl2fi(t.skewX / 180., 14), fl2fi(t.skewY / 180., 14)))
                if have_tcenter:    points.append((t.tCenterX, t.tCenterY))

            masterPoints.append(GlyphCoordinates(points))

        # Build glyph data

        layer = next(iter(glyph.masters.values()))
        for component in layer.glyph.components:
            componentGlyph = await loadGlyph(component.name, rcjkfont)
            componentAxes = {axis.name:(axis.minValue,axis.defaultValue,axis.maxValue)
                             for axis in componentGlyph.axes}
            coords = component.location
            coords = normalizeLocation(coords, componentAxes)

            t = component.transformation

            flag = 1<<13

            numAxes = struct.pack(">B", len(coords))
            gid = struct.pack(">H", reverseGlyphMap[component.name])

            axisIndices = []
            for i,coord in enumerate(coords):
                name = '%4d' % i if coord not in fvarTags else coord
                axisIndices.append(fvarTags.index(name))

            if all(v <= 255 for v in axisIndices):
                axisIndices = b''.join(struct.pack(">B", v) for v in axisIndices)
            else:
                axisIndices = b''.join(struct.pack(">H", v) for v in axisIndices)
                flag |= (1<<1)

            axisValues = b''.join(struct.pack(">h", fl2fi(v, 14)) for v in coords.values())

            translate = rotation = scale = skew = tcenter = b""
            if have_translate:
                translate = struct.pack(">hh", otRound(t.translateX), otRound(t.translateY))
                flag |= (1<<3) | (1<<4)
            if have_rotation:
                rotation = struct.pack(">h", fl2fi(t.rotation / 180., 12))
                flag |= (1<<5)
            if have_scale:
                scale = struct.pack(">hh", fl2fi(t.scaleX, 10), fl2fi(t.scaleY, 10))
                flag |= (1<<6) | (1<<7)
            if have_skew:
                skew = struct.pack(">hh", fl2fi(t.skewX / 180., 14), fl2fi(t.skewY / 180., 14))
                flag |= (1<<8) | (1<<9)
            if have_tcenter:
                tcenter = struct.pack(">hh", otRound(t.tCenterX), otRound(t.tCenterY))
                flag |= (1<<10) | (1<<11)

            transform = translate + rotation + scale + skew + tcenter

            flag = struct.pack(">H", flag)

            rec = flag + numAxes + gid + axisIndices + axisValues + transform

            data.extend(rec)

        ttGlyph = Glyph()
        ttGlyph.data = bytes(data)
        fbGlyphs[glyph.name] = ttGlyph

        # Build variation

        masterLocs = list(dictifyLocation(l)
                          for l in glyph.masters.keys())
        masterLocs = [normalizeLocation(m, axes)
                      for m in masterLocs]

        masterLocs = [{axesMap[k]:v for k,v in loc.items()}
                      for loc in masterLocs]

        model = VariationModel(masterLocs, list(axes.keys()))

        deltas, supports = model.getDeltasAndSupports(masterPoints,
            round=partial(GlyphCoordinates.__round__, round=round)
        )

        fbVariations[glyph.name] = []
        for delta, support in zip(deltas[1:], supports[1:]):

            # Allow encoding 32768 by nudging it down.
            for i,(x,y) in enumerate(delta):
                if x == 32768: delta[i] = 32767,y
                if y == 32768: delta[i] = x,32767

            delta.extend([(0,0), (0,0), (0,0), (0,0)]) # TODO Phantom points
            tv = TupleVariation(support, delta)
            fbVariations[glyph.name].append(tv)

    fb.setupFvar(fvarAxes, [])
    fb.setupGlyf(fbGlyphs)
    fb.setupGvar(fbVariations)
    fb.font.recalcBBoxes = False
    fb.save("varc.ttf")


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

        glyph = await loadGlyph(glyphname, rcjkfont)
        glyphs[glyphname] = glyph

        # Check that glyph does not mix contours and components
        for layer in glyph.masters.values():
            assert not layer.glyph.path.coordinates or not layer.glyph.components

    await buildVarcFont(rcjkfont, glyphs)
    await buildFlatFont(rcjkfont, glyphs)

if __name__ == "__main__":
    import sys
    asyncio.run(main(sys.argv[1:]))
