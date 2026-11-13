"""Roda DENTRO do Blender (modo background).

blender -b --factory-startup -P blender_ops.py -- <entrada.glb> <saida.ext> <ops.json>

ops.json: {"decimate": 0.5 | null, "remesh": {"mode": "voxel"|"quad", "value": n} | null,
           "height_cm": 20 | null, "base": {"height_mm": 3, "margin_mm": 5} | null,
           "ground": true}
A extensão da saída escolhe o formato: .glb .fbx .obj .stl .usdz .blend
"""
import json
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
src, dst, ops_path = argv[0], argv[1], argv[2]
with open(ops_path, encoding='utf-8') as f:
    ops = json.load(f)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)

meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    raise SystemExit('Nenhuma malha no arquivo de entrada')
bpy.ops.object.select_all(action='DESELECT')
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
# Solta de pais/vazios do glTF e aplica transformações
bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
for o in list(bpy.context.scene.objects):
    if o.type != 'MESH':
        bpy.data.objects.remove(o, do_unlink=True)
obj.name = 'Modelo'


def apply_mod(mod):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)


def bbox():
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


if ops.get('remesh'):
    r = ops['remesh']
    if r.get('mode') == 'quad':
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.quadriflow_remesh(target_faces=int(r.get('value', 5000)), use_preserve_sharp=True)
    else:
        m = obj.modifiers.new('Remesh', 'REMESH')
        m.mode = 'VOXEL'
        lo, hi = bbox()
        m.voxel_size = max((hi - lo)) / max(16, float(r.get('value', 128)))
        apply_mod(m)

if ops.get('decimate'):
    m = obj.modifiers.new('Decimate', 'DECIMATE')
    m.ratio = max(0.01, min(1.0, float(ops['decimate'])))
    apply_mod(m)

if ops.get('height_cm'):
    lo, hi = bbox()
    h = hi.z - lo.z
    if h > 0:
        s = (float(ops['height_cm']) / 100.0) / h
        obj.scale = (s, s, s)
        bpy.ops.object.transform_apply(scale=True)

if ops.get('ground', True):
    lo, hi = bbox()
    c = (lo + hi) / 2
    obj.location -= Vector((c.x, c.y, lo.z))
    bpy.ops.object.transform_apply(location=True)

if ops.get('base'):
    b = ops['base']
    lo, hi = bbox()
    radius = max(hi.x - lo.x, hi.y - lo.y) / 2 + float(b.get('margin_mm', 5)) / 1000
    depth = float(b.get('height_mm', 3)) / 1000
    bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=radius, depth=depth, location=(0, 0, -depth / 2))
    base = bpy.context.active_object
    base.name = 'Base'
    bpy.ops.object.select_all(action='DESELECT')
    base.select_set(True)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    lo, _ = bbox()
    obj.location.z -= lo.z
    bpy.ops.object.transform_apply(location=True)

bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
ext = dst.lower().rsplit('.', 1)[-1]
if ext == 'glb':
    bpy.ops.export_scene.gltf(filepath=dst, export_format='GLB', use_selection=True)
elif ext == 'fbx':
    bpy.ops.export_scene.fbx(filepath=dst, use_selection=True, path_mode='COPY', embed_textures=True)
elif ext == 'obj':
    bpy.ops.wm.obj_export(filepath=dst, export_selected_objects=True, path_mode='COPY')
elif ext == 'stl':
    bpy.ops.wm.stl_export(filepath=dst, export_selected_objects=True)
elif ext == 'usdz':
    bpy.ops.wm.usd_export(filepath=dst, selected_objects_only=True)
elif ext == 'blend':
    bpy.ops.wm.save_as_mainfile(filepath=dst)
else:
    raise SystemExit(f'Formato não suportado: {ext}')

lo, hi = bbox()
d = hi - lo
print('MIAU_RESULT ' + json.dumps({
    'faces': len(obj.data.polygons),
    'vertices': len(obj.data.vertices),
    'size_cm': [round(d.x * 100, 2), round(d.y * 100, 2), round(d.z * 100, 2)],
}))
