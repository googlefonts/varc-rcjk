from font import createFontBuilder
from rcjkTools import *
from flatFont import buildFlatGlyph

from fontTools.misc.roundTools import otRound
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates
from fontTools.misc.fixedTools import floatToFixed as fl2fi
from fontTools.varLib.models import normalizeLocation, VariationModel
from fontTools.varLib.errors import VariationModelError
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from functools import partial
import struct


async def closureGlyphs(rcjkfont, glyphs):

    changed = True
    while changed:
        changed = False
        for glyph in list(glyphs.values()):
            assert glyph.sources[0].name == "<default>"
            assert glyph.sources[0].layerName == "foreground"
            assert glyph.layers[0].name == "foreground"
            layer = glyph.layers[0]
            for component in layer.glyph.components:
                if component.name not in glyphs:
                    componentGlyph = await rcjkfont.getGlyph(component.name)
                    glyphs[component.name] = componentGlyph
                    changed = True

class ComponentHave:
    have_translateX = False
    have_translateY = False
    have_rotation = False
    have_scaleX = False
    have_scaleY = False
    have_skewX = False
    have_skewY = False
    have_tcenterX = False
    have_tcenterY = False


def setupFvarAxes(rcjkfont, glyphs):
    fvarAxes = []
    for axis in rcjkfont.designspace['axes']:
        fvarAxes.append((axis['tag'], axis['minValue'], axis['defaultValue'], axis['maxValue'], axis['name']))

    maxAxes = 0
    for glyph in glyphs.values():
        axes = {axis.name:(axis.minValue,axis.defaultValue,axis.maxValue) for axis in glyph.axes}
        maxAxes = max(maxAxes, len(axes))

    for i in range(maxAxes):
        tag = '%4d' % i
        fvarAxes.append((tag, -1, 0, 1, tag))

    return fvarAxes


async def buildComponentPoints(rcjkfont, component,
                               coordinateVaries, coordinateHave, transformHave):

    componentGlyph = await rcjkfont.getGlyph(component.name)
    componentAxes = {axis.name:(axis.minValue,axis.defaultValue,axis.maxValue)
                     for axis in componentGlyph.axes}
    coords = component.location
    coords = normalizeLocation(coords, componentAxes)

    t = component.transformation

    points = []

    if coordinateVaries:
        for j,coord in enumerate(coords.values()):
            if j in coordinateHave:
                points.append((fl2fi(coord, 14), 0))

    c = transformHave
    if c.have_translateX or c.have_translateY:  points.append((t.translateX, t.translateY))
    if c.have_rotation:                         points.append((fl2fi(t.rotation / 180., 12), 0))
    if c.have_scaleX or c.have_scaleY:          points.append((fl2fi(t.scaleX, 10), fl2fi(t.scaleY, 10)))
    if c.have_skewX or c.have_skewY:            points.append((fl2fi(t.skewX / 180., 14), fl2fi(t.skewY / 180., 14)))
    if c.have_tcenterX or c.have_tcenterY:      points.append((t.tCenterX, t.tCenterY))

    return points

async def buildComponentRecord(rcjkfont, component,
                               coordinateVaries, coordinateHave, transformHave,
                               fvarTags, reverseGlyphMap):

    componentGlyph = await rcjkfont.getGlyph(component.name)

    componentAxes = {axis.name:(axis.minValue,axis.defaultValue,axis.maxValue)
                     for axis in componentGlyph.axes}
    coords = component.location
    coords = normalizeLocation(coords, componentAxes)

    t = component.transformation

    flag = 0

    numAxes = struct.pack(">B", len(coordinateHave))

    gid = reverseGlyphMap[component.name]
    if gid <= 65535:
        # gid16
        gid = struct.pack(">H", gid)
    else:
        # gid24
        gid = struct.pack(">L", gid)[1:]
        flag |= 1<<12

    axisIndices = []
    for i,coord in enumerate(coords):
        if i not in coordinateHave: continue
        name = '%4d' % i if coord not in fvarTags else coord
        axisIndices.append(fvarTags.index(name))

    if coordinateVaries:
        flag |= 1<<13

    if all(v <= 255 for v in axisIndices):
        axisIndices = b''.join(struct.pack(">B", v) for v in axisIndices)
    else:
        axisIndices = b''.join(struct.pack(">H", v) for v in axisIndices)
        flag |= (1<<1)

    axisValues = b''.join(struct.pack(">h", fl2fi(v, 14)) for i,v in enumerate(coords.values()) if i in coordinateHave)

    c = transformHave

    translateX = translateY = rotation = scaleX = scaleY = skewX = skewY = tcenterX = tcenterY = b""
    if c.have_translateX:
        translateX = struct.pack(">h", otRound(t.translateX))
        flag |= (1<<3)
    if c.have_translateY:
        translateY = struct.pack(">h", otRound(t.translateY))
        flag |= (1<<4)
    if c.have_rotation:
        rotation = struct.pack(">h", fl2fi(t.rotation / 180., 12))
        flag |= (1<<5)
    if c.have_scaleX:
        scaleX = struct.pack(">h", fl2fi(t.scaleX, 10))
        flag |= (1<<6)
    if c.have_scaleY:
        scaleY = struct.pack(">h", fl2fi(t.scaleY, 10))
        flag |= (1<<7)
    if c.have_skewX:
        skewX = struct.pack(">h", fl2fi(t.skewX / 180., 14))
        flag |= (1<<8)
    if c.have_skewY:
        skewY = struct.pack(">h", fl2fi(t.skewY / 180., 14))
        flag |= (1<<9)
    if c.have_tcenterX:
        tcenterX = struct.pack(">h", otRound(t.tCenterX))
        flag |= (1<<10)
    if c.have_tcenterY:
        tcenterY = struct.pack(">h", otRound(t.tCenterY))
        flag |= (1<<11)

    transform = translateX + translateY + rotation + scaleX + scaleY + skewX + skewY + tcenterX + tcenterY

    flag = struct.pack(">H", flag)

    rec = flag + numAxes + gid + axisIndices + axisValues + transform

    return rec


