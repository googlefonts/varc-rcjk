from fontTools.misc.roundTools import otRound
from fontTools.misc.fixedTools import floatToFixed as fl2fi
from fontTools.varLib.models import normalizeLocation
import struct

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

def analyzeComponents(glyph_masters):

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

    return coordinateVaries, coordinateHave, transformHave


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