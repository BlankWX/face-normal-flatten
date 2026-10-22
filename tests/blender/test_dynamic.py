# SPDX-License-Identifier: GPL-3.0-or-later
"""Native evaluated-normal tests. Run only in the factory-startup test runner."""
import json
import math
from pathlib import Path
import tempfile
import traceback

import bpy
from mathutils import Vector

import face_normal_flatten as addon
from face_normal_flatten.core import slerp_normal
from face_normal_flatten.dynamic import _raw_custom
from test_generality import _face_patch, _TemporaryScene, _max_angle, _mesh_snapshot, _assert_geometry_unchanged


def evaluated(obj):
    obj.data.update()
    obj.update_tag()
    bpy.context.view_layer.update()
    evaluated_obj = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated_obj.to_mesh()
    try:
        return [tuple(n.vector) for n in mesh.corner_normals]
    finally:
        evaluated_obj.to_mesh_clear()


def endpoints(obj, result):
    modifier = obj.modifiers[result['modifier']]
    group = modifier.vertex_group
    actual = evaluated(obj)
    modifier.vertex_group = ''
    native = evaluated(obj)
    modifier.show_viewport = False
    base = evaluated(obj)
    modifier.show_viewport = True
    modifier.vertex_group = group
    expected = [slerp_normal(a, b, result['weights'][loop.vertex_index])
                for a, b, loop in zip(base, native, obj.data.loops)]
    error = _max_angle(actual, expected)
    assert error < 0.15, f'Native weighted blend differs by {error} degrees'
    flat = [l.index for l in obj.data.loops if result['weights'][l.vertex_index] >= 0.999999]
    roots = [l.index for l in obj.data.loops if result['weights'][l.vertex_index] == 0.0]
    central_error = _max_angle([actual[i] for i in flat], [native[i] for i in flat])
    root_error = _max_angle([actual[i] for i in roots], [base[i] for i in roots])
    assert central_error < 0.15 and root_error < 0.15
    return {'blend_error_deg': error, 'center_error_deg': central_error,
            'root_error_deg': root_error, 'center_corners': len(flat), 'root_corners': len(roots)}


def patch(owner, **kwargs):
    obj = owner.create('dynamic', *_face_patch(**kwargs))
    obj.fnf_settings.effect_mode = 'DYNAMIC'
    obj.fnf_settings.direction = 'NEG_Y'
    return obj


def default_creation(owner):
    obj = patch(owner, cells=24, holes=((7,10,14,17),))
    before = _mesh_snapshot(obj.data)
    result = addon.apply_effect(obj)
    mod = obj.modifiers[result['modifier']]
    assert (mod.type,mod.mode,mod.mix_mode) == ('NORMAL_EDIT','RADIAL','ADD')
    assert tuple(mod.offset) == (0.0,2.0,0.0)
    assert mod.mix_factor == 1 and abs(mod.mix_limit-math.pi)<1e-6 and mod.no_polynors_fix
    assert mod.target is None and not mod.use_direction_parallel
    assert not obj.data.has_custom_normals, 'Dynamic mode baked normals into the base mesh'
    assert result['stats']['ignored_inner_loop_count'] == 1
    metrics = endpoints(obj, result)
    count = len(obj.vertex_groups)
    mod.name = 'Renamed native modifier'
    second = addon.apply_effect(obj)
    assert len(obj.modifiers) == 1 and len(obj.vertex_groups) == count
    assert second['weights'] == result['weights']
    addon.restore_normals(obj)
    assert len(obj.modifiers) == 0 and len(obj.vertex_groups) == 0
    _assert_geometry_unchanged(obj.data,before)
    assert sorted(a.name for a in obj.data.attributes)==before['attributes']
    return metrics


def existing_preservation(owner):
    obj=patch(owner)
    mask=obj.vertex_groups.new(name='User Mask')
    mask.add(list(range(len(obj.data.vertices))),0.35,'REPLACE')
    mod=obj.modifiers.new('User Normal Edit','NORMAL_EDIT')
    mod.mode='RADIAL'; mod.mix_mode='ADD'; mod.offset=(0.4,3.2,-0.7)
    mod.mix_factor=0.73; mod.mix_limit=1.7; mod.no_polynors_fix=True
    mod.vertex_group=mask.name; mod.invert_vertex_group=True
    mod.show_render=False
    obj.modifiers.new('Armature placeholder','ARMATURE')
    original={key:getattr(mod,key) for key in ('mode','mix_mode','mix_factor','mix_limit','no_polynors_fix')}
    offset=tuple(mod.offset)
    result=addon.apply_effect(obj)
    assert list(obj.modifiers).index(mod)==1
    assert all(getattr(mod,k)==v for k,v in original.items()) and tuple(mod.offset)==offset
    assert max(result['weights'])<0.651 and max(result['weights'])>0.649
    addon.restore_normals(obj)
    assert list(obj.modifiers).index(mod)==0
    assert mod.vertex_group==mask.name and mod.invert_vertex_group and not mod.show_render
    assert all(abs(mask.weight(v.index)-0.35)<1e-6 for v in obj.data.vertices)
    return {'restored_original_order_and_mask':True}