async def buildVarcFont(rcjkfont, glyphs):

    print("Building varc.ttf")

    await closureGlyphs(rcjkfont, glyphs)

    fvarAxes = setupFvarAxes(rcjkfont, glyphs)
    fvarTags = [axis[0] for axis in fvarAxes]

    fb = await createFontBuilder(rcjkfont, "rcjk", "varc", glyphs)
    reverseGlyphMap = fb.font.getReverseGlyphMap()

    fbGlyphs = {'.notdef': Glyph()}
    fbVariations = {}
    for glyph in glyphs.values():
        glyph_masters = glyphMasters(glyph)

        axes = {axis.name:(axis.minValue,axis.defaultValue,axis.maxValue) for axis in glyph.axes}
        axesMap = {}
        for i,name in enumerate(axes.keys()):
            axesMap[name] = '%4d' % i if name not in fvarTags else name

        if glyph_masters[()].glyph.path.coordinates:
            fbGlyphs[glyph.name], fbVariations[glyph.name] = await buildFlatGlyph(rcjkfont, glyph, axesMap)
            continue

        # VarComposite glyph...

        coordinates = {}
        transforms = {}
        b = 0, 0, 0, 0
        data = bytearray(struct.pack(">hhhhh", -2, b[0], b[1], b[2], b[3]))
        masterPoints = []

        transformHave = []
        coordinateHave = []
        layer = next(iter(glyph_masters.values()))
        defaultComponents = layer.glyph.components
        coordinateVaries = [False] * len(defaultComponents)
        for component in layer.glyph.components:
            transformHave.append(ComponentHave())
            coordinateHave.append(set())
        for layer in glyph_masters.values():
            for i,component in enumerate(layer.glyph.components):
                t = component.transformation
                if t.translateX:   transformHave[i].have_translateX = True
                if t.translateY:   transformHave[i].have_translateY = True
                if t.rotation:     transformHave[i].have_rotation = True
                if t.scaleX != 1:  transformHave[i].have_scaleX = True
                if t.scaleY != 1:  transformHave[i].have_scaleY = True
                if t.skewX:        transformHave[i].have_skewX = True
                if t.skewY:        transformHave[i].have_skewY = True
                if t.tCenterX:     transformHave[i].have_tcenterX = True
                if t.tCenterY:     transformHave[i].have_tcenterY = True
                for j,c in enumerate(component.location.values()):
                    if c:
                        coordinateHave[i].add(j)
                if component.location != defaultComponents[i].location:
                    coordinateVaries[i] = True

        for loc,layer in glyph_masters.items():

            points = []
            for ci,component in enumerate(layer.glyph.components):

                pts = await buildComponentPoints(rcjkfont,
                                                 component,
                                                 coordinateVaries[ci],
                                                 coordinateHave[ci],
                                                 transformHave[ci])
                points.extend(pts)

            masterPoints.append(GlyphCoordinates(points))

        # Build glyph data

        layer = next(iter(glyph_masters.values()))
        for ci,component in enumerate(layer.glyph.components):
            rec = await buildComponentRecord(rcjkfont,
                                             component,
                                             coordinateVaries[ci],
                                             coordinateHave[ci],
                                             transformHave[ci],
                                             fvarTags,
                                             reverseGlyphMap)
            data.extend(rec)

        ttGlyph = Glyph()
        ttGlyph.data = bytes(data)
        fbGlyphs[glyph.name] = ttGlyph

        # Build variation

        masterLocs = list(dictifyLocation(l)
                          for l in glyph_masters.keys())
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
