"""Generate original, dependency-free glTF cups in meters (Y-up, base at Y=0)."""
import json
import math
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'frontend' / 'assets' / 'models'


def cup(filename, height, bottom_radius, top_radius):
    positions, normals, indices, primitives = [], [], [], []

    def ring_segment(y0, y1, r0, r1, material):
        first_vertex, first_index = len(positions) // 3, len(indices)
        slope = (r0 - r1) / max(y1 - y0, 0.0001)
        length = math.sqrt(1 + slope * slope)
        for y, radius in [(y0, r0), (y1, r1)]:
            for i in range(65):
                angle = i * math.tau / 64
                positions.extend([radius * math.cos(angle), y, radius * math.sin(angle)])
                normals.extend([math.cos(angle) / length, slope / length, math.sin(angle) / length])
        for i in range(64):
            a, b = first_vertex + i, first_vertex + i + 65
            indices.extend([a, b, a + 1, a + 1, b, b + 1])
        primitives.append((first_index, len(indices) - first_index, material))

    def disc(y, radius, top, material):
        first_vertex, first_index = len(positions) // 3, len(indices)
        positions.extend([0, y, 0])
        normals.extend([0, 1 if top else -1, 0])
        for i in range(65):
            angle = i * math.tau / 64
            positions.extend([radius * math.cos(angle), y, radius * math.sin(angle)])
            normals.extend([0, 1 if top else -1, 0])
        for i in range(64):
            triangle = [first_vertex, first_vertex + i + 2, first_vertex + i + 1]
            indices.extend(triangle if top else triangle[::-1])
        primitives.append((first_index, len(indices) - first_index, material))

    def radius_at(y):
        return bottom_radius + (top_radius - bottom_radius) * y / height

    ring_segment(0, height, bottom_radius, top_radius, 0)
    ring_segment(height * .30, height * .72, radius_at(height * .30) + .0003, radius_at(height * .72) + .0003, 1)
    disc(0, bottom_radius, False, 0)
    ring_segment(height, height + .006, top_radius + .003, top_radius + .003, 2)
    disc(height + .006, top_radius + .003, True, 2)
    ring_segment(height + .006, height + .010, top_radius * .93, top_radius * .90, 2)
    disc(height + .010, top_radius * .90, True, 2)

    position_bytes = struct.pack('<' + 'f' * len(positions), *positions)
    normal_bytes = struct.pack('<' + 'f' * len(normals), *normals)
    index_bytes = struct.pack('<' + 'H' * len(indices), *indices)
    binary = position_bytes + normal_bytes + index_bytes
    accessors = [
        {'bufferView': 0, 'componentType': 5126, 'count': len(positions) // 3, 'type': 'VEC3',
         'min': [min(positions[i::3]) for i in range(3)], 'max': [max(positions[i::3]) for i in range(3)]},
        {'bufferView': 1, 'componentType': 5126, 'count': len(normals) // 3, 'type': 'VEC3'},
    ]
    meshes = []
    for start, count, material in primitives:
        accessors.append({'bufferView': 2, 'byteOffset': start * 2, 'componentType': 5123, 'count': count, 'type': 'SCALAR'})
        meshes.append({'attributes': {'POSITION': 0, 'NORMAL': 1}, 'indices': len(accessors) - 1, 'material': material})
    document = {
        'asset': {'version': '2.0', 'generator': 'Altitude Pulse original cup generator'},
        'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0, 'name': filename.removesuffix('.glb')}],
        'meshes': [{'primitives': meshes}],
        'materials': [{'name': name, 'pbrMetallicRoughness': {'baseColorFactor': color, 'metallicFactor': 0, 'roughnessFactor': .8}}
                      for name, color in [('Paper', [.82, .77, .64, 1]), ('Pulse sleeve', [.59, .78, .29, 1]), ('Lid', [.06, .09, .04, 1])]],
        'buffers': [{'byteLength': len(binary)}],
        'bufferViews': [
            {'buffer': 0, 'byteOffset': 0, 'byteLength': len(position_bytes), 'target': 34962},
            {'buffer': 0, 'byteOffset': len(position_bytes), 'byteLength': len(normal_bytes), 'target': 34962},
            {'buffer': 0, 'byteOffset': len(position_bytes) + len(normal_bytes), 'byteLength': len(index_bytes), 'target': 34963}],
        'accessors': accessors,
        'extras': {'units': 'meters', 'note': 'Illustrative cafe cup dimensions, not a certified capacity measurement.'},
    }
    encoded = json.dumps(document, separators=(',', ':')).encode()
    encoded += b' ' * (-len(encoded) % 4)
    binary += b'\x00' * (-len(binary) % 4)
    result = struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(encoded) + 8 + len(binary))
    result += struct.pack('<I4s', len(encoded), b'JSON') + encoded
    result += struct.pack('<I4s', len(binary), b'BIN\x00') + binary
    (ROOT / filename).write_bytes(result)
    print(f'{filename}: {len(result)} bytes; {height + .010:.3f} m tall')


if __name__ == '__main__':
    ROOT.mkdir(parents=True, exist_ok=True)
    cup('cup_12oz.glb', .110, .028, .044)
    cup('cup_16oz.glb', .135, .030, .045)