def migrate_static(owner):
    obj=patch(owner)
    obj.data.normals_split_custom_set([tuple(n.vector) for n in obj.data.corner_normals])
    original=_raw_custom(obj.data)
    mod=obj.modifiers.new('Original','NORMAL_EDIT'); mod.offset=(0,2,0);mod.mix_mode='ADD'
    addon.apply_flatten(obj)
    assert not mod.show_viewport and _raw_custom(obj.data)!=original
    result=addon.apply_effect(obj)
    assert mod.show_viewport and _raw_custom(obj.data)==original
    metrics=endpoints(obj,result)
    addon.restore_normals(obj)
    assert _raw_custom(obj.data)==original and not mod.show_viewport
    return {'original_raw_storage_restored':True,**metrics}


def rigged(owner):
    obj=patch(owner,cells=24,size=0.1)
    arm=bpy.data.armatures.new('FNF_TestArmature')
    rig=bpy.data.objects.new('FNF_TestRig',arm)
    owner.objects.append(rig)
    bpy.context.scene.collection.objects.link(rig)
    owner.activate(rig)
    bpy.ops.object.mode_set(mode='EDIT')
    b=arm.edit_bones.new('Head');b.head=(0,0,0);b.tail=(0,0,1)
    bpy.ops.object.mode_set(mode='OBJECT')
    owner.activate(obj)
    group=obj.vertex_groups.new(name='Head');group.add(list(range(len(obj.data.vertices))),1,'REPLACE')
    mod=obj.modifiers.new('Armature','ARMATURE');mod.object=rig
    return obj,rig


def animated_pose(owner):
    obj,rig=rigged(owner)
    bone=rig.pose.bones['Head'];bone.rotation_mode='XYZ'
    for frame,angle in ((1,0),(10,-70),(20,70)):
        bone.rotation_euler.y=math.radians(angle)
        bone.keyframe_insert(data_path='rotation_euler',frame=frame)
    bpy.context.scene.frame_set(1)
    result=addon.apply_effect(obj)
    records=[]
    light=Vector((0.6,-0.8,0))
    indices=[l.index for l in obj.data.loops if result['weights'][l.vertex_index]>=0.999999]
    for frame in (1,10,20):
        bpy.context.scene.frame_set(frame)
        metrics=endpoints(obj,result)
        ns=evaluated(obj)
        response=sum(max(0,Vector(ns[i]).dot(light)) for i in indices)/len(indices)
        records.append({'frame':frame,'mean_diffuse_response':response,**metrics})
    assert min(r['mean_diffuse_response'] for r in records)>0.1
    addon.restore_normals(obj)
    bpy.context.scene.frame_set(1)
    addon.apply_flatten(obj)
    bpy.context.scene.frame_set(10)
    static=evaluated(obj)
    static_response=sum(max(0,Vector(static[i]).dot(light)) for i in indices)/len(indices)
    assert records[1]['mean_diffuse_response'] > static_response + 0.1
    addon.restore_normals(obj)
    bpy.context.scene.frame_set(1)
    return {'poses_without_reapplying':records,'legacy_response_frame_10':static_response}


def shape_and_transform(owner):
    obj=patch(owner,cells=24,triangulate=True)
    obj.scale=(2.0,0.7,1.3);obj.rotation_euler=(0.4,-0.2,0.8)
    obj.shape_key_add(name='Basis')
    key=obj.shape_key_add(name='Expression')
    for point in key.data:
        if point.co.z<0:point.co.y-=0.12*(1-abs(point.co.x))
    result=addon.apply_effect(obj)
    measurements=[]
    for value in (0,0.5,1):
        key.value=value
        measurements.append(endpoints(obj,result))
    addon.restore_normals(obj)
    assert obj.data.shape_keys and key.value==1
    return {'shape_values':measurements}


def scoped_face(owner):
    obj=patch(owner,cells=24)
    group=obj.vertex_groups.new(name='Region')
    group.add([v.index for v in obj.data.vertices if v.co.x>-0.7 and v.co.x<0.7],1,'REPLACE')
    obj.fnf_settings.region_group=group.name
    result=addon.apply_effect(obj)
    assert all(result['weights'][v.index]==0 for v in obj.data.vertices if abs(v.co.x)>=0.7)
    metrics=endpoints(obj,result)
    addon.restore_normals(obj)
    assert obj.vertex_groups.get(group.name)
    return metrics


def collision_and_selection(owner):
    obj=patch(owner)
    original=obj.vertex_groups.new(name='FNF_Transition')
    original.add([0],0.123,'REPLACE')
    a=obj.modifiers.new('A','NORMAL_EDIT');b=obj.modifiers.new('B','NORMAL_EDIT')
    b.show_viewport=False
    try:addon.apply_effect(obj)
    except ValueError:pass
    else:raise AssertionError('Ambiguous modifier selection was accepted')
    assert addon.STATE not in obj.data and len(obj.vertex_groups)==1
    obj.fnf_settings.normal_modifier='A'
    result=addon.apply_effect(obj)
    assert a.vertex_group!=original.name and not b.show_viewport
    addon.restore_normals(obj)
    assert abs(original.weight(0)-0.123)<1e-6 and len(obj.vertex_groups)==1
    return {'multiple_requires_selection':True,'user_group_preserved':True}


