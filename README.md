# IGI 2 MEF Parsing Library (`igi2mef`)

A high-performance, specification-driven Python library for parsing **IGI 2: Covert Strike** binary `.mef` models.

## Features
- **Precise Parsing**: Optimized for Rigid, Bone, Lightmap, and Shadow models.
- **Exhaustive Specs**: Includes `guidemef.md`, the master reference for the MEF format.
- **Production Ready**: Clean API for developers to build viewers, converters, or engine mods.

## Installation

### From Source
1. Clone this repository.
2. Install in editable mode:
   ```bash
   pip install -e .
   ```

### From PyPI (Coming Soon)
```bash
pip install igi2mef
```

## Quick Start
```python
from igi2mef import parse_mef

# Load a model
model = parse_mef("path/to/model.mef")

# Access geometry
print(f"Model Type: {model.header.type}")
for mesh in model.meshes:
    print(f"Mesh has {len(mesh.vertices)} vertices.")
```

## Documentation
Check [guidemef.md](guidemef.md) for a complete byte-level breakdown of the MEF format.

## License
MIT License.
