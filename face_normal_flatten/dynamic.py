# SPDX-License-Identifier: GPL-3.0-or-later
"""Native Normal Edit workflow: persistent vertex weights, no frame handlers."""

import json
import math

import bpy

GROUP = 'FNF_Transition'
SWITCHES = ('vertex_group', 'invert_vertex_group', 'show_viewport', 'show_render')


def _binding(modifier):
    return {'name': modifier.name, 'uid': getattr(modifier, 'persistent_uid', None)}


def _bound_modifier(obj, saved):
    uid = saved.get('uid')
    if uid is not None:
        matches = [m for m in obj.modifiers if m.type == 'NORMAL_EDIT'
                   and getattr(m, 'persistent_uid', None) == uid]
        if len(matches) == 1:
            return matches[0]
        # A deleted modifier must never bind to an unrelated new same-name one.
        return None
    modifier = obj.modifiers.get(saved['name'])
    return modifier if modifier and modifier.type == 'NORMAL_EDIT' else None


def _state(obj):
    from . import STATE
    return json.loads(obj.data.get(STATE, '{}')).get('dynamic')


def _select(obj, settings, state):
    if state:
        modifier = _bound_modifier(obj, state)
        if modifier is None:
            raise ValueError('受管理的法线编辑已被删除，请先解除过渡再重新创建。')
        group = obj.vertex_groups.get(state['group'])
        if group is None or modifier.vertex_group != group.name:
            raise ValueError('过渡顶点组已被删除、重命名或替换，请先解除过渡再重新应用。')
        if settings.normal_modifier and settings.normal_modifier not in (state['name'], modifier.name):
            raise ValueError('请先解除过渡，再更换受管理的法线编辑修改器。')
        return modifier
    if settings.normal_modifier:
        modifier = obj.modifiers.get(settings.normal_modifier)
        if not modifier or modifier.type != 'NORMAL_EDIT':
            raise ValueError('指定的修改器不是有效的法线编辑，请清空选择以自动创建。')
        return modifier
    candidates = [m for m in obj.modifiers if m.type == 'NORMAL_EDIT']
    if len(candidates) > 1:
        raise ValueError('有多个法线编辑修改器，请指定需要添加过渡的那一个。')
    return candidates[0] if candidates else None


def panel_modifier(obj):
    try:
        return _select(obj, obj.fnf_settings, _state(obj))
    except (ValueError, KeyError, TypeError):
        return None


def _move(obj, modifier, index):
    if list(obj.modifiers).index(modifier) != index:
        with bpy.context.temp_override(object=obj, active_object=obj):
            status = bpy.ops.object.modifier_move_to_index(modifier=modifier.name, index=index)
        if status != {'FINISHED'} or list(obj.modifiers).index(modifier) != index:
            raise RuntimeError('无法将法线编辑移动至骨架之后。')


def _raw_custom(mesh):
    attr = mesh.attributes.get('custom_normal')
    if not attr:
        return None
    field = 'vector' if attr.data_type == 'FLOAT_VECTOR' else 'value'
    return (attr.data_type, attr.domain, field,
            [tuple(getattr(item, field)) for item in attr.data])


def _put_raw(mesh, saved):
    attr = mesh.attributes.get('custom_normal')
    if attr:
        mesh.attributes.remove(attr)
    if saved:
        kind, domain, field, values = saved
        attr = mesh.attributes.new('custom_normal', kind, domain)
        for item, value in zip(attr.data, values):
            setattr(item, field, value)
    mesh.update()


def _scope_weights(obj, state):
    original = state['original']
    name = original['vertex_group']
    if not name:
        return [1.0] * len(obj.data.vertices)
    group = obj.vertex_groups.get(name)
    if group is None:
        raise ValueError('原修改器的作用范围顶点组已不存在，请先修复该组。')
    invert = original['invert_vertex_group']
    return [(1.0 - w if invert else w) for w in (
        next((g.weight for g in v.groups if g.group == group.index), 0.0)
        for v in obj.data.vertices)]


