# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistent mesh backup and original custom-normal storage."""

import json

from .core import topology_hash

BASE = ".fnf_original_corner_normal"
RAW = ".fnf_original_normal_storage"
WEIGHT = "FNF_Weight"
STATE = "fnf_backup_v1"


def signature(mesh):
    return topology_hash(len(mesh.vertices), [tuple(e.vertices) for e in mesh.edges],
                         [tuple(p.vertices) for p in mesh.polygons])


def read_backup(obj):
    me = obj.data
    if STATE not in me:
        return None
    state = json.loads(me[STATE])
    attr = me.attributes.get(BASE)
    if (state['topology'] != signature(me) or not attr
            or attr.data_type != 'FLOAT_VECTOR' or attr.domain != 'CORNER'
            or len(attr.data) != len(me.loops)):
        raise ValueError("网格拓扑已变化，原法线备份不能安全映射。请撤销拓扑修改或使用文件备份。")
    if me.users > 1:
        raise ValueError("此网格被多个物体共用，请先设为单用户数据。")
    raw = me.attributes.get(RAW)
    actual_format = (raw.data_type, raw.domain) if raw else (None, None)
    if actual_format != (state.get('storage_type'), state.get('storage_domain')):
        raise ValueError("原始法线编码备份已缺失或损坏，请使用完整文件备份恢复。")
    return state


def snapshot(obj):
    me = obj.data
    state = read_backup(obj)
    if state:
        return state
    if me.users > 1:
        raise ValueError("此网格被多个物体共用，请先设为单用户数据。")
    if any(me.attributes.get(n) for n in (BASE, RAW, WEIGHT)):
        raise ValueError("已有同名 FNF 属性但没有有效备份，请先重命名该属性。")
    normals = [tuple(n.vector) for n in me.corner_normals]
    state = {"topology": signature(me), "owner": obj.name,
             "custom_normals": me.has_custom_normals,
             "normal_modifiers": [{"name": m.name, "viewport": m.show_viewport,
                                   "render": m.show_render}
                                  for m in obj.modifiers if m.type == 'NORMAL_EDIT']}
    raw = read_raw_normals(me)
    try:
        if raw is not None:
            state['storage_type'], state['storage_domain'] = raw[:2]
            write_raw_normals(me, raw, RAW)
        attr = me.attributes.new(BASE, 'FLOAT_VECTOR', 'CORNER')
        attr.data.foreach_set('vector', [c for n in normals for c in n])
        me[STATE] = json.dumps(state)
    except Exception:
        discard_backup(me)
        raise
    return state


def discard_backup(mesh):
    """Remove the backup attributes and metadata owned by this workflow."""
    for name in (BASE, RAW):
        attr = mesh.attributes.get(name)
        if attr:
            mesh.attributes.remove(attr)
    if STATE in mesh:
        del mesh[STATE]


def read_raw_normals(mesh, name="custom_normal"):
    attr = mesh.attributes.get(name)
    if not attr:
        return None
    field = 'vector' if attr.data_type == 'FLOAT_VECTOR' else 'value'
    return (attr.data_type, attr.domain, field,
            [tuple(getattr(item, field)) for item in attr.data])


def write_raw_normals(mesh, saved, name="custom_normal"):
    attr = mesh.attributes.get(name)
    if attr:
        mesh.attributes.remove(attr)
    if saved:
        kind, domain, field, values = saved
        attr = mesh.attributes.new(name, kind, domain)
        for item, value in zip(attr.data, values):
            setattr(item, field, value)
    mesh.update()


def restore_base_normals(mesh, state):
    """Restore original storage while retaining the persistent backup."""
    raw = read_raw_normals(mesh, RAW)
    if raw is None and state['custom_normals']:
        mesh.normals_split_custom_set([tuple(x.vector) for x in mesh.attributes[BASE].data])
        mesh.update()
    else:
        write_raw_normals(mesh, raw)
