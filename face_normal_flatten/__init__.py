# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender add-on: planar facial shading with a preserved root transition."""
bl_info = {
    "name": "Face Normal Flatten / 脸部法线平面化",
    "author": "BlankWX",
    "version": (1, 2, 0),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > 脸部法线",
    "description": "保留骨架后的实时法线编辑，并在面部外缘平滑过渡；兼容静态模式",
    "category": "Mesh",
}

import json
import bpy
from bpy.props import EnumProperty, FloatProperty, FloatVectorProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup
from mathutils import Vector
from .core import flatten_normals, topology_hash

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
    if state.get('storage_type') and (not raw or raw.data_type != state['storage_type']
                                     or raw.domain != state['storage_domain']):
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
    custom = me.attributes.get('custom_normal')
    if custom:
        state['storage_type'] = custom.data_type
        state['storage_domain'] = custom.domain
        field = 'vector' if custom.data_type == 'FLOAT_VECTOR' else 'value'
        raw = me.attributes.new(RAW, custom.data_type, custom.domain)
        # Creating an attribute can invalidate RNA data references; reacquire.
        custom = me.attributes['custom_normal']
        for dst, src in zip(raw.data, custom.data):
            setattr(dst, field, tuple(getattr(src, field)))
    attr = me.attributes.new(BASE, 'FLOAT_VECTOR', 'CORNER')
    attr.data.foreach_set('vector', [c for n in normals for c in n])
    me[STATE] = json.dumps(state)
    return state


def detect_forward(mesh, polygons=None):
    polygons = mesh.polygons if polygons is None else polygons
    direction = sum((p.normal * p.area for p in polygons), Vector())
    total_area = sum(p.area for p in polygons)
    if total_area <= 0 or direction.length / total_area < 0.03:
        raise ValueError("无法从闭合或对称网格判断面部朝向，请手动指定朝向。")
    return direction.normalized()


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
    if settings.direction == 'AUTO':
        forward = detect_forward(me, polygons)
    elif settings.direction == 'CUSTOM':
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


def apply_flatten(obj, settings=None):
    """Legacy static API; the UI dispatches through apply_effect instead."""
    settings = settings or obj.fnf_settings
    result, forward, old_state = calculate_flatten(obj, settings)
    if old_state and old_state.get('dynamic'):
        raise ValueError("请先恢复应用前状态，再切换到静态模式。")
    me = obj.data
    snapshot(obj)
    from .storage import write_precise_tangent_normals
    try:
        result['stats']['storage'] = write_precise_tangent_normals(me, result['corner_normals'])
    except Exception:
        if old_state is None:
            for name in (BASE, RAW):
                attr = me.attributes.get(name)
                if attr:
                    me.attributes.remove(attr)
            if STATE in me:
                del me[STATE]
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


def restore_base_normals(me, state):
    """Restore original storage while retaining the persistent backup."""
    raw = me.attributes.get(RAW)
    if raw:
        field = 'vector' if raw.data_type == 'FLOAT_VECTOR' else 'value'
        values = [tuple(getattr(item, field)) for item in raw.data]
        current = me.attributes.get('custom_normal')
        if current:
            me.attributes.remove(current)
        restored = me.attributes.new('custom_normal', state['storage_type'], state['storage_domain'])
        for item, value in zip(restored.data, values):
            setattr(item, field, value)
    elif state['custom_normals']:
        me.normals_split_custom_set([tuple(x.vector) for x in me.attributes[BASE].data])
    else:
        # Remove the layer directly. The operator/API roundtrip can create an
        # otherwise absent all-false sharp_edge layer on automatic-normal meshes.
        current = me.attributes.get('custom_normal')
        if current:
            me.attributes.remove(current)
    me.update()


