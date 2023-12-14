def tuplifyLocation(loc):
    return tuple(sorted(loc.items()))


def dictifyLocation(loc):
    return {k: v for k, v in loc}


def glyphMasters(glyph):
    masters = {}
    for source in glyph.sources:
        locationTuple = tuplifyLocation(source.location)
        assert locationTuple not in masters
        masters[locationTuple] = glyph.layers[source.layerName]

    return masters