def jaw_and_persistence(owner):
    obj=patch(owner,cells=24)
    a=addon.apply_effect(obj)
    obj.fnf_settings.jaw_offset_ratio=0.15
    b=addon.apply_effect(obj)
    assert b['weights']!=a['weights']
    assert all(a['weights'][v.index]==b['weights'][v.index] for v in obj.data.vertices if v.co.z>0.7)
    assert all(b['weights'][i]==0 for i in b['root_vertex_ids'])
    before=evaluated(obj)
    with tempfile.TemporaryDirectory() as temp:
        path=str(Path(temp)/'dynamic-roundtrip.blend')
        bpy.data.libraries.write(path,{obj})
        with bpy.data.libraries.load(path,link=False) as (src,dst):
            dst.objects=[obj.name]
        copy=dst.objects[0]
        owner.objects.append(copy);owner.meshes.append(copy.data)
        bpy.context.scene.collection.objects.link(copy)
        assert _max_angle(before,evaluated(copy))<0.001
        owner.activate(copy)
        addon.apply_effect(copy)
        assert len(copy.modifiers)==1
        addon.restore_normals(copy)
        assert not copy.modifiers and not copy.vertex_groups
    return {'persisted_native_evaluation':True}


def invalid_rejection(owner):
    obj=patch(owner)
    shared=owner.shared_object(obj)
    try:addon.apply_effect(obj)
    except ValueError:pass
    else:raise AssertionError('Shared mesh was accepted')
    assert not obj.modifiers and addon.STATE not in obj.data
    # Delete only this fixture's shared object; leave owner cleanup ownership intact.
    owner.objects.remove(shared);bpy.data.objects.remove(shared,do_unlink=True)
    addon.apply_effect(obj)
    old_mods=list(obj.modifiers)
    obj.fnf_settings.root_group='Missing'
    before=obj.data[addon.STATE]
    try:addon.apply_effect(obj)
    except ValueError:pass
    else:raise AssertionError('Missing group accepted')
    assert obj.data[addon.STATE]==before and list(obj.modifiers)==old_mods
    addon.restore_normals(obj)
    return {'failed_updates_preserve_state':True}


def rollback_and_deleted_modifier(owner):
    from unittest.mock import patch as mock_patch
    from face_normal_flatten import dynamic
    obj=patch(owner)
    normal=obj.modifiers.new('Existing','NORMAL_EDIT')
    obj.modifiers.new('Armature placeholder','ARMATURE')
    addon.apply_flatten(obj)
    original_raw=_raw_custom(obj.data)
    original_state=obj.data[addon.STATE]
    original_weights=[x.value for x in obj.data.attributes[addon.WEIGHT].data]
    real_move=dynamic._move
    calls=[]
    def fail_once(*args):
        calls.append(1)
        if len(calls)==1:raise RuntimeError('Injected modifier movement failure')
        return real_move(*args)
    with mock_patch.object(dynamic,'_move',fail_once):
        try:addon.apply_effect(obj)
        except RuntimeError:pass
        else:raise AssertionError('Injected mutation failure was not raised')
    assert _raw_custom(obj.data)==original_raw
    assert obj.data[addon.STATE]==original_state
    assert [x.value for x in obj.data.attributes[addon.WEIGHT].data]==original_weights
    assert not obj.vertex_groups and list(obj.modifiers).index(normal)==0 and not normal.show_viewport
    addon.restore_normals(obj)
    addon.apply_effect(obj)
    obj.modifiers.remove(normal)
    addon.restore_normals(obj)
    assert not obj.fnf_settings.normal_modifier
    result=addon.apply_effect(obj)
    assert obj.modifiers[result['modifier']].type=='NORMAL_EDIT'
    addon.restore_normals(obj)
    return {'mid_application_failure_rolled_back':True,'recreated_after_deletion':True}


def run(output_path):
    fixtures=(default_creation,existing_preservation,migrate_static,animated_pose,
              shape_and_transform,scoped_face,collision_and_selection,jaw_and_persistence,invalid_rejection,
              rollback_and_deleted_modifier)
    owner=_TemporaryScene();owner.prepare()
    arms_before=set(bpy.data.armatures)
    report={'blender_version':bpy.app.version_string,'cases':[]}
    try:
        for fixture in fixtures:
            item={'name':fixture.__name__}
            try:item.update(fixture(owner),passed=True)
            except Exception as exc:item.update(passed=False,error=str(exc),traceback=traceback.format_exc())
            report['cases'].append(item)
    finally:
        report['cleanup_errors']=owner.cleanup()
        for arm in set(bpy.data.armatures)-arms_before:
            if arm.users==0:bpy.data.armatures.remove(arm)
    report.update(case_count=len(fixtures),passed_count=sum(c['passed'] for c in report['cases']))
    report['all_passed']=report['passed_count']==len(fixtures) and not report['cleanup_errors']
    Path(output_path).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