def restore_normals(obj):
    me = obj.data
    state = read_backup(obj)
    if not state:
        raise ValueError("当前网格没有插件原法线备份。")
    if state.get('dynamic'):
        from .dynamic import restore_dynamic
        restore_dynamic(obj, state['dynamic'])
    else:
        for item in state['normal_modifiers']:
            modifier = obj.modifiers.get(item['name'])
            if modifier and modifier.type == 'NORMAL_EDIT':
                modifier.show_viewport = item['viewport']
                modifier.show_render = item['render']
    restore_base_normals(me, state)
    for name in (BASE, RAW, WEIGHT):
        attr = me.attributes.get(name)
        if attr:
            me.attributes.remove(attr)
    del me[STATE]
    for key in ('fnf_last_stats','fnf_forward'):
        if key in obj:
            del obj[key]
    me.update()
    obj.fnf_settings.status = "已恢复原始法线和修改器，已移除插件生成的过渡组"


def apply_effect(obj, settings=None):
    settings = settings or obj.fnf_settings
    if settings.effect_mode == 'DYNAMIC':
        from .dynamic import apply_dynamic
        return apply_dynamic(obj, settings)
    return apply_flatten(obj, settings)


class FNF_Settings(PropertyGroup):
    effect_mode: EnumProperty(name="工作模式", items=[
        ('DYNAMIC', '动态修改器过渡', '保留骨架后的法线编辑，实时计算；插件只生成过渡权重'),
        ('STATIC', '静态平面化（旧版）', '一次性写入统一的自定义法线，随网格变形')], default='DYNAMIC')
    normal_modifier: StringProperty(name="法线编辑修改器", description="留空时自动选择唯一的法线编辑；没有则按径向、相加、Y=2创建。有多个时请明确指定")
    direction: EnumProperty(name="面部朝向", items=[
        ('AUTO', '自动识别', '根据面片面积法线识别主要朝向'),
        ('NEG_Y', '-Y', ''), ('Y', '+Y', ''), ('X', '+X', ''),
        ('NEG_X', '-X', ''), ('Z', '+Z', ''), ('NEG_Z', '-Z', ''),
        ('CUSTOM', '自定义方向', '任意局部空间方向')], default='AUTO')
    custom_forward: FloatVectorProperty(name="自定义朝向", default=(0,-1,0), size=3, subtype='DIRECTION')
    transition_ratio: FloatProperty(name="过渡宽度", description="过渡带宽度占面部总宽度的比例；越大过渡越柔和，中心区域越小",
                                    default=0.30, min=0.01, max=1.0, subtype='FACTOR')
    root_hold_ratio: FloatProperty(name="根部保留宽度", description="外缘保持原法线的带宽，占面部总宽度的比例",
                                   default=0.02, min=0.0, max=0.25, subtype='FACTOR')
    jaw_offset_ratio: FloatProperty(name="下颌过渡下移", description="正值把下巴过渡压低至轮廓，负值向上展开；按面部宽度比例计算。0保持旧效果，调整后点击应用 / 更新",
                                    default=0.0, min=-0.50, max=0.50, soft_min=-0.20, soft_max=0.20,
                                    precision=3, step=1)
    jaw_up_direction: EnumProperty(name="模型上方向", description="下颌位置判断使用的物体局部上方向，常规模型为 +Z，不改变旧版过渡宽度计算", items=[
        ('Z', '+Z', ''), ('NEG_Z', '-Z', ''), ('Y', '+Y', ''),
        ('NEG_Y', '-Y', ''), ('X', '+X', ''), ('NEG_X', '-X', '')], default='Z')
    root_group: StringProperty(name="指定根部顶点组", description="留空自动识别外缘。指定组会替代自动外缘；权重大于0.5的顶点作为根部")
    region_group: StringProperty(name="作用范围顶点组", description="独立脸部网格留空；整头或连身体网格请指定面部范围，只有组内完整面片参与计算")
    status: StringProperty(default="选择独立脸部网格后应用")


