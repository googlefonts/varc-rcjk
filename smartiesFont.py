from varcFont import *

from fontTools.varLib.models import normalizeLocation, VariationModel
from fontTools.misc.vector import Vector

import numpy as np

from collections import defaultdict


async def buildSmartiesFont(rcjkfont, glyphs):

    print("Learning smarties.ttf")

    #glyphs = glyphs.copy ()

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
        while k and s[k - 1] < first / 500:
            k -= 1

        # Truncate rank to k
        u = u[:,:k]
        s = s[:k]
        v = v[:k,:]

        reconst = np.round(u * np.diag(s) * v)
        error = reconst - mat
        maxError = np.max(error)
        meanSqError = np.mean(np.square(error))
        print("Num samples %d num masters %d max error %d mean-squared error %g" % (len(samples), k, maxError, meanSqError))

        # Multiply extracted features by singular values and be done with those values.
        v = np.diag(s) * v
        del s




    await buildVarcFont(rcjkfont, glyphs, "smarties")
