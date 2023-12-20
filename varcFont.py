from font import *
from rcjkTools import *
from flatFont import buildFlatGlyph
from component import *

from fontTools.ttLib import newTable
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates
from fontTools.varLib.models import normalizeLocation, VariationModel
from fontTools.varLib.multiVarStore import OnlineMultiVarStoreBuilder
import fontTools.ttLib.tables.otTables as ot
from fontTools.misc.vector import Vector
from functools import partial
from collections import defaultdict
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
    fvarTags = {axis[0] for axis in fvarAxes}
    fvarNames = {axis[4] for axis in fvarAxes}

    maxAxes = 0
    for glyph in glyphs.values():
        axes = {
            axis.name: (axis.minValue, axis.defaultValue, axis.maxValue)
            for axis in glyph.axes
            if axis.name not in fvarNames
        }
        maxAxes = max(maxAxes, len(axes))

    for i in range(maxAxes):
        tag = "%04d" % i
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

    fb = await createFontBuilder(rcjkfont, "rcjk", "varc", glyphs, glyphDataFormat=1)
    reverseGlyphMap = fb.font.getReverseGlyphMap()

    fbGlyphs = {".notdef": Glyph()}
    fbVariations = {}
    varcGlyphs = {}
    axisIndicesList = []
    axisIndicesMap = {}
    axisValuesList = []
    axisValuesMap = {}
    transformList = []
    transformMap = {}

    varStoreBuilder = OnlineMultiVarStoreBuilder(fvarTags)

    for glyphName, glyph in glyphs.items():
        print("Processing glyph", glyphName)
        glyph_masters = glyphMasters(glyph)

        axes = {
            axis.name: (axis.minValue, axis.defaultValue, axis.maxValue)
            for axis in glyph.axes
        }
        axesMap = {}
        i = 0
        for name in sorted(axes.keys()):
            if name in publicAxes:
                axesMap[name] = name
            else:
                axesMap[name] = "%04d" % i
                i += 1

        if not glyph_masters[()].glyph.components:
            # Simple glyph...

            fbGlyphs[glyph.name], fbVariations[glyph.name] = await buildFlatGlyph(
                rcjkfont, glyph, axesMap
            )
            continue

        # VarComposite glyph...

        fbGlyphs[glyph.name] = Glyph()

        componentAnalysis = analyzeComponents(glyph_masters, glyphs, axes, publicAxes)

        glyphRecord = varcGlyphs[glyph.name] = ot.VarCompositeGlyph()
        glyphRecord.populateDefaults()
        componentRecords = glyphRecord.components

        layer = next(iter(glyph_masters.values()))  # Default master
        assert len(layer.glyph.components) == len(componentAnalysis), (len(layer.glyph.components), len(componentAnalysis))
        for component, ca in zip(layer.glyph.components, componentAnalysis):
            rec = VarComponent()
            rec.flags = ca.getComponentFlags()
            rec.glyphName = component.name
            componentRecords.append(rec)

        #
        # Build variations
        #

        masterLocs = list(dictifyLocation(l) for l in glyph_masters.keys())
        masterLocs = [normalizeLocation(m, axes) for m in masterLocs]
        masterLocs = [{axesMap[k]: v for k, v in loc.items()} for loc in masterLocs]

        model = VariationModel(masterLocs, list(axes.keys()))

        assert len(componentRecords) == len(componentAnalysis), (
            len(componentRecords),
            len(componentAnalysis),
        )
        for ci, (rec, ca) in enumerate(zip(componentRecords, componentAnalysis)):
            allAxisIndexMasterValues = []
            allAxisValueMasterValues = []
            allTransformMasterValues = []
            for loc, layer in glyph_masters.items():
                component = layer.glyph.components[ci]

                (
                    axisIndexMasters,
                    axisValueMasters,
                    transformMasters,
                ) = getComponentMasters(
                    rcjkfont,
                    component,
                    glyphs[component.name],
                    ca,
                    fvarTags,
                    publicAxes,
                )
                allAxisIndexMasterValues.append(axisIndexMasters)
                allAxisValueMasterValues.append(axisValueMasters)
                allTransformMasterValues.append(transformMasters)

            allAxisIndexMasterValues = tuple(allAxisIndexMasterValues)
            allAxisValueMasterValues = tuple(allAxisValueMasterValues)
            allTransformMasterValues = tuple(allTransformMasterValues)

            axisIndexMasterValues = allAxisIndexMasterValues[0]
            assert all(axisIndexMasterValues == m for m in allAxisIndexMasterValues)
            if axisIndexMasterValues:
                if axisIndexMasterValues in axisIndicesMap:
                    idx = axisIndicesMap[axisIndexMasterValues]
                else:
                    idx = len(axisIndicesList)
                    axisIndicesList.append(axisIndexMasterValues)
                    axisIndicesMap[axisIndexMasterValues] = idx
                rec.AxisIndicesIndex = idx
            else:
                rec.AxisIndicesIndex = None

            if rec.AxisIndicesIndex is not None:
                if allAxisValueMasterValues in axisValuesMap:
                    idx = axisValuesMap[allAxisValueMasterValues]
                else:
                    idx = len(axisValuesList)
                    axisValuesList.append((model, allAxisValueMasterValues))
                    axisValuesMap[allAxisValueMasterValues] = idx
                rec.AxisValuesIndex = idx
            else:
                rec.AxisValuesIndex = None

            transformMasterValues = allTransformMasterValues[0]
            if transformMasterValues or not all(
                transformMasterValues == m for m in allTransformMasterValues
            ):
                if allTransformMasterValues in transformMap:
                    idx = transformMap[allTransformMasterValues]
                else:
                    idx = len(transformList)
                    transformList.append(
                        (
                            model,
                            allTransformMasterValues,
                            ca.getTransformFlags(),
                        )
                    )
                    transformMap[allTransformMasterValues] = idx
                rec.TransformIndex = idx
            else:
                rec.TransformIndex = None

    axisIndices = ot.AxisIndicesList()
    axisIndices.Item = axisIndicesList
    print("AxisIndicesList:", len(axisIndicesList))

    axisValues = ot.AxisValuesList()
    axisValues.VarIndices = []
    axisValues.Item = [l[1][0] for l in axisValuesList]
    # Store the rest in the varStore
    for model, lst in axisValuesList:
        varStoreBuilder.setModel(model)
        axisValues.VarIndices.append(
            varStoreBuilder.storeMasters(
                [Vector(l) for l in lst], round=Vector.__round__
            )[1]
        )

    # Reorder the axisValuesList to put all the NO_VARIATION_INDEX values at the end
    # so we don't have to encode them.
    mapping = sorted(
        range(len(axisValues.VarIndices)), key=lambda i: axisValues.VarIndices[i]
    )
    axisValues.VarIndices = [axisValues.VarIndices[i] for i in mapping]
    axisValues.Item = [axisValues.Item[i] for i in mapping]
    reverseMapping = {mapping[i]: i for i in range(len(mapping))}
    for rec in varcGlyphs.values():
        for comp in rec.components:
            if comp.AxisValuesIndex is not None:
                comp.AxisValuesIndex = reverseMapping[comp.AxisValuesIndex]
    while axisValues.VarIndices and axisValues.VarIndices[-1] == ot.NO_VARIATION_INDEX:
        axisValues.VarIndices.pop()

    axisValues.VarIndicesCount = len(axisValues.VarIndices)
    print("AxisValuesList:", len(axisValues.Item), len(axisValues.VarIndices))

    transforms = ot.TransformList()
    transforms.VarTransform = []
    for model, lst, flags in transformList:
        varStoreBuilder.setModel(model)
        t = ot.VarTransform()
        t.flags = flags
        t.transform.scaleX = t.transform.scaleY = 0
        t.applyDeltas(lst[0])
        t.varIndex = varStoreBuilder.storeMasters(
            [Vector(l) for l in lst], round=Vector.__round__
        )[1]
        if t.varIndex == ot.NO_VARIATION_INDEX:
            t.flags &= ~VarTransformFlags.HAVE_VARIATIONS
        else:
            t.flags |= VarTransformFlags.HAVE_VARIATIONS
        transforms.VarTransform.append(t)
    print("TransformList:", len(transforms.VarTransform))

    varStore = varStoreBuilder.finish()

    varCompositeGlyphs = ot.VarCompositeGlyphs()
    varCompositeGlyphs.VarCompositeGlyph = list(varcGlyphs.values())

    varc = newTable("VARC")
    varcTable = varc.table = ot.VARC()
    varcTable.Version = 0x00010000

    coverage = varcTable.Coverage = ot.Coverage()
    coverage.glyphs = [glyph for glyph in varcGlyphs.keys()]

    varcTable.MultiVarStore = varStore
    varcTable.AxisIndicesList = axisIndices
    varcTable.AxisValuesList = axisValues
    varcTable.TransformList = transforms
    varcTable.VarCompositeGlyphs = varCompositeGlyphs

    fb.setupFvar(fvarAxes, [])
    fb.setupGlyf(fbGlyphs, validateGlyphFormat=False)
    fb.setupGvar(fbVariations)
    recalcSimpleGlyphBounds(fb)
    fixLsb(fb)
    fb.font["VARC"] = varc
    print("Saving varc.ttf")
    fb.save("varc.ttf")
