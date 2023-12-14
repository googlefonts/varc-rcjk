# pip install git+https://github.com/BlackFoundryCom/fontra.git
# pip install git+https://github.com/BlackFoundryCom/fontra-rcjk.git

# See src/fontra/core/classes.py in the fontra repo for the data structure
# PackedPath objects have a drawPoints method that takes a point pen


import argparse
import asyncio
from dataclasses import asdict
import json
import sys
from fontra_rcjk.backend_fs import RCJKBackend


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("rcjk_path")
    parser.add_argument("glyph_name")
    args = parser.parse_args()
    backend = RCJKBackend.fromPath(args.rcjk_path)
    revCmap = await backend.getGlyphMap()
    print(sorted(revCmap)[:100])
    glyph = await backend.getGlyph(args.glyph_name)
    print(json.dumps(asdict(glyph), indent=2))


asyncio.run(main())