def apply_dynamic(obj, settings=None):
    from . import (BASE, RAW, STATE, WEIGHT, calculate_flatten, restore_base_normals,
                   snapshot)
    settings = settings or obj.fnf_settings
    result, forward, backup = calculate_flatten(obj, settings)
    previous = backup.get('dynamic') if backup else None
    modifier = _select(obj, settings, previous)
    if previous:
        managed = dict(previous)
    else:
        managed = {'created': modifier is None,
                   'original_index': list(obj.modifiers).index(modifier) if modifier else -1,
                   'original': {k: getattr(modifier, k) for k in SWITCHES} if modifier else {
                       'vertex_group': '', 'invert_vertex_group': False,
                       'show_viewport': True, 'show_render': True}}
    scope = _scope_weights(obj, managed)
    weights = [w * s for w, s in zip(result['weights'], scope)]
    if not any(w > 0.0 for w in weights):
        raise ValueError('原修改器作用范围与面部过渡区域没有交集。')
    # A skinning bone with this name would deform the mesh when weights change.
    # Choose a fresh name instead of replacing any user group.
    group_name = GROUP
    bones = {b.name for m in obj.modifiers if m.type == 'ARMATURE' and m.object
             for b in m.object.data.bones}
    suffix = 1
    while group_name in bones or (not previous and obj.vertex_groups.get(group_name)):
        group_name = f'{GROUP}.{suffix:03d}'
        suffix += 1
    mesh = obj.data
    raw_before = _raw_custom(mesh)
    json_before = mesh.get(STATE)
    switches_before = {k: getattr(modifier, k) for k in SWITCHES} if modifier else None
    index_before = list(obj.modifiers).index(modifier) if modifier else None
    group = obj.vertex_groups.get(previous['group']) if previous else None
    old_weights = [next((g.weight for g in v.groups if g.group == group.index), None)
                   for v in mesh.vertices] if group else None
    attr_before = ([x.value for x in mesh.attributes[WEIGHT].data]
                   if mesh.attributes.get(WEIGHT) else None)
    new_modifier = new_group = False
    try:
        state = snapshot(obj)
        # v1 migration: restore pre-flatten custom normals, keeping the backup.
        # The native modifier now receives normals after armature/shape deformation.
        restore_base_normals(mesh, state)
        if modifier is None:
            modifier = obj.modifiers.new('FNF 法线编辑', 'NORMAL_EDIT')
            new_modifier = True
            modifier.mode = 'RADIAL'
            modifier.offset = (0.0, 2.0, 0.0)
            modifier.mix_mode = 'ADD'
            modifier.mix_factor = 1.0
            modifier.mix_limit = math.pi
            modifier.no_polynors_fix = True
            modifier.use_direction_parallel = False
            modifier.target = None
        if group is None:
            group = obj.vertex_groups.new(name=group_name)
            new_group = True
        if group.name in bones:
            raise ValueError('过渡组与骨骼同名，请先解除过渡后重新生成。')
        for index, weight in enumerate(weights):
            group.add([index], weight, 'REPLACE')
        modifier.vertex_group = group.name
        modifier.invert_vertex_group = False
        modifier.show_viewport = modifier.show_render = True
        last_armature = max((i for i, m in enumerate(obj.modifiers) if m.type == 'ARMATURE'), default=-1)
        if list(obj.modifiers).index(modifier) < last_armature:
            _move(obj, modifier, last_armature)
        if any(m.type == 'ARMATURE' for m in list(obj.modifiers)[list(obj.modifiers).index(modifier)+1:]):
            raise RuntimeError('法线编辑仍在骨架前，动态过渡未应用。')
        attr = mesh.attributes.get(WEIGHT) or mesh.attributes.new(WEIGHT, 'FLOAT', 'POINT')
        attr.data.foreach_set('value', weights)
        managed.update(_binding(modifier), group=group.name)
        state['dynamic'] = managed
        mesh[STATE] = json.dumps(state)
    except Exception:
        if new_modifier:
            obj.modifiers.remove(modifier)
        elif modifier and switches_before:
            for k, v in switches_before.items():
                setattr(modifier, k, v)
            _move(obj, modifier, index_before)
        if new_group:
            obj.vertex_groups.remove(group)
        elif group and old_weights is not None:
            group.remove(list(range(len(mesh.vertices))))
            for index, weight in enumerate(old_weights):
                if weight is not None:
                    group.add([index], weight, 'REPLACE')
        _put_raw(mesh, raw_before)
        attr = mesh.attributes.get(WEIGHT)
        if attr_before is None and attr:
            mesh.attributes.remove(attr)
        elif attr_before is not None:
            attr.data.foreach_set('value', attr_before)
        if json_before is None:
            for name in (BASE, RAW):
                attr = mesh.attributes.get(name)
                if attr:
                    mesh.attributes.remove(attr)
            if STATE in mesh:
                del mesh[STATE]
        else:
            mesh[STATE] = json_before
        raise
    result.pop('corner_normals', None)
    result['weights'] = weights
    result['modifier'] = modifier.name
    stats = result['stats']
    stats.update(mode='DYNAMIC', modifier=modifier.name, vertex_group=group.name,
                 flat_vertex_count=sum(w >= 0.999999 for w in weights),
                 transition_vertex_count=sum(0.0 < w < 0.999999 for w in weights))
    obj['fnf_last_stats'] = json.dumps(stats)
    obj['fnf_forward'] = list(forward)
    settings.normal_modifier = modifier.name
    settings.status = '已应用动态过渡：法线编辑保留在骨架之后'
    mesh.update()
    obj.update_tag()
    return result


def restore_dynamic(obj, state):
    modifier = _bound_modifier(obj, state)
    group = obj.vertex_groups.get(state['group'])
    if modifier:
        if state['created']:
            obj.modifiers.remove(modifier)
            obj.fnf_settings.normal_modifier = ''
        else:
            for key, value in state['original'].items():
                setattr(modifier, key, value)
            _move(obj, modifier, min(state['original_index'], len(obj.modifiers)-1))
    else:
        obj.fnf_settings.normal_modifier = ''
    # Only remove the group owned by this application, never the original mask.
    if group:
        obj.vertex_groups.remove(group)
