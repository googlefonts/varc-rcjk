from fontTools.misc.roundTools import otRound
from fontTools.misc.fixedTools import floatToFixed as fl2fi
from fontTools.varLib.models import normalizeLocation
from fontTools.ttLib.tables.otTables import (
    VarComponent,
    VarComponentFlags,
    VarTransformFlags,
)
from fontTools.misc.transform import DecomposedTransform
from rcjkTools import *
import struct


class TransformHave:
    transform = DecomposedTransform()
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

    def getTransformFlags(self):
        flags = 0
        if self.transformHave.have_translateX:
            flags |= VarTransformFlags.HAVE_TRANSLATE_X
        if self.transformHave.have_translateY:
            flags |= VarTransformFlags.HAVE_TRANSLATE_Y
        if self.transformHave.have_rotation:
            flags |= VarTransformFlags.HAVE_ROTATION
        if self.transformHave.have_scaleX:
            flags |= VarTransformFlags.HAVE_SCALE_X
        if self.transformHave.have_scaleY:
            flags |= VarTransformFlags.HAVE_SCALE_Y
        if self.transformHave.have_skewX:
            flags |= VarTransformFlags.HAVE_SKEW_X
        if self.transformHave.have_skewY:
            flags |= VarTransformFlags.HAVE_SKEW_Y
        if self.transformHave.have_tcenterX:
            flags |= VarTransformFlags.HAVE_TCENTER_X
        if self.transformHave.have_tcenterY:
            flags |= VarTransformFlags.HAVE_TCENTER_Y

        return flags

    def getComponentFlags(self):
        flags = 0

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
            ca.transformHave.transform = t
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


def buildTransform(componentAnalysis):
    ca = componentAnalysis
    transform = DecomposedTransform()
    c = ca.transformHave
    if c.have_translateX:
        t.translateX
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


def buildComponentRecord(component, componentAnalysis):
    ca = componentAnalysis

    rec = VarComponent()
    rec.flags = ca.getComponentFlags()
    rec.glyphName = component.name

    return rec


def getComponentMasters(
    rcjkfont, component, componentGlyph, componentAnalysis, fvarTags, publicAxes
):
    ca = componentAnalysis

    componentAxes = {
        axis.name: (axis.minValue, axis.defaultValue, axis.maxValue)
        for axis in componentGlyph.axes
    }
    axesMap = {}
    i = 0
    for name in sorted(componentAxes.keys()):
        if name in publicAxes:
            axesMap[name] = name
        else:
            axesMap[name] = "%04d" % i
            i += 1

    coords = component.location
    coords = normalizeLocation(coords, componentAxes)

    axisIndexMasters, axisValueMasters, transformMasters = [], [], []

    for name in ca.coordinateHave:
        coord = coords.get(name, 0)
        i = fvarTags.index(axesMap[name])
        axisIndexMasters.append(i)
        axisValueMasters.append(fl2fi(coord, 14))
    if axisIndexMasters:
        # Sort them for better sharing
        axisIndexMasters, axisValueMasters = zip(
            *sorted(zip(axisIndexMasters, axisValueMasters))
        )

    c = ca.transformHave
    t = component.transformation
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

    return tuple(axisIndexMasters), tuple(axisValueMasters), tuple(transformMasters)
