from varcFont import *

from fontTools.varLib.models import normalizeLocation, VariationModel
from fontTools.misc.vector import Vector

import numpy as np

from collections import defaultdict
from copy import deepcopy


async def buildSmartiesFont(rcjkfont, glyphs):

    print("Learning smarties.ttf")

    glyphs = deepcopy(glyphs)

    await closureGlyphs(rcjkfont, glyphs)

    revCmap = await rcjkfont.getReverseCmap()


    # Collect all Deep Components

    deepComponents = {}
    dcLocations = defaultdict(list)
    for glyphname,glyph in glyphs.items():
        if not glyphname.startswith("DC_"): continue

        assert not revCmap[glyphname] # Deep Components should not be mapped

        deepComponents[glyphname] = glyph


    # Collect all references to deepComponents with their coordinates

    for glyph in glyphs.values():

        glyph_masters = glyphMasters(glyph)
        for layer in glyph_masters.values():

            for component in layer.glyph.components:
                if component.name not in deepComponents: continue

                dcLocations[component.name].append(component.location)

    # Learn
    learned = {}
    for dcName,locations in dcLocations.items():

        glyph = await rcjkfont.getGlyph(dcName)

        axes = {axis.name:(axis.minValue,axis.defaultValue,axis.maxValue)
                for axis in glyph.axes}

        glyph_masters = glyphMasters(glyph)

        masterLocs = list(dictifyLocation(l)
                          for l in glyph_masters.keys())
        masterLocs = [normalizeLocation(m, axes)
                      for m in masterLocs]

        model = VariationModel(masterLocs, list(axes.keys()))

        numComps = len(next(iter(glyph_masters.values())).glyph.components)

        samples = []
        for location in locations:
            sample = []

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
                for cLocations in compLocations:
                    assert locKeys == list(cLocations.keys())
                    locationVectors.append(Vector(cLocations.values()))
                transformVectors = []
                for t in compTransforms:
                    transformVectors.append(Vector((t.translateX, t.translateY,
                                                    t.rotation,
                                                    t.scaleX, t.scaleY,
                                                    t.skewX, t.skewY,
                                                    t.tCenterX, t.tCenterY)))

                loc = normalizeLocation(location, axes)
                locationVector = model.interpolateFromMasters(loc, locationVectors)
                transformVector = model.interpolateFromMasters(loc, transformVectors)

                sample.extend(locationVector)
                sample.extend(transformVector)

            samples.append(sample)

        mat = np.matrix(samples)
        u,s,v = np.linalg.svd(mat, full_matrices=False)

        # Find number of "masters" to keep
        first = s[0] # Largest singular value
        k = len(s)
        while k and s[k - 1] < first / 1000:
            k -= 1

        # Truncate rank to k
        u = u[:,:k]
        s = s[:k]
        v = v[:k,:]

        reconst = np.round(u * np.diag(s) * v)
        error = reconst - mat
        maxError = np.max(np.abs(error))
        meanSqError = np.mean(np.square(error))
        print("%s: #samples %d #orig masters %d #masters %d max-err %g mean^2-err %g" % (dcName, len(samples), len(location), k, maxError, meanSqError))

        # Multiply extracted features by singular values and be done with those values.
        v = np.diag(s) * v
        del s

        # v contains the list of "master"-like features discovered, one in each row, and
        # u contains the "location" of those, one row per sample.

        # Normalize range of each "axis" to 0-1; This extracts default master and deltas
        defaultMaster = np.zeros(np.shape(v[0]))
        for j in range(k):
            minV = np.min(u[:,j])
            maxV = np.max(u[:,j])
            diff = maxV - minV

            u[:,j] -= minV
            if diff:
                u[:,j] /= diff

            defaultMaster += v[j,:] * minV
            v[j,:] *= diff
        # Convert deltas to masters
        for j in range(k):
            v[j,:] += defaultMaster

        # Save learned locations
        learned[dcName] = {}
        for location,vec in zip(locations,u):
            learned[dcName][tuplifyLocation(location)] = {"% 4d"%(i+1):l for i,l in enumerate(vec.tolist()[0])}

        # Setup new axes
        newAxes = []
        for j in range(k):
            tag = "% 4d" % (j+1)
            newAxis = type(glyph.axes[0])(tag, 0., 0., 1.)
            newAxes.append(newAxis)

        # Construct new glyph

        newGlyph = type(glyph)(glyph.name)
        newGlyph.axes = newAxes
        for i,newMasterRow in enumerate(np.concatenate((defaultMaster, v), 0)):
            newMasterRow = newMasterRow.tolist()[0]

            name = "master%d" % i
            newSource = type(glyph.sources[0])(name if i else "<default>", name if i else "foreground")

            newLocation = {"% 4d" % i: 1} if i else {}
            newSource.location = newLocation

            newLayerGlyph = type(glyph.layers[0].glyph)()
            newLayer = type(glyph.layers[0])(name if i else "foreground", newLayerGlyph)

            newGlyph.sources.append(newSource)
            newGlyph.layers.append(newLayer)

            # Fill in layer components
            for compIndex in range(numComps):
                referenceComponent = glyph.layers[0].glyph.components[compIndex]
                component = type(referenceComponent)(referenceComponent.name)
                newLayerGlyph.components.append(component)

                locationLen = len(referenceComponent.location)
                component.location = {tag:l for tag,l in zip(referenceComponent.location.keys(), newMasterRow[:locationLen])}
                newMasterRow = newMasterRow[locationLen:]

                t = newMasterRow[:9]
                newMasterRow = newMasterRow[9:]
                component.transformation = type(referenceComponent.transformation)()
                component.transformation.translateX = t[0]
                component.transformation.translateY = t[1]
                component.transformation.rotation = t[2]
                component.transformation.scaleX = t[3]
                component.transformation.scaleY = t[4]
                component.transformation.skewX = t[5]
                component.transformation.skewY = t[6]
                component.transformation.tCenterX = t[7]
                component.transformation.tCenterY = t[8]
            assert(not newMasterRow)

        glyphs[glyph.name] = newGlyph

    # Update component references
    for glyph in glyphs.values():

        glyph_masters = glyphMasters(glyph)
        for layer in glyph_masters.values():

            for component in layer.glyph.components:
                if component.name not in learned: continue

                component.location = learned[component.name][tuplifyLocation(component.location)]

    await buildVarcFont(rcjkfont, glyphs, "smarties")
