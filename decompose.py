from transform import composeTransform, Identity
from mathRecording import MathRecording
from rcjkTools import *

from fontTools.pens.recordingPen import RecordingPointPen
from fontTools.pens.transformPen import TransformPointPen
from fontTools.varLib.models import normalizeLocation, VariationModel
from fontTools.misc.vector import Vector

async def decomposeGlyph(glyph, rcjkfont, location=(), trans=Identity):
    value = []
    axes = {axis.name:(axis.minValue,axis.defaultValue,axis.maxValue)
            for axis in glyph.axes}

    glyph_masters = glyphMasters(glyph)

    masterLocs = list(dictifyLocation(l)
                      for l in glyph_masters.keys())
    masterLocs = [normalizeLocation(m, axes)
                  for m in masterLocs]

    model = VariationModel(masterLocs, list(axes.keys()))


    # Interpolate outline

    masterShapes = [await decomposeLayer(layer, rcjkfont, trans, shallow=True)
                    for layer in glyph_masters.values()]

    loc = normalizeLocation(location, axes)
    shape = model.interpolateFromMasters(loc, masterShapes)

    value.extend(shape.value)

    # Interpolate components

    numComps = len(next(iter(glyph_masters.values())).glyph.components)
    for compIndex in range(numComps):
        compTransforms = []
        compLocations = []
        name = None
        for layer in glyph_masters.values():
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

        componentGlyph = await rcjkfont.getGlyph(name)
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

        componentGlyph = await rcjkfont.getGlyph(component.name)

        value.extend((await decomposeGlyph(componentGlyph, rcjkfont, component.location, composedTrans)).value)

    return MathRecording(value)

