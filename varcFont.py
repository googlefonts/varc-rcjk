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
        print("Processing varc glyph", glyphName)
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
        componentRecords = glyphRecord.components

        layer = next(iter(glyph_masters.values()))  # Default master
        assert len(layer.glyph.components) == len(componentAnalysis), (
            len(layer.glyph.components),
            len(componentAnalysis),
        )
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
        varStoreBuilder.setModel(model)

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
            rec.numAxes = len(axisIndexMasterValues)
            if axisIndexMasterValues:
                if axisIndexMasterValues in axisIndicesMap:
                    idx = axisIndicesMap[axisIndexMasterValues]
                else:
                    idx = len(axisIndicesList)
                    axisIndicesList.append(axisIndexMasterValues)
                    axisIndicesMap[axisIndexMasterValues] = idx
                rec.axisIndicesIndex = idx
            else:
                rec.axisIndicesIndex = None

            axisValues, rec.axisValuesVarIndex = varStoreBuilder.storeMasters(
                [Vector(l) for l in allAxisValueMasterValues], round=Vector.__round__
            )
            rec.axisValues = tuple(axisValues)

            transformBase, rec.transformVarIndex = varStoreBuilder.storeMasters(
                [Vector(l) for l in allTransformMasterValues], round=Vector.__round__
            )
            rec.axisValues = tuple(axisValues)
            rec.transform.scaleX = rec.transform.scaleY = 0
            rec.applyTransformDeltas(transformBase)

    # Reorder axisIndices such that the more used ones come first
    # Count users first.
    axisIndicesUsers = [0] * len(axisIndicesList)
    for glyph in varcGlyphs.values():
        for component in glyph.components:
            if component.axisIndicesIndex is not None:
                axisIndicesUsers[component.axisIndicesIndex] += 1
    # Then sort by usage
    mapping = sorted(range(len(axisIndicesList)), key=lambda i: -axisIndicesUsers[i])
    axisIndicesList = [axisIndicesList[i] for i in mapping]
    reverseMapping = {mapping[i]: i for i in range(len(mapping))}
    # Then remap axisIndicesIndex
    for glyph in varcGlyphs.values():
        for component in glyph.components:
            if component.axisIndicesIndex is not None:
                component.axisIndicesIndex = reverseMapping[component.axisIndicesIndex]

    axisIndices = ot.AxisIndicesList()
    axisIndices.Item = axisIndicesList
    print("AxisIndicesList:", len(axisIndicesList))

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
    varcTable.VarCompositeGlyphs = varCompositeGlyphs

    fb.setupFvar(fvarAxes, [])
    fb.setupGlyf(fbGlyphs, validateGlyphFormat=False)
    fb.setupGvar(fbVariations)
    recalcSimpleGlyphBounds(fb)
    fixLsb(fb)
    fb.font["VARC"] = varc
    print("Saving varc.ttf")
    fb.save("varc.ttf")
