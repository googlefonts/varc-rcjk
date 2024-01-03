def tuplifyLocation(loc):
    return tuple(sorted(loc.items()))


def dictifyLocation(loc):
    return {k: v for k, v in loc}


def glyphMasters(glyph):
    masters = {}
    for source in glyph.sources:
        if source.inactive:
            continue
        if not source.customData["fontra.development.status"]:
            continue
        locationTuple = tuplifyLocation(source.location)
        assert locationTuple not in masters, locationTuple
        masters[locationTuple] = glyph.layers[source.layerName]

    return masters
