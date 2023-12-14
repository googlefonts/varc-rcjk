from fontTools.misc.roundTools import otRound
from fontTools.misc.fixedTools import floatToFixed as fl2fi
from fontTools.varLib.models import normalizeLocation
from rcjkTools import *
import struct


class TransformHave:
    have_translateX = False
    have_translateY = False
    have_rotation = False
    have_scaleX = False
    have_scaleY = False
    have_skewX = False
    have_skewY = False
    have_tcenterX = False
    have_tcenterY = False


class ComponentAnalysis:
    def __init__(self):
        self.coordinates = set()
        self.coordinateVaries = False
        self.coordinateHaveOverlay = set()
        self.coordinateHaveReset = set()
        self.coordinateHave = set()
        self.coordinatesReset = None
        self.transformHave = TransformHave()


def analyzeComponents(glyph_masters, glyphs, glyphAxes, publicAxes):
    layer = next(iter(glyph_masters.values()))
    defaultComponents = layer.glyph.components
    defaultLocations = []
    allComponentAxes = []
    for component in defaultComponents:
        loc = component.location
        componentAxes = {
            axis.name: (axis.minValue, axis.defaultValue, axis.maxValue)
            for axis in glyphs[component.name].axes
        }
        allComponentAxes.append(componentAxes)
        loc = normalizeLocation(loc, componentAxes)
        defaultLocations.append(loc)

    cas = []
    for component in layer.glyph.components:
        cas.append(ComponentAnalysis())

    for masterLocationTuple, layer in glyph_masters.items():
        for i, component in enumerate(layer.glyph.components):
            ca = cas[i]
            ca.coordinates.update(component.location.keys())
    for ca in cas:
        ca.coordinates = list(sorted(ca.coordinates))

    for masterLocationTuple, layer in glyph_masters.items():
        masterLocation = dictifyLocation(masterLocationTuple)
        for i, component in enumerate(layer.glyph.components):
            ca = cas[i]
            t = component.transformation
            if otRound(t.translateX):
                ca.transformHave.have_translateX = True
            if otRound(t.translateY):
                ca.transformHave.have_translateY = True
            if fl2fi(t.rotation / 180.0, 12):
                ca.transformHave.have_rotation = True
            if fl2fi(t.scaleX, 10) != 1 << 10:
                ca.transformHave.have_scaleX = True
            if fl2fi(t.scaleY, 10) != 1 << 10:
                ca.transformHave.have_scaleY = True
            if fl2fi(t.skewX / 180.0, 12):
                ca.transformHave.have_skewX = True
            if fl2fi(t.skewY / 180.0, 12):
                ca.transformHave.have_skewY = True
            if otRound(t.tCenterX):
                ca.transformHave.have_tcenterX = True
            if otRound(t.tCenterY):
                ca.transformHave.have_tcenterY = True

            loc = component.location
            loc = normalizeLocation(loc, allComponentAxes[i])
            for tag in ca.coordinates:
                c = loc.get(tag, 0)
                if c:
                    ca.coordinateHaveReset.add(tag)
                if c != masterLocation.get(tag, 0) or (
                    tag in publicAxes and tag not in glyphAxes
                ):
                    ca.coordinateHaveOverlay.add(tag)

    for ca in cas:
        ca.coordinatesReset = len(ca.coordinateHaveReset) <= len(
            ca.coordinateHaveOverlay
        )
        ca.coordinateHave = (
            ca.coordinateHaveReset if ca.coordinatesReset else ca.coordinateHaveOverlay
        )

    for layer in glyph_masters.values():
        for i, component in enumerate(layer.glyph.components):
            ca = cas[i]
            loc = component.location
            loc = normalizeLocation(loc, allComponentAxes[i])
            for tag in ca.coordinates:
                if tag in ca.coordinateHave and loc.get(tag, 0) != defaultLocations[
                    i
                ].get(tag, 0):
                    ca.coordinateVaries = True

    return cas


