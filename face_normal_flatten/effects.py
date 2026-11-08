# SPDX-License-Identifier: GPL-3.0-or-later
"""Apply the selected normal workflow and restore the original mesh state."""

import json

from .backup import WEIGHT, discard_backup, read_backup, restore_base_normals, snapshot
from .dynamic import apply_dynamic, restore_dynamic
from .storage import write_precise_tangent_normals
from .transition import calculate_flatten


def apply_flatten(obj, settings=None):
    """Legacy static API; the UI dispatches through apply_effect instead."""
    settings = settings or obj.fnf_settings
    result, forward, old_state = calculate_flatten(obj, settings)
    if old_state and old_state.get('dynamic'):
        raise ValueError("请先恢复应用前状态，再切换到静态模式。")
    me = obj.data
    snapshot(obj)
    try:
        result['stats']['storage'] = write_precise_tangent_normals(me, result['corner_normals'])
    except Exception:
        if old_state is None:
            discard_backup(me)
        raise
    weight = me.attributes.get(WEIGHT) or me.attributes.new(WEIGHT, 'FLOAT', 'POINT')
    weight.data.foreach_set('value', result['weights'])
    for m in obj.modifiers:
        if m.type == 'NORMAL_EDIT':
            m.show_viewport = False
            m.show_render = False
    me.update()
    obj['fnf_last_stats'] = json.dumps(result['stats'])
    obj['fnf_forward'] = list(forward)
    settings.status = "已应用：中心平面化，外缘恢复原法线"
    return result


def restore_normals(obj):
    me = obj.data
    state = read_backup(obj)
    if not state:
        raise ValueError("当前网格没有插件原法线备份。")
    if state.get('dynamic'):
        restore_dynamic(obj, state['dynamic'])
    else:
        for item in state['normal_modifiers']:
            modifier = obj.modifiers.get(item['name'])
            if modifier and modifier.type == 'NORMAL_EDIT':
                modifier.show_viewport = item['viewport']
                modifier.show_render = item['render']
    restore_base_normals(me, state)
    discard_backup(me)
    weight = me.attributes.get(WEIGHT)
    if weight:
        me.attributes.remove(weight)
    for key in ('fnf_last_stats','fnf_forward'):
        if key in obj:
            del obj[key]
    me.update()
    obj.fnf_settings.status = "已恢复原始法线和修改器，已移除插件生成的过渡组"


def apply_effect(obj, settings=None):
    settings = settings or obj.fnf_settings
    if settings.effect_mode == 'DYNAMIC':
        return apply_dynamic(obj, settings)
    return apply_flatten(obj, settings)
