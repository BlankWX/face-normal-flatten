# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender add-on: planar facial shading with a preserved root transition."""
bl_info = {
    "name": "Face Normal Flatten / 脸部法线平面化",
    "author": "BlankWX",
    "version": (1, 2, 3),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > 脸部法线",
    "description": "保留骨架后的实时法线编辑，并在面部外缘平滑过渡；兼容静态模式",
    "category": "Mesh",
}

import json
import bpy
from bpy.props import EnumProperty, FloatProperty, FloatVectorProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup

# Keep the package-level scripting API available to existing callers.
from .backup import BASE, RAW, STATE, WEIGHT, read_backup, restore_base_normals, signature, snapshot
from .core import flatten_normals, topology_hash
from .dynamic import panel_modifier
from .effects import apply_effect, apply_flatten, restore_normals
from .reset import FNF_OT_reset_normals
from .transition import calculate_flatten


def _read_direction(settings, value, is_set):
    # Saved v1.2.0 files use 0 for AUTO and 1 for -Y.
    return 1 if value == 0 else value


class FNF_Settings(PropertyGroup):
    effect_mode: EnumProperty(name="工作模式", items=[
        ('DYNAMIC', '动态修改器过渡', '保留骨架后的法线编辑，实时计算；插件只生成过渡权重'),
        ('STATIC', '静态平面化（旧版）', '一次性写入统一的自定义法线，随网格变形')], default='DYNAMIC')
    normal_modifier: StringProperty(name="法线编辑修改器", description="留空时选用唯一的法线编辑；没有则按径向、复制、Y=2 创建。有多个时请明确指定")
    direction: EnumProperty(name="面部朝向", items=[
        ('NEG_Y', '-Y', '', 1), ('Y', '+Y', '', 2), ('X', '+X', '', 3),
        ('NEG_X', '-X', '', 4), ('Z', '+Z', '', 5), ('NEG_Z', '-Z', '', 6),
        ('CUSTOM', '自定义方向', '任意局部空间方向', 7)],
        default='NEG_Y', get_transform=_read_direction)
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
            apply_effect(context.object)
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
        layout.operator('object.fnf_reset_normals', icon='NORMALS_VERTEX')
        if settings.effect_mode == 'DYNAMIC':
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
        if not settings.root_group:
            layout.label(text="自动外缘跳过眼睛和嘴巴内孔")
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


CLASSES = (FNF_Settings, FNF_OT_apply, FNF_OT_restore, FNF_OT_reset_normals, FNF_PT_panel)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.fnf_settings = PointerProperty(type=FNF_Settings)


def unregister():
    del bpy.types.Object.fnf_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