class FNF_OT_apply(Operator):
    bl_idname = 'object.fnf_apply'
    bl_label = '应用 / 更新平面化'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'MESH' and context.object.mode == 'OBJECT'

    def execute(self, context):
        try:
            result = apply_effect(context.object)
            self.report({'INFO'}, context.object.fnf_settings.status)
            return {'FINISHED'}
        except (ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class FNF_OT_restore(Operator):
    bl_idname = 'object.fnf_restore'
    bl_label = '恢复原始法线 / 解除过渡'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.object and context.object.type == 'MESH'
                and context.object.mode == 'OBJECT' and STATE in context.object.data)

    def execute(self, context):
        try:
            restore_normals(context.object)
            self.report({'INFO'}, context.object.fnf_settings.status)
            return {'FINISHED'}
        except (ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class FNF_PT_panel(Panel):
    bl_label = '脸部法线平面化'
    bl_idname = 'FNF_PT_panel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '脸部法线'

    def draw(self, context):
        layout = self.layout
        obj = context.object
        if not obj or obj.type != 'MESH':
            layout.label(text="请选择独立的脸部网格", icon='INFO')
            return
        settings = obj.fnf_settings
        layout.label(text=obj.name, icon='MESH_DATA')
        layout.prop(settings, 'effect_mode')
        if settings.effect_mode == 'DYNAMIC':
            layout.prop_search(settings, 'normal_modifier', obj, 'modifiers')
        layout.prop(settings, 'direction', text='边界识别朝向' if settings.effect_mode == 'DYNAMIC' else '面部朝向')
        if settings.direction == 'CUSTOM':
            layout.prop(settings, 'custom_forward')
        layout.prop(settings, 'transition_ratio', slider=True)
        layout.prop(settings, 'root_hold_ratio', slider=True)
        layout.prop(settings, 'jaw_offset_ratio', slider=True)
        if settings.jaw_offset_ratio != 0.0:
            layout.prop(settings, 'jaw_up_direction')
        layout.prop_search(settings, 'region_group', obj, 'vertex_groups')
        layout.prop_search(settings, 'root_group', obj, 'vertex_groups')
        layout.operator('object.fnf_apply', text='创建 / 更新动态过渡' if settings.effect_mode == 'DYNAMIC' else '应用 / 更新平面化', icon='NORMALS_FACE')
        layout.operator('object.fnf_restore', icon='LOOP_BACK')
        if settings.effect_mode == 'DYNAMIC':
            from .dynamic import panel_modifier
            modifier = panel_modifier(obj)
            if modifier:
                box = layout.box()
                box.label(text=f'实时法线：{modifier.name}', icon='MOD_NORMALEDIT')
                box.prop(modifier, 'mode')
                box.prop(modifier, 'target')
                box.prop(modifier, 'offset')
                box.prop(modifier, 'mix_mode')
                box.prop(modifier, 'mix_factor')
            layout.label(text="骨架后实时计算；中心保留修改器效果")
            layout.label(text="修改器参数即时生效，过渡参数需更新")
        layout.label(text="自动模式跳过眼睛和嘴巴内孔")
        layout.label(text="调整参数后点击应用 / 更新")
        if STATE in obj.data:
            layout.label(text="原法线备份随 .blend 保存", icon='CHECKMARK')
            try:
                stats = json.loads(obj.get('fnf_last_stats','{}'))
                center = '完整作用' if stats.get('mode') == 'DYNAMIC' else '平面中心'
                layout.label(text=f"{center}：{stats.get('flat_vertex_count',0)} 顶点")
                layout.label(text=f"平滑过渡：{stats.get('transition_vertex_count',0)} 顶点")
            except (ValueError, TypeError):
                pass


CLASSES = (FNF_Settings, FNF_OT_apply, FNF_OT_restore, FNF_PT_panel)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.fnf_settings = PointerProperty(type=FNF_Settings)


def unregister():
    del bpy.types.Object.fnf_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