def buildComponentPoints(rcjkfont, component, componentGlyph, componentAnalysis):
    ca = componentAnalysis

    componentAxes = {
        axis.name: (axis.minValue, axis.defaultValue, axis.maxValue)
        for axis in componentGlyph.axes
    }
    coords = component.location
    coords = normalizeLocation(coords, componentAxes)

    t = component.transformation

    points = []

    if ca.coordinateVaries:
        for tag in componentAxes.keys():
            if tag in ca.coordinateHave:
                coord = coords.get(tag, 0)
                points.append((fl2fi(coord, 14), 0))

    c = ca.transformHave
    if c.have_translateX or c.have_translateY:
        points.append((t.translateX, t.translateY))
    if c.have_rotation:
        points.append((fl2fi(t.rotation / 180.0, 12), 0))
    if c.have_scaleX or c.have_scaleY:
        points.append((fl2fi(t.scaleX, 10), fl2fi(t.scaleY, 10)))
    if c.have_skewX or c.have_skewY:
        points.append((fl2fi(t.skewX / 180.0, 12), fl2fi(t.skewY / 180.0, 12)))
    if c.have_tcenterX or c.have_tcenterY:
        points.append((t.tCenterX, t.tCenterY))

    return points


def buildComponentRecord(
    component, componentGlyph, componentAnalysis, fvarTags, reverseGlyphMap
):
    ca = componentAnalysis

    componentAxes = {
        axis.name: (axis.minValue, axis.defaultValue, axis.maxValue)
        for axis in componentGlyph.axes
    }
    coords = component.location
    coords = normalizeLocation(coords, componentAxes)

    flag = 0

    numAxes = struct.pack(">B", len(ca.coordinateHave))

    gid = reverseGlyphMap[component.name]
    if gid <= 65535:
        # gid16
        gid = struct.pack(">H", gid)
    else:
        # gid24
        gid = struct.pack(">L", gid)[1:]
        flag |= 1 << 12

    if ca.coordinatesReset:
        flag |= 1 << 14

    axisIndices = []
    for i, tag in enumerate(componentAxes.keys()):
        if tag not in ca.coordinateHave:
            continue
        name = "%4d" % i if tag not in fvarTags else tag
        axisIndices.append(fvarTags.index(name))

    if ca.coordinateVaries:
        flag |= 1 << 13

    if all(v <= 255 for v in axisIndices):
        axisIndices = b"".join(struct.pack(">B", v) for v in axisIndices)
    else:
        axisIndices = b"".join(struct.pack(">H", v) for v in axisIndices)
        flag |= 1 << 1

    axisValues = b"".join(
        struct.pack(">h", fl2fi(coords.get(tag, 0), 14))
        for tag in componentAxes.keys()
        if tag in ca.coordinateHave
    )

    c = ca.transformHave

    t = component.transformation

    translateX = (
        translateY
    ) = rotation = scaleX = scaleY = skewX = skewY = tcenterX = tcenterY = b""
    if c.have_translateX:
        translateX = struct.pack(">h", otRound(t.translateX))
        flag |= 1 << 3
    if c.have_translateY:
        translateY = struct.pack(">h", otRound(t.translateY))
        flag |= 1 << 4
    if c.have_rotation:
        rotation = struct.pack(">h", fl2fi(t.rotation / 180.0, 12))
        flag |= 1 << 5
    if c.have_scaleX:
        scaleX = struct.pack(">h", fl2fi(t.scaleX, 10))
        flag |= 1 << 6
    if c.have_scaleY:
        if not c.have_scaleX or fl2fi(t.scaleY, 10) != fl2fi(t.scaleX, 10):
            scaleY = struct.pack(">h", fl2fi(t.scaleY, 10))
            flag |= 1 << 7
        else:
            flag |= 1 << 2
    if c.have_skewX:
        skewX = struct.pack(">h", fl2fi(t.skewX / 180.0, 12))
        flag |= 1 << 8
    if c.have_skewY:
        skewY = struct.pack(">h", fl2fi(t.skewY / 180.0, 12))
        flag |= 1 << 9
    if c.have_tcenterX:
        tcenterX = struct.pack(">h", otRound(t.tCenterX))
        flag |= 1 << 10
    if c.have_tcenterY:
        tcenterY = struct.pack(">h", otRound(t.tCenterY))
        flag |= 1 << 11

    transform = (
        translateX
        + translateY
        + rotation
        + scaleX
        + scaleY
        + skewX
        + skewY
        + tcenterX
        + tcenterY
    )

    flag = struct.pack(">H", flag)

    rec = flag + numAxes + gid + axisIndices + axisValues + transform

    return rec
