# SPDX-License-Identifier: GPL-3.0-or-later
"""Map the selected Blender face region to the pure geometry solver and back."""

from mathutils import Vector

from .backup import BASE, WEIGHT, read_backup
from .core import flatten_normals


def calculate_flatten(obj, settings=None):
    """Validate and calculate the common transition without mutating Blender data."""
    if obj.type != 'MESH' or obj.mode != 'OBJECT':
        raise ValueError("请在物体模式选择独立的脸部网格。")
    settings = settings or obj.fnf_settings
    me = obj.data
    weight = me.attributes.get(WEIGHT)
    if weight and (weight.data_type != 'FLOAT' or weight.domain != 'POINT'
                   or len(weight.data) != len(me.vertices)):
        raise ValueError("FNF_Weight 属性已被改为不兼容类型，请先恢复原始法线或修复该属性。")
    # Validate inputs and topology before storing anything.
    old_state = read_backup(obj)
    if old_state:
        normals = [tuple(x.vector) for x in me.attributes[BASE].data]
    else:
        normals = [tuple(n.vector) for n in me.corner_normals]
    polygons = list(me.polygons)
    if settings.region_group:
        region_group = obj.vertex_groups.get(settings.region_group)
        if region_group is None:
            raise ValueError("作用范围顶点组不存在。")
        included = {v.index for v in me.vertices if any(
            g.group == region_group.index and g.weight > 0.5 for g in v.groups)}
        polygons = [p for p in polygons if all(i in included for i in p.vertices)]
        if not polygons:
            raise ValueError("作用范围中没有完整面片（需要顶点组权重大于 0.5）。")
    ids = sorted({i for p in polygons for i in p.vertices})
    remap = {i: j for j, i in enumerate(ids)}
    corner_ids = [i for p in polygons for i in p.loop_indices]
    axes = {'X': (1,0,0), 'NEG_X': (-1,0,0), 'Y': (0,1,0),
            'NEG_Y': (0,-1,0), 'Z': (0,0,1), 'NEG_Z': (0,0,-1)}
    if settings.direction == 'CUSTOM':
        forward = Vector(settings.custom_forward)
        if forward.length < 1e-8:
            raise ValueError("自定义朝向不能为零向量。")
        forward.normalize()
    else:
        forward = Vector(axes[settings.direction])
    protected = None
    if settings.root_group:
        group = obj.vertex_groups.get(settings.root_group)
        if group is None:
            raise ValueError("指定的根部顶点组不存在。")
        protected = [remap[v.index] for v in me.vertices if v.index in remap
                     and any(g.group == group.index and g.weight > 0.5 for g in v.groups)]
        if not protected:
            raise ValueError("根部顶点组为空（需要权重大于 0.5）。")
    result = flatten_normals([tuple(me.vertices[i].co) for i in ids], None,
                             [tuple(remap[i] for i in p.vertices) for p in polygons],
                             [normals[i] for i in corner_ids], forward,
                             transition_ratio=settings.transition_ratio,
                             root_hold_ratio=settings.root_hold_ratio,
                             protect_vertex_ids=protected,
                             world_matrix=[list(row) for row in obj.matrix_world],
                             jaw_offset_ratio=settings.jaw_offset_ratio,
                             jaw_up_axis=axes[settings.jaw_up_direction])
    if not any(w >= 0.999999 for w in result['weights']):
        raise ValueError("过渡带覆盖了整张脸，没有完整作用的中心。请减小过渡宽度。")
    if not protected and any(c.get('outer_loop_confidence') == 'low'
                             for c in result['stats'].get('component_stats', [])):
        raise ValueError("外边界识别可信度低，请指定作用范围或根部顶点组。")
    full_weights = [0.0] * len(me.vertices)
    for i, w in zip(ids, result['weights']):
        full_weights[i] = w
    full_normals = list(normals)
    for i, n in zip(corner_ids, result['corner_normals']):
        full_normals[i] = n
    result['weights'], result['corner_normals'] = full_weights, full_normals
    result['root_vertex_ids'] = [ids[i] for i in result['root_vertex_ids']]
    result['stats']['scope_vertex_count'] = len(ids)
    result['stats']['excluded_vertex_count'] = len(me.vertices) - len(ids)
    return result, forward, old_state
