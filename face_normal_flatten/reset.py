# SPDX-License-Identifier: GPL-3.0-or-later
"""Reset base-mesh normals independently of the flattening workflows."""

import bpy

from .backup import read_raw_normals, write_raw_normals


class FNF_OT_reset_normals(bpy.types.Operator):
    bl_idname = 'object.fnf_reset_normals'
    bl_label = '重置所选网格法线'
    bl_description = '物体模式重置所选网格的全部自定义法线；编辑模式对选中元素执行“重置矢量”。修改器继续生效'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode in {'OBJECT', 'EDIT_MESH'}
                and context.object is not None and context.object.type == 'MESH')

    def execute(self, context):
        editing = context.mode == 'EDIT_MESH'
        objects = context.objects_in_mode if editing else context.selected_objects
        meshes = [obj.data for obj in objects if obj.type == 'MESH']
        if not meshes or (editing and not any(mesh.total_vert_sel for mesh in meshes)):
            self.report({'WARNING'}, '请先选择要重置法线的网格或网格元素。')
            return {'CANCELLED'}
        for mesh in meshes:
            if mesh.users > 1 or not mesh.is_editable:
                self.report({'ERROR'}, f'网格“{mesh.name}”需要是可编辑的单用户数据。')
                return {'CANCELLED'}
        if editing:
            return bpy.ops.mesh.normals_tools(mode='RESET')

        # Without an edit selection, remove the whole override. This also
        # covers hidden geometry and preserves the mesh's edit selection.
        previous = []
        try:
            for mesh in meshes:
                raw = read_raw_normals(mesh)
                if raw is not None:
                    previous.append((mesh, raw))
                    write_raw_normals(mesh, None)
        except (RuntimeError, ValueError, TypeError) as exc:
            for mesh, raw in previous:
                write_raw_normals(mesh, raw)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if previous:
            self.report({'INFO'}, f'已重置 {len(previous)} 个网格的自定义法线。')
        else:
            self.report({'INFO'}, '所选网格已使用自动法线。')
        return {'FINISHED'}
