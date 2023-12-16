from fontTools.misc.roundTools import otRound
from fontTools.misc.fixedTools import floatToFixed as fl2fi
from fontTools.varLib.models import normalizeLocation
from fontTools.ttLib.tables.otTables import VarComponent, VarComponentFlags
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
        self.transformVaries = False

    def getFlags(self):
        flags = 0
        if self.transformHave.have_translateX:
            flags |= VarComponentFlags.HAVE_TRANSLATE_X
        if self.transformHave.have_translateY:
            flags |= VarComponentFlags.HAVE_TRANSLATE_Y
        if self.transformHave.have_rotation:
            flags |= VarComponentFlags.HAVE_ROTATION
        if self.transformHave.have_scaleX:
            flags |= VarComponentFlags.HAVE_SCALE_X
        if self.transformHave.have_scaleY:
            flags |= VarComponentFlags.HAVE_SCALE_Y
        if self.transformHave.have_skewX:
            flags |= VarComponentFlags.HAVE_SKEW_X
        if self.transformHave.have_skewY:
            flags |= VarComponentFlags.HAVE_SKEW_Y
        if self.transformHave.have_tcenterX:
            flags |= VarComponentFlags.HAVE_TCENTER_X
        if self.transformHave.have_tcenterY:
            flags |= VarComponentFlags.HAVE_TCENTER_Y

        if self.transformVaries:
            flags |= VarComponentFlags.TRANSFORM_HAS_VARIATION
        if self.coordinateVaries:
            flags |= VarComponentFlags.AXIS_VALUES_HAVE_VARIATION
        if self.coordinatesReset:
            flags |= VarComponentFlags.RESET_UNSPECIFIED_AXES

        return flags


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
            if t != defaultComponents[i].transformation:
                ca.transformVaries = True
            if otRound(t.translateX):
                ca.transformHave.have_translateX = True
            if otRound(t.translateY):
                ca.transformHave.have_translateY = True
            if fl2fi(t.rotation / 180.0, 12):
                ca.transformHave.have_rotation = True
            if fl2fi(t.scaleX, 10) != 1 << 10:
                ca.transformHave.have_scaleX = True
            if fl2fi(t.scaleY, 10) != 1 << 10 and fl2fi(t.scaleY, 10) != fl2fi(
                t.scaleX, 10
            ):
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

    for layer in list(glyph_masters.values())[1:]:
        for i, component in enumerate(layer.glyph.components):
            ca = cas[i]
            loc = component.location
            loc = normalizeLocation(loc, allComponentAxes[i])
            for tag in ca.coordinates:
                # XXX Is this logic correct for coordinatesReset?
                if tag in ca.coordinateHave and loc.get(tag, 0) != defaultLocations[
                    i
                ].get(tag, 0):
                    ca.coordinateVaries = True

    return cas


def buildComponentRecord(component, componentGlyph, componentAnalysis, fvarTags):
    ca = componentAnalysis

    componentAxes = {
        axis.name: (axis.minValue, axis.defaultValue, axis.maxValue)
        for axis in componentGlyph.axes
    }
    coords = component.location
    coords = normalizeLocation(coords, componentAxes)

    axesMap = {}
    for i, name in enumerate(componentAxes):
        axesMap[name] = "%04d" % i if name not in fvarTags else name

    rec = VarComponent()
    rec.glyphName = component.name
    rec.transform = component.transformation
    rec.location = {axesMap[tag]: coords.get(tag, 0) for tag in componentAxes if tag in ca.coordinateHave}
    if not rec.location:
        assert not ca.coordinateVaries
    rec.flags = ca.getFlags()

    return rec


def getComponentMasters(rcjkfont, component, componentGlyph, componentAnalysis):
    ca = componentAnalysis

    componentAxes = {
        axis.name: (axis.minValue, axis.defaultValue, axis.maxValue)
        for axis in componentGlyph.axes
    }
    coords = component.location
    coords = normalizeLocation(coords, componentAxes)

    t = component.transformation

    coordinateMasters, transformMasters = [], []

    if ca.coordinateVaries:
        for tag in componentAxes:
            if tag in ca.coordinateHave:
                coord = coords.get(tag, 0)
                coordinateMasters.append(fl2fi(coord, 14))

    if ca.transformVaries:
        c = ca.transformHave
        if c.have_translateX:
            transformMasters.append(otRound(t.translateX))
        if c.have_translateY:
            transformMasters.append(otRound(t.translateY))
        if c.have_rotation:
            transformMasters.append(fl2fi(t.rotation / 180.0, 12))
        if c.have_scaleX:
            transformMasters.append(fl2fi(t.scaleX, 10))
        if c.have_scaleY:
            transformMasters.append(fl2fi(t.scaleY, 10))
        if c.have_skewX:
            transformMasters.append(fl2fi(t.skewX / 180.0, 12))
        if c.have_skewY:
            transformMasters.append(fl2fi(t.skewY / 180.0, 12))
        if c.have_tcenterX:
            transformMasters.append(otRound(t.tCenterX))
        if c.have_tcenterY:
            transformMasters.append(otRound(t.tCenterY))

    return coordinateMasters, transformMasters
