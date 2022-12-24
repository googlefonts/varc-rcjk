
def tuplifyLocation(loc):
    return tuple(sorted(loc.items()))

def dictifyLocation(loc):
    return {k:v for k,v in loc}


def glyphMasters(glyph):

    layersByName = {}
    for layer in glyph.layers:
        layersByName[layer.name] = layer

    masters = {}
    for source in glyph.sources:
        locationTuple = tuplifyLocation(source.location)
        masters[locationTuple] = layersByName[source.layerName]

    return masters
