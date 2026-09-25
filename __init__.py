import bpy
import bmesh
import math
import uuid
from bpy.types import PropertyGroup, Operator, Panel, UIList
from bpy.props import (
    StringProperty, EnumProperty, PointerProperty, CollectionProperty,
    IntProperty, FloatProperty, BoolProperty, FloatVectorProperty
)
from mathutils import Vector, Matrix

SLIDER_LEN = 1.0
TRACK_THICK = 0.16
SQUARE_LEN = 2.0
CIRCLE_RADIUS = 0.09

LABEL_H = 0.18
LABEL_GAP = 0.025
ROW_GAP = 0.06
GROUP_HEADER_H = 0.26
GROUP_HEADER_GAP = 0.05
COLUMN_GAP = 0.22
VERTICAL_SLIDER_GAP = 0.12
VERTICAL_MAX_ROW_WIDTH = 3.0
PANEL_PADDING = 0.15
TITLE_H = 0.45

WIDGET_COLLECTION_NAME = "CTFR_Widgets"


def _link_to_collection(obj, collection):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    collection.objects.link(obj)


def get_widgets_collection():
    coll = bpy.data.collections.get(WIDGET_COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(WIDGET_COLLECTION_NAME)
        bpy.context.scene.collection.children.link(coll)
        coll.hide_render = True
    return coll


def get_or_create_material(name, color):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = color
            if "Emission Color" in bsdf.inputs:
                bsdf.inputs["Emission Color"].default_value = color
                bsdf.inputs["Emission Strength"].default_value = 0.4
        mat.diffuse_color = color
    return mat


def _new_object_from_mesh(mesh_data, name, location, parent, material=None):
    obj = bpy.data.objects.new(name, mesh_data)
    obj.location = location
    coll = get_widgets_collection()
    coll.objects.link(obj)

    if parent is not None:
        obj.parent = parent

    if material is not None:
        if mesh_data.materials:
            mesh_data.materials[0] = material
        else:
            mesh_data.materials.append(material)

    obj.hide_select = True
    return obj


def get_or_create_circle_mesh():
    key = "CTFR_MeshData_Circle"
    mesh = bpy.data.meshes.get(key)

    if mesh is None:
        mesh = bpy.data.meshes.new(key)
        bm = bmesh.new()
        bmesh.ops.create_circle(
            bm,
            cap_ends=True,
            radius=1.0,
            segments=24
        )
        bm.to_mesh(mesh)
        bm.free()

    return mesh


def get_or_create_rect_outline_mesh(width, height, key):
    mesh = bpy.data.meshes.get(key)

    if mesh is None:
        mesh = bpy.data.meshes.new(key)
        bm = bmesh.new()

        hw = width / 2.0
        hh = height / 2.0

        v1 = bm.verts.new((-hw, -hh, 0.0))
        v2 = bm.verts.new((hw, -hh, 0.0))
        v3 = bm.verts.new((hw, hh, 0.0))
        v4 = bm.verts.new((-hw, hh, 0.0))

        bm.edges.new((v1, v2))
        bm.edges.new((v2, v3))
        bm.edges.new((v3, v4))
        bm.edges.new((v4, v1))

        bm.to_mesh(mesh)
        bm.free()

    return mesh


def create_text_object(text, location, parent, size=0.16, align='CENTER'):
    curve = bpy.data.curves.new(name="CTFR_Label", type='FONT')
    curve.body = text
    curve.size = size
    curve.align_x = align
    curve.align_y = 'TOP'

    obj = bpy.data.objects.new(
        "CTFR_Label_" + text[:40],
        curve
    )

    obj.location = location

    coll = get_widgets_collection()
    coll.objects.link(obj)

    if parent is not None:
        obj.parent = parent

    mat = get_or_create_material(
        "CTFR_Mat_Label",
        (0.85, 0.9, 0.9, 1.0)
    )

    curve.materials.append(mat)
    obj.hide_select = True

    return obj


def sanitize_name(name):
    return "".join(
        ch for ch in name.strip()
        if ch not in "\n\t\r"
    ).strip() or "Control"

def _strip_group_prefix(text, group_name):

    import re

    if not text or not group_name:
        return text

    group_clean = group_name.strip()
    if not group_clean:
        return text

    pattern = r'^' + re.escape(group_clean) + r'[_\-\s]*'
    stripped = re.sub(pattern, '', text, count=1, flags=re.IGNORECASE)
    stripped = stripped.strip()

    return stripped if stripped else text


def _auto_label_from_parts(parts, group_name):
    """Build a display label from one or more shape-key names, stripping the
    group name off each part individually before joining them."""
    cleaned = [_strip_group_prefix(p, group_name) for p in parts if p]
    return "_".join(cleaned) if cleaned else ""

def is_facerig(obj):
    return (
        bool(obj)
        and obj.type == 'ARMATURE'
        and obj.get("ctfr_is_facerig", False)
    )


def set_active(obj):
    bpy.context.view_layer.objects.active = obj

    for o in bpy.context.selected_objects:
        o.select_set(False)

    obj.select_set(True)


def _rig_uid(rig_obj):
    uid = rig_obj.get("ctfr_uid")

    if not uid:
        uid = uuid.uuid4().hex[:12]
        rig_obj["ctfr_uid"] = uid

    return uid


def _target_mesh_for_rig(rig_obj):
    if not is_facerig(rig_obj):
        return None

    stored_name = rig_obj.get(
        "ctfr_target_mesh_name",
        ""
    )

    if stored_name:
        obj = bpy.data.objects.get(stored_name)

        if (
            obj
            and obj.type == 'MESH'
            and obj.data.shape_keys
        ):
            return obj

    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue

        shape_keys = obj.data.shape_keys

        if not shape_keys:
            continue

        anim = shape_keys.animation_data

        if not anim or not anim.drivers:
            continue

        for fc in anim.drivers:
            driver = fc.driver

            if not driver:
                continue

            for var in driver.variables:
                for target in var.targets:
                    if target.id == rig_obj:
                        return obj

    return None


def _target_prefix(rig_obj, mesh_obj=None):
    mesh_obj = mesh_obj or _target_mesh_for_rig(rig_obj)

    prefix = rig_obj.get(
        "ctfr_target_prefix",
        ""
    )

    if not prefix and mesh_obj:
        prefix = sanitize_name(mesh_obj.name)
        rig_obj["ctfr_target_prefix"] = prefix

    return sanitize_name(
        prefix or rig_obj.name
    )


def _control_bone_name(rig_obj, mesh_obj, requested_name):
    base = sanitize_name(requested_name)
    prefix = _target_prefix(
        rig_obj,
        mesh_obj
    )

    candidate = f"{prefix}_{base}"

    if candidate not in rig_obj.data.bones:
        return candidate

    i = 2

    while f"{candidate}_{i}" in rig_obj.data.bones:
        i += 1

    return f"{candidate}_{i}"


def _track_name(rig_obj, bone_name):
    return f"CTFR_Track_{_rig_uid(rig_obj)}_{bone_name}"


def _find_track(rig_obj, bone_name):
    obj = bpy.data.objects.get(
        _track_name(
            rig_obj,
            bone_name
        )
    )

    if obj:
        return obj

    return bpy.data.objects.get(
        f"CTFR_Track_{bone_name}"
    )


def _title_name(rig_obj):
    return f"CTFR_Panel_Title_{_rig_uid(rig_obj)}"


def _find_or_detect_rig(context):
    scene = context.scene

    rig = scene.ctfr_rig_object

    if is_facerig(rig):
        return rig

    active = context.view_layer.objects.active

    if is_facerig(active):
        return active

    for obj in context.selected_objects:
        if is_facerig(obj):
            return obj

    for obj in bpy.data.objects:
        if is_facerig(obj):
            return obj

    return None


def _sync_rig_from_append(rig_obj):
    if not is_facerig(rig_obj):
        return None

    mesh_obj = _target_mesh_for_rig(rig_obj)

    if mesh_obj:
        rig_obj["ctfr_target_mesh_name"] = mesh_obj.name

        if not rig_obj.get("ctfr_target_prefix"):
            rig_obj["ctfr_target_prefix"] = sanitize_name(
                mesh_obj.name
            )

    return mesh_obj


def add_shape_key_driver(
    mesh_obj,
    shape_key_name,
    rig_obj,
    bone_name,
    transform_type,
    expression
):
    key_blocks = mesh_obj.data.shape_keys

    if (
        key_blocks is None
        or shape_key_name not in key_blocks.key_blocks
    ):
        return None

    kb = key_blocks.key_blocks[shape_key_name]

    kb.driver_remove("value")

    fcurve = kb.driver_add("value")

    drv = fcurve.driver
    drv.type = 'SCRIPTED'

    for v in list(drv.variables):
        drv.variables.remove(v)

    var = drv.variables.new()
    var.name = "var"
    var.type = 'TRANSFORMS'

    target = var.targets[0]
    target.id = rig_obj
    target.bone_target = bone_name
    target.transform_type = transform_type
    target.transform_space = 'LOCAL_SPACE'

    drv.expression = expression

    fcurve.update()

    return fcurve


def _new_edit_bone(rig_obj, name, head):
    prev_mode = rig_obj.mode

    set_active(rig_obj)

    bpy.ops.object.mode_set(mode='EDIT')

    eb = rig_obj.data.edit_bones.new(name)

    eb.head = Vector(
        (
            head[0],
            head[1],
            0.0
        )
    )

    eb.tail = Vector(
        (
            head[0],
            head[1] + 0.05,
            0.0
        )
    )

    eb.roll = 0.0

    real_name = eb.name

    bpy.ops.object.mode_set(mode='OBJECT')

    return real_name


def _get_circle_widget_object():
    key = "CTFR_Widget_Circle"

    circle_obj = bpy.data.objects.get(key)

    if circle_obj is None:
        circle = get_or_create_circle_mesh()

        circle_mat = get_or_create_material(
            "CTFR_Mat_Knob",
            (0.2, 1.0, 0.45, 1.0)
        )

        if not circle.materials:
            circle.materials.append(circle_mat)

        circle_obj = bpy.data.objects.new(
            key,
            circle
        )

        get_widgets_collection().objects.link(
            circle_obj
        )

        circle_obj.hide_select = True
        circle_obj.hide_viewport = True
        circle_obj.hide_render = True

    return circle_obj


def _setup_pose_bone_common(
    rig_obj,
    bone_name,
    shape_obj,
    shape_scale
):
    pb = rig_obj.pose.bones[bone_name]

    pb.custom_shape = shape_obj
    pb.use_custom_shape_bone_size = False

    if hasattr(
        pb,
        "custom_shape_scale_xyz"
    ):
        pb.custom_shape_scale_xyz = (
            shape_scale,
            shape_scale,
            shape_scale
        )
    else:
        pb.custom_shape_scale = shape_scale

    pb.lock_rotation = (
        True,
        True,
        True
    )

    pb.lock_rotation_w = True

    pb.lock_scale = (
        True,
        True,
        True
    )

    return pb


def create_slider_control(
    rig_obj,
    mesh_obj,
    name,
    orientation,
    bidirectional,
    shape_key_pos,
    shape_key_neg,
    location
):
    bone_name = _control_bone_name(
        rig_obj,
        mesh_obj,
        name
    )

    bone_name = _new_edit_bone(
        rig_obj,
        bone_name,
        location
    )

    circle_obj = _get_circle_widget_object()

    pb = _setup_pose_bone_common(
        rig_obj,
        bone_name,
        circle_obj,
        CIRCLE_RADIUS
    )

    con = pb.constraints.new(
        'LIMIT_LOCATION'
    )

    con.owner_space = 'LOCAL'
    con.use_transform_limit = True

    half = SLIDER_LEN / 2.0

    if orientation == 'HORIZONTAL':
        axis_lock = ('y', 'z')

        if bidirectional:
            con.use_min_x = True
            con.min_x = -half

            con.use_max_x = True
            con.max_x = half
        else:
            con.use_min_x = True
            con.min_x = 0.0

            con.use_max_x = True
            con.max_x = SLIDER_LEN

        track_w = SLIDER_LEN
        track_h = TRACK_THICK

        track_key = (
            f"CTFR_Track_H_"
            f"{'bi' if bidirectional else 'uni'}"
        )

        transform_axis = 'LOC_X'

    else:
        axis_lock = ('x', 'z')

        if bidirectional:
            con.use_min_y = True
            con.min_y = -half

            con.use_max_y = True
            con.max_y = half
        else:
            con.use_min_y = True
            con.min_y = 0.0

            con.use_max_y = True
            con.max_y = SLIDER_LEN

        track_w = TRACK_THICK
        track_h = SLIDER_LEN

        track_key = (
            f"CTFR_Track_V_"
            f"{'bi' if bidirectional else 'uni'}"
        )

        transform_axis = 'LOC_Y'

    con.use_min_z = True
    con.min_z = 0.0

    con.use_max_z = True
    con.max_z = 0.0

    for ax in axis_lock:
        setattr(
            con,
            f"use_min_{ax}",
            True
        )

        setattr(
            con,
            f"min_{ax}",
            0.0
        )

        setattr(
            con,
            f"use_max_{ax}",
            True
        )

        setattr(
            con,
            f"max_{ax}",
            0.0
        )

    pb.lock_location = tuple(
        True if a in axis_lock else False
        for a in ('x', 'y', 'z')
    )

    track_mesh = get_or_create_rect_outline_mesh(
        track_w,
        track_h,
        track_key
    )

    if bidirectional:
        mid = Vector(
            (
                location[0],
                location[1],
                -0.005
            )
        )
    else:
        if orientation == 'HORIZONTAL':
            mid = Vector(
                (
                    location[0] + SLIDER_LEN / 2.0,
                    location[1],
                    -0.005
                )
            )
        else:
            mid = Vector(
                (
                    location[0],
                    location[1] + SLIDER_LEN / 2.0,
                    -0.005
                )
            )

    track_mat = get_or_create_material(
        "CTFR_Mat_Track",
        (0.25, 0.85, 0.55, 1.0)
    )

    _new_object_from_mesh(
        track_mesh,
        _track_name(
            rig_obj,
            bone_name
        ),
        mid,
        rig_obj,
        track_mat
    )

    if bidirectional:
        if shape_key_pos:
            add_shape_key_driver(
                mesh_obj,
                shape_key_pos,
                rig_obj,
                bone_name,
                transform_axis,
                "max(var, 0.0) * 2.0"
            )

        if shape_key_neg:
            add_shape_key_driver(
                mesh_obj,
                shape_key_neg,
                rig_obj,
                bone_name,
                transform_axis,
                "max(-var, 0.0) * 2.0"
            )

    else:
        if shape_key_pos:
            add_shape_key_driver(
                mesh_obj,
                shape_key_pos,
                rig_obj,
                bone_name,
                transform_axis,
                "var"
            )

    return bone_name


def create_square_control(
    rig_obj,
    mesh_obj,
    name,
    sk_up,
    sk_down,
    sk_left,
    sk_right,
    location
):
    bone_name = _control_bone_name(
        rig_obj,
        mesh_obj,
        name
    )

    bone_name = _new_edit_bone(
        rig_obj,
        bone_name,
        location
    )

    circle_obj = _get_circle_widget_object()

    pb = _setup_pose_bone_common(
        rig_obj,
        bone_name,
        circle_obj,
        CIRCLE_RADIUS
    )

    con = pb.constraints.new(
        'LIMIT_LOCATION'
    )

    con.owner_space = 'LOCAL'
    con.use_transform_limit = True

    half = SQUARE_LEN / 2.0

    con.use_min_x = True
    con.min_x = -half

    con.use_max_x = True
    con.max_x = half

    con.use_min_y = True
    con.min_y = -half

    con.use_max_y = True
    con.max_y = half

    con.use_min_z = True
    con.min_z = 0.0

    con.use_max_z = True
    con.max_z = 0.0

    pb.lock_location = (
        False,
        False,
        True
    )

    track_mesh = get_or_create_rect_outline_mesh(
        SQUARE_LEN,
        SQUARE_LEN,
        "CTFR_Track_Square"
    )

    track_mat = get_or_create_material(
        "CTFR_Mat_Track",
        (0.25, 0.85, 0.55, 1.0)
    )

    _new_object_from_mesh(
        track_mesh,
        _track_name(
            rig_obj,
            bone_name
        ),
        Vector(
            (
                location[0],
                location[1],
                -0.005
            )
        ),
        rig_obj,
        track_mat
    )

    if sk_up:
        add_shape_key_driver(
            mesh_obj,
            sk_up,
            rig_obj,
            bone_name,
            'LOC_Y',
            "max(var, 0.0)"
        )

    if sk_down:
        add_shape_key_driver(
            mesh_obj,
            sk_down,
            rig_obj,
            bone_name,
            'LOC_Y',
            "max(-var, 0.0)"
        )

    if sk_right:
        add_shape_key_driver(
            mesh_obj,
            sk_right,
            rig_obj,
            bone_name,
            'LOC_X',
            "max(var, 0.0)"
        )

    if sk_left:
        add_shape_key_driver(
            mesh_obj,
            sk_left,
            rig_obj,
            bone_name,
            'LOC_X',
            "max(-var, 0.0)"
        )

    return bone_name


class CTFR_ControlItem(PropertyGroup):
    bone_name: StringProperty(name="Bone")
    label: StringProperty(name="Label")

    control_type: EnumProperty(
        name="Type",
        items=[
            ('SLIDER', "Slider", ""),
            ('SQUARE', "2D Pad", "")
        ],
    )

    orientation: EnumProperty(
        name="Orientation",
        items=[
            ('HORIZONTAL', "Horizontal", ""),
            ('VERTICAL', "Vertical", ""),
            ('NA', "N/A", "")
        ],
        default='NA',
    )

    group: StringProperty(
        name="Group"
    )

    order: IntProperty(
        default=0
    )

    width: FloatProperty(
        default=SLIDER_LEN
    )

    height: FloatProperty(
        default=TRACK_THICK
    )

    bidirectional: BoolProperty(
        default=False
    )


class CTFR_GroupItem(PropertyGroup):
    name: StringProperty(
        name="Group Name"
    )

    column: IntProperty(
        name="Column",
        default=0,
        min=0
    )

    order: IntProperty(
        default=0
    )


def _estimate_label_width(
    text,
    size=0.16
):
    return max(
        0.3,
        len(text) * size * 0.62
    )


def rebuild_layout(rig_obj):
    groups = sorted(
        rig_obj.ctfr_groups,
        key=lambda g: (
            g.column,
            g.order
        )
    )

    controls = list(
        rig_obj.ctfr_controls
    )

    to_remove = [
        o
        for o in bpy.data.objects
        if (
            o.parent == rig_obj
            and o.name.startswith("CTFR_Label_")
        )
    ]

    for o in to_remove:
        bpy.data.objects.remove(
            o,
            do_unlink=True
        )

    by_group = {}

    for c in controls:
        by_group.setdefault(
            c.group,
            []
        ).append(c)

    for g in by_group:
        by_group[g].sort(
            key=lambda c: c.order
        )

    columns = {}

    for g in groups:
        columns.setdefault(
            g.column,
            []
        ).append(g)

    col_x = PANEL_PADDING
    max_content_height = 0.0

    for col_index in sorted(
        columns.keys()
    ):
        col_groups = columns[col_index]

        col_width = 0.4

        for g in col_groups:
            items = by_group.get(
                g.name,
                []
            )

            col_width = max(
                col_width,
                _estimate_label_width(
                    g.name,
                    0.20
                )
            )

            verticals = [
                c
                for c in items
                if (
                    c.control_type == 'SLIDER'
                    and c.orientation == 'VERTICAL'
                )
            ]

            non_verticals = [
                c
                for c in items
                if c not in verticals
            ]

            if verticals:
                row_width = 0.0
                rows = 1

                for c in verticals:
                    needed = (
                        c.width
                        if row_width == 0
                        else VERTICAL_SLIDER_GAP + c.width
                    )

                    if (
                        row_width + needed
                        > VERTICAL_MAX_ROW_WIDTH
                        and row_width > 0
                    ):
                        rows += 1
                        row_width = c.width
                    else:
                        row_width += needed

                col_width = max(
                    col_width,
                    min(
                        VERTICAL_MAX_ROW_WIDTH,
                        row_width
                    )
                )

            for c in non_verticals:
                col_width = max(
                    col_width,
                    c.width
                )

        cur_y = -(
            PANEL_PADDING
            + TITLE_H
        )

        for g in col_groups:
            header_loc = Vector(
                (
                    col_x,
                    cur_y,
                    0.0
                )
            )

            create_text_object(
                g.name,
                header_loc,
                rig_obj,
                size=0.20
            )

            cur_y -= (
                GROUP_HEADER_H
                + GROUP_HEADER_GAP
            )

            items = by_group.get(
                g.name,
                []
            )

            vertical_items = [
                c
                for c in items
                if (
                    c.control_type == 'SLIDER'
                    and c.orientation == 'VERTICAL'
                )
            ]

            other_items = [
                c
                for c in items
                if not (
                    c.control_type == 'SLIDER'
                    and c.orientation == 'VERTICAL'
                )
            ]

            if vertical_items:
                row_y = cur_y
                row_x = col_x
                row_height = 0.0

                for c in vertical_items:
                    if (
                        row_x != col_x
                        and
                        row_x
                        + VERTICAL_SLIDER_GAP
                        + c.width
                        >
                        col_x
                        + VERTICAL_MAX_ROW_WIDTH
                    ):
                        cur_y = (
                            row_y
                            - row_height
                            - ROW_GAP
                        )

                        row_y = cur_y
                        row_x = col_x
                        row_height = 0.0

                    label_loc = Vector(
                        (
                            row_x,
                            row_y,
                            0.0
                        )
                    )

                    create_text_object(
                        c.label,
                        label_loc,
                        rig_obj,
                        size=0.15
                    )

                    label_bottom = (
                        row_y
                        - LABEL_H
                        - LABEL_GAP
                    )

                    if c.bidirectional:
                        head_y = (
                            label_bottom
                            - c.height / 2.0
                        )
                    else:
                        head_y = (
                            label_bottom
                            - c.height
                        )

                    eb_head = Vector(
                        (
                            row_x,
                            head_y,
                            0.0
                        )
                    )

                    _reposition_bone_head(
                        rig_obj,
                        c.bone_name,
                        eb_head,
                        c
                    )

                    row_height = max(
                        row_height,
                        LABEL_H
                        + LABEL_GAP
                        + c.height
                    )

                    row_x += (
                        c.width
                        + VERTICAL_SLIDER_GAP
                    )

                cur_y = (
                    row_y
                    - row_height
                    - ROW_GAP
                )

            for c in other_items:
                label_loc = Vector(
                    (
                        col_x,
                        cur_y,
                        0.0
                    )
                )

                create_text_object(
                    c.label,
                    label_loc,
                    rig_obj,
                    size=0.15
                )

                cur_y -= (
                    LABEL_H
                    + LABEL_GAP
                )

                is_centered_x = (
                    c.control_type == 'SQUARE'
                    or (
                        c.control_type == 'SLIDER'
                        and c.orientation == 'HORIZONTAL'
                        and c.bidirectional
                    )
                )

                head_x = (
                    col_x + c.width / 2.0
                    if is_centered_x
                    else col_x
                )

                head_y = (
                    cur_y
                    - c.height / 2.0
                )

                eb_head = Vector(
                    (
                        head_x,
                        head_y,
                        0.0
                    )
                )

                _reposition_bone_head(
                    rig_obj,
                    c.bone_name,
                    eb_head,
                    c
                )

                cur_y -= (
                    c.height
                    + ROW_GAP
                )

            cur_y -= 0.03

        content_height = (
            -cur_y
            - (
                PANEL_PADDING
                + TITLE_H
            )
        )

        max_content_height = max(
            max_content_height,
            content_height
        )

        col_x += (
            col_width
            + COLUMN_GAP
        )

    total_width = (
        col_x
        - COLUMN_GAP
        + PANEL_PADDING
    )

    _rebuild_title(
        rig_obj,
        total_width
    )


def _reposition_bone_head(
    rig_obj,
    bone_name,
    new_head,
    control_item
):
    prev_active = (
        bpy.context.view_layer.objects.active
    )

    set_active(rig_obj)

    bpy.ops.object.mode_set(
        mode='EDIT'
    )

    eb = rig_obj.data.edit_bones.get(
        bone_name
    )

    if eb:
        length = (
            eb.tail
            - eb.head
        )

        eb.head = new_head
        eb.tail = (
            new_head
            + length
        )

    bpy.ops.object.mode_set(
        mode='OBJECT'
    )

    track = _find_track(
        rig_obj,
        bone_name
    )

    if track:
        if (
            track.matrix_parent_inverse
            != Matrix.Identity(4)
        ):
            track.matrix_parent_inverse = (
                Matrix.Identity(4)
            )

        if control_item.control_type == 'SQUARE':
            track.location = Vector(
                (
                    new_head[0],
                    new_head[1],
                    -0.005
                )
            )

        elif control_item.orientation == 'HORIZONTAL':
            if track.data.name.endswith("bi"):
                track.location = Vector(
                    (
                        new_head[0],
                        new_head[1],
                        -0.005
                    )
                )
            else:
                track.location = Vector(
                    (
                        new_head[0] + SLIDER_LEN / 2.0,
                        new_head[1],
                        -0.005
                    )
                )

        else:
            if track.data.name.endswith("bi"):
                track.location = Vector(
                    (
                        new_head[0],
                        new_head[1],
                        -0.005
                    )
                )
            else:
                track.location = Vector(
                    (
                        new_head[0],
                        new_head[1] + SLIDER_LEN / 2.0,
                        -0.005
                    )
                )

    if prev_active:
        set_active(
            prev_active
        )


def _rebuild_title(
    rig_obj,
    width
):
    old = bpy.data.objects.get(
        _title_name(rig_obj)
    )

    if old:
        bpy.data.objects.remove(
            old,
            do_unlink=True
        )

    title_text = rig_obj.get(
        "ctfr_title",
        rig_obj.name
    )

    curve = bpy.data.curves.new(
        "CTFR_Title",
        type='FONT'
    )

    curve.body = title_text
    curve.size = 0.34
    curve.align_x = 'CENTER'

    mat = get_or_create_material(
        "CTFR_Mat_Title",
        (0.7, 0.75, 0.75, 1.0)
    )

    curve.materials.append(mat)

    obj = bpy.data.objects.new(
        _title_name(rig_obj),
        curve
    )

    obj.location = (
        width / 2.0 - PANEL_PADDING,
        PANEL_PADDING * 0.6,
        0.0
    )

    get_widgets_collection().objects.link(
        obj
    )

    obj.parent = rig_obj


class CTFR_OT_detect_rig(Operator):
    bl_idname = "ctfr.detect_rig"
    bl_label = "Detect / Read Face Rig"
    bl_description = (
        "Automatically find a CT FaceRig in the current file, "
        "including an appended rig, and recover its target mesh"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig_obj = _find_or_detect_rig(
            context
        )

        if not rig_obj:
            self.report(
                {'ERROR'},
                "No CT FaceRig armature found"
            )
            return {'CANCELLED'}

        context.scene.ctfr_rig_object = rig_obj

        mesh_obj = _sync_rig_from_append(
            rig_obj
        )

        if mesh_obj:
            context.scene.ctfr_target_mesh = mesh_obj

            self.report(
                {'INFO'},
                f"Using '{rig_obj.name}' → '{mesh_obj.name}'"
            )
        else:
            self.report(
                {'INFO'},
                f"Using '{rig_obj.name}'. Target mesh not found yet"
            )

        return {'FINISHED'}


class CTFR_OT_new_rig(Operator):
    bl_idname = "ctfr.new_rig"
    bl_label = "New Face Rig"
    bl_description = (
        "Create a new empty face-rig control panel (armature)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(
        name="Name",
        default="CT_FaceRig"
    )

    rig_location: FloatVectorProperty(
        name="Location",
        subtype='TRANSLATION',
        size=3,
        default=(0.0, 0.0, 0.0)
    )

    rig_rotation: FloatVectorProperty(
        name="Rotation",
        subtype='EULER',
        size=3,
        default=(
            math.radians(90.0),
            0.0,
            0.0
        )
    )

    rig_scale: FloatProperty(
        name="Scale",
        default=0.15,
        min=0.0001
    )

    def execute(self, context):
        arm_data = bpy.data.armatures.new(
            self.rig_name
        )

        rig_obj = bpy.data.objects.new(
            self.rig_name,
            arm_data
        )

        context.scene.collection.objects.link(
            rig_obj
        )

        rig_obj["ctfr_is_facerig"] = True
        rig_obj["ctfr_title"] = self.rig_name
        rig_obj["ctfr_target_mesh_name"] = ""
        rig_obj["ctfr_target_prefix"] = ""
        rig_obj["ctfr_uid"] = uuid.uuid4().hex[:12]

        rig_obj.location = self.rig_location

        rig_obj.rotation_euler = (
            self.rig_rotation
        )

        rig_obj.scale = (
            self.rig_scale,
            self.rig_scale,
            self.rig_scale
        )

        arm_data.display_type = 'WIRE'
        rig_obj.show_in_front = True

        context.scene.ctfr_rig_object = rig_obj

        rebuild_layout(
            rig_obj
        )

        self.report(
            {'INFO'},
            f"Created {rig_obj.name}"
        )

        return {'FINISHED'}


class CTFR_OT_set_target_mesh(Operator):
    bl_idname = "ctfr.set_target_mesh"
    bl_label = "Set Target Mesh"
    bl_description = (
        "Assign the mesh whose shape keys will be controlled"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene

        rig_obj = scene.ctfr_rig_object
        mesh_obj = scene.ctfr_target_mesh

        if not is_facerig(rig_obj):
            self.report(
                {'ERROR'},
                "Select/create a face rig first"
            )
            return {'CANCELLED'}

        if (
            not mesh_obj
            or mesh_obj.type != 'MESH'
        ):
            self.report(
                {'ERROR'},
                "Pick a mesh object first"
            )
            return {'CANCELLED'}

        rig_obj["ctfr_target_mesh_name"] = (
            mesh_obj.name
        )

        rig_obj["ctfr_target_prefix"] = (
            sanitize_name(mesh_obj.name)
        )

        rig_obj[
            "ctfr_target_mesh_library_name"
        ] = mesh_obj.data.name

        self.report(
            {'INFO'},
            f"Target mesh: {mesh_obj.name} | "
            f"Prefix: {rig_obj['ctfr_target_prefix']}"
        )

        return {'FINISHED'}


class CTFR_OT_add_group(Operator):
    bl_idname = "ctfr.add_group"
    bl_label = "Add Group"
    bl_description = (
        "Create a new named area used to organize controls "
        "in the panel"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        rig_obj = scene.ctfr_rig_object

        if not is_facerig(rig_obj):
            self.report(
                {'ERROR'},
                "Select/create a face rig first"
            )
            return {'CANCELLED'}

        name = sanitize_name(
            scene.ctfr_new_group_name
            or "Group"
        )

        if any(
            g.name == name
            for g in rig_obj.ctfr_groups
        ):
            self.report(
                {'ERROR'},
                "A group with that name already exists"
            )
            return {'CANCELLED'}

        g = rig_obj.ctfr_groups.add()

        g.name = name
        g.column = scene.ctfr_new_group_column
        g.order = len(
            rig_obj.ctfr_groups
        )

        rig_obj.ctfr_active_group_index = (
            len(rig_obj.ctfr_groups) - 1
        )

        rebuild_layout(
            rig_obj
        )

        return {'FINISHED'}


class CTFR_OT_remove_group(Operator):
    bl_idname = "ctfr.remove_group"
    bl_label = "Remove Group"
    bl_description = (
        "Remove the active group and every control inside it"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig_obj = (
            context.scene.ctfr_rig_object
        )

        if not is_facerig(rig_obj):
            return {'CANCELLED'}

        idx = (
            rig_obj.ctfr_active_group_index
        )

        if (
            idx < 0
            or idx >= len(rig_obj.ctfr_groups)
        ):
            return {'CANCELLED'}

        group_name = (
            rig_obj.ctfr_groups[idx].name
        )

        mesh_obj = _target_mesh_for_rig(
            rig_obj
        )

        for i in reversed(
            range(len(rig_obj.ctfr_controls))
        ):
            if (
                rig_obj.ctfr_controls[i].group
                == group_name
            ):
                _delete_control_by_index(
                    rig_obj,
                    mesh_obj,
                    i
                )

        rig_obj.ctfr_groups.remove(
            idx
        )

        rig_obj.ctfr_active_group_index = min(
            idx,
            len(rig_obj.ctfr_groups) - 1
        )

        rebuild_layout(
            rig_obj
        )

        return {'FINISHED'}


def _delete_control_by_index(
    rig_obj,
    mesh_obj,
    index
):
    item = rig_obj.ctfr_controls[index]

    bone_name = item.bone_name

    if (
        mesh_obj
        and mesh_obj.data.shape_keys
    ):
        anim = (
            mesh_obj.data.shape_keys.animation_data
        )

        if anim and anim.drivers:
            for fc in list(anim.drivers):
                for var in fc.driver.variables:
                    for t in var.targets:
                        if (
                            t.id == rig_obj
                            and t.bone_target == bone_name
                        ):
                            anim.drivers.remove(
                                fc
                            )
                            break

    track = _find_track(
        rig_obj,
        bone_name
    )

    if track:
        bpy.data.objects.remove(
            track,
            do_unlink=True
        )

    set_active(
        rig_obj
    )

    bpy.ops.object.mode_set(
        mode='EDIT'
    )

    eb = rig_obj.data.edit_bones.get(
        bone_name
    )

    if eb:
        rig_obj.data.edit_bones.remove(
            eb
        )

    bpy.ops.object.mode_set(
        mode='OBJECT'
    )

    rig_obj.ctfr_controls.remove(
        index
    )


class CTFR_OT_remove_control(Operator):
    bl_idname = "ctfr.remove_control"
    bl_label = "Remove Control"
    bl_description = (
        "Delete this control (bone, drivers, track, label)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty()

    def execute(self, context):
        rig_obj = (
            context.scene.ctfr_rig_object
        )

        if not is_facerig(rig_obj):
            return {'CANCELLED'}

        mesh_obj = _target_mesh_for_rig(
            rig_obj
        )

        _delete_control_by_index(
            rig_obj,
            mesh_obj,
            self.index
        )

        rebuild_layout(
            rig_obj
        )

        return {'FINISHED'}


class CTFR_OT_rebuild_layout(Operator):
    bl_idname = "ctfr.rebuild_layout"
    bl_label = "Rebuild Panel Layout"
    bl_description = (
        "Recompute label / track positions and resize "
        "the background panel"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig_obj = (
            context.scene.ctfr_rig_object
        )

        if not is_facerig(rig_obj):
            self.report(
                {'ERROR'},
                "Select/create a face rig first"
            )
            return {'CANCELLED'}

        rebuild_layout(
            rig_obj
        )

        return {'FINISHED'}


class CTFR_OT_add_slider(Operator):
    bl_idname = "ctfr.add_slider"
    bl_label = "Add Slider Control"
    bl_description = (
        "Create a 0..1 or -1..1 slider bound to "
        "one or two shape keys"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        rig_obj = scene.ctfr_rig_object

        if not is_facerig(rig_obj):
            self.report(
                {'ERROR'},
                "Select/create a face rig first"
            )
            return {'CANCELLED'}

        mesh_obj = _target_mesh_for_rig(
            rig_obj
        )

        if (
            not mesh_obj
            or not mesh_obj.data.shape_keys
        ):
            self.report(
                {'ERROR'},
                "Target mesh has no shape keys"
            )
            return {'CANCELLED'}

        if not rig_obj.ctfr_groups:
            self.report(
                {'ERROR'},
                "Create a group first"
            )
            return {'CANCELLED'}

        bidirectional = (
            scene.ctfr_slider_type == 'BI'
        )

        sk_pos = scene.ctfr_shape_key_pos

        sk_neg = (
            scene.ctfr_shape_key_neg
            if bidirectional
            else ""
        )

        if not sk_pos and not (
            bidirectional and sk_neg
        ):
            self.report(
                {'ERROR'},
                "Pick at least one shape key"
            )
            return {'CANCELLED'}

        if (
            scene.ctfr_use_custom_name
            and scene.ctfr_custom_name
        ):
            auto_name = (
                scene.ctfr_custom_name
            )
        else:
            if bidirectional:
                auto_name = "_".join(
                    n
                    for n in (
                        sk_pos,
                        sk_neg
                    )
                    if n
                ) or "Slider"
            else:
                auto_name = (
                    sk_pos
                    or "Slider"
                )

        active_group_idx = (
            rig_obj.ctfr_active_group_index
        )

        if (
            0 <= active_group_idx
            < len(rig_obj.ctfr_groups)
        ):
            group = (
                rig_obj.ctfr_groups[
                    active_group_idx
                ].name
            )
        else:
            group = (
                rig_obj.ctfr_groups[0].name
            )

        if scene.ctfr_custom_label:
            label = scene.ctfr_custom_label
        elif (
            scene.ctfr_use_custom_name
            and scene.ctfr_custom_name
        ):
            label = _strip_group_prefix(
                scene.ctfr_custom_name,
                group
            )
        else:
            if bidirectional:
                label = _auto_label_from_parts(
                    (sk_pos, sk_neg),
                    group
                ) or "Slider"
            else:
                label = (
                    _strip_group_prefix(sk_pos, group)
                    if sk_pos
                    else "Slider"
                )

        bone_name = create_slider_control(
            rig_obj,
            mesh_obj,
            auto_name,
            scene.ctfr_orientation,
            bidirectional,
            sk_pos,
            sk_neg,
            (0.0, 0.0)
        )

        item = rig_obj.ctfr_controls.add()

        item.bone_name = bone_name
        item.label = label
        item.control_type = 'SLIDER'
        item.orientation = (
            scene.ctfr_orientation
        )
        item.bidirectional = bidirectional
        item.group = group
        item.order = len(
            rig_obj.ctfr_controls
        )

        if (
            scene.ctfr_orientation
            == 'HORIZONTAL'
        ):
            item.width = SLIDER_LEN
            item.height = TRACK_THICK
        else:
            item.width = TRACK_THICK
            item.height = SLIDER_LEN

        rebuild_layout(
            rig_obj
        )

        self.report(
            {'INFO'},
            f"Added slider '{bone_name}'"
        )

        return {'FINISHED'}


class CTFR_OT_add_square(Operator):
    bl_idname = "ctfr.add_square"
    bl_label = "Add 2D Pad Control"
    bl_description = (
        "Create a square pad bound to "
        "up/down/left/right shape keys"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        rig_obj = scene.ctfr_rig_object

        if not is_facerig(rig_obj):
            self.report(
                {'ERROR'},
                "Select/create a face rig first"
            )
            return {'CANCELLED'}

        mesh_obj = _target_mesh_for_rig(
            rig_obj
        )

        if (
            not mesh_obj
            or not mesh_obj.data.shape_keys
        ):
            self.report(
                {'ERROR'},
                "Target mesh has no shape keys"
            )
            return {'CANCELLED'}

        if not rig_obj.ctfr_groups:
            self.report(
                {'ERROR'},
                "Create a group first"
            )
            return {'CANCELLED'}

        up = scene.ctfr_shape_key_up
        down = scene.ctfr_shape_key_down
        left = scene.ctfr_shape_key_left
        right = scene.ctfr_shape_key_right

        if not any(
            (
                up,
                down,
                left,
                right
            )
        ):
            self.report(
                {'ERROR'},
                "Pick at least one shape key"
            )
            return {'CANCELLED'}

        if (
            scene.ctfr_use_custom_name
            and scene.ctfr_custom_name
        ):
            auto_name = (
                scene.ctfr_custom_name
            )
        else:
            auto_name = "_".join(
                n
                for n in (
                    up,
                    down,
                    left,
                    right
                )
                if n
            ) or "Pad"

        active_group_idx = (
            rig_obj.ctfr_active_group_index
        )

        if (
            0 <= active_group_idx
            < len(rig_obj.ctfr_groups)
        ):
            group = (
                rig_obj.ctfr_groups[
                    active_group_idx
                ].name
            )
        else:
            group = (
                rig_obj.ctfr_groups[0].name
            )

        if scene.ctfr_custom_label:
            label = scene.ctfr_custom_label
        elif (
            scene.ctfr_use_custom_name
            and scene.ctfr_custom_name
        ):
            label = _strip_group_prefix(
                scene.ctfr_custom_name,
                group
            )
        else:
            label = _auto_label_from_parts(
                (up, down, left, right),
                group
            ) or "Pad"

        bone_name = create_square_control(
            rig_obj,
            mesh_obj,
            auto_name,
            up,
            down,
            left,
            right,
            (0.0, 0.0)
        )

        item = rig_obj.ctfr_controls.add()

        item.bone_name = bone_name
        item.label = label
        item.control_type = 'SQUARE'
        item.orientation = 'NA'
        item.group = group
        item.order = len(
            rig_obj.ctfr_controls
        )
        item.width = SQUARE_LEN
        item.height = SQUARE_LEN

        rebuild_layout(
            rig_obj
        )

        self.report(
            {'INFO'},
            f"Added 2D pad '{bone_name}'"
        )

        return {'FINISHED'}


class CTFR_UL_controls(UIList):
    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname,
        index
    ):
        row = layout.row(
            align=True
        )

        icon_id = (
            'IPO_LINEAR'
            if item.control_type == 'SLIDER'
            else 'MESH_PLANE'
        )

        row.label(
            text=f"{item.label}",
            icon=icon_id
        )

        row.label(
            text=item.group,
            icon='OUTLINER_COLLECTION'
        )

        op = row.operator(
            "ctfr.remove_control",
            text="",
            icon='X'
        )

        op.index = index


class CTFR_UL_groups(UIList):
    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname,
        index
    ):
        row = layout.row(
            align=True
        )

        row.label(
            text=item.name,
            icon='OUTLINER_COLLECTION'
        )

        row.label(
            text=f"Col {item.column}"
        )


class CTFR_PT_main(Panel):
    bl_idname = "CTFR_PT_main"
    bl_label = "CT FaceRig"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FaceRig"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        rig_obj = _find_or_detect_rig(
            context
        )

        box = layout.box()

        box.label(
            text="Rig",
            icon='ARMATURE_DATA'
        )

        box.prop(
            scene,
            "ctfr_rig_object",
            text="Rig"
        )

        row = box.row()

        row.operator(
            "ctfr.new_rig",
            icon='ADD'
        )

        row.operator(
            "ctfr.detect_rig",
            icon='VIEWZOOM'
        )

        if not is_facerig(rig_obj):
            layout.label(
                text="Create or select a face rig above.",
                icon='INFO'
            )
            return

        box = layout.box()

        box.label(
            text="Transform",
            icon='OBJECT_ORIGIN'
        )

        box.prop(
            rig_obj,
            "location"
        )

        box.prop(
            rig_obj,
            "rotation_euler",
            text="Rotation"
        )

        box.prop(
            rig_obj,
            "scale"
        )

        box = layout.box()

        box.label(
            text="Target Mesh",
            icon='MESH_DATA'
        )

        box.prop(
            scene,
            "ctfr_target_mesh",
            text="Mesh"
        )

        box.operator(
            "ctfr.set_target_mesh",
            icon='CHECKMARK'
        )

        detected_mesh = _target_mesh_for_rig(
            rig_obj
        )

        cur = (
            detected_mesh.name
            if detected_mesh
            else rig_obj.get(
                "ctfr_target_mesh_name",
                ""
            )
        )

        box.label(
            text=f"Current: {cur or '(none)'}"
        )

        mesh_obj = (
            detected_mesh
            if detected_mesh
            else bpy.data.objects.get(cur)
        )

        has_mesh = bool(
            mesh_obj
            and mesh_obj.type == 'MESH'
            and mesh_obj.data.shape_keys
        )

        if not has_mesh:
            box.label(
                text="Target mesh with shape keys not found.",
                icon='ERROR'
            )

        box = layout.box()

        box.label(
            text="Groups",
            icon='OUTLINER_COLLECTION'
        )

        box.template_list(
            "CTFR_UL_groups",
            "",
            rig_obj,
            "ctfr_groups",
            rig_obj,
            "ctfr_active_group_index",
            rows=3
        )

        row = box.row(
            align=True
        )

        row.prop(
            scene,
            "ctfr_new_group_name",
            text=""
        )

        row.prop(
            scene,
            "ctfr_new_group_column",
            text="Col"
        )

        box.operator(
            "ctfr.add_group",
            icon='ADD'
        )

        box.operator(
            "ctfr.remove_group",
            icon='REMOVE'
        )

        box = layout.box()

        box.label(
            text="Add Slider",
            icon='IPO_LINEAR'
        )

        box.prop(
            scene,
            "ctfr_slider_type",
            expand=True
        )

        box.prop(
            scene,
            "ctfr_orientation",
            expand=True
        )

        if has_mesh:
            box.prop_search(
                scene,
                "ctfr_shape_key_pos",
                mesh_obj.data.shape_keys,
                "key_blocks",
                text=(
                    "Shape Key +"
                    if scene.ctfr_slider_type == 'BI'
                    else "Shape Key"
                )
            )

            if scene.ctfr_slider_type == 'BI':
                box.prop_search(
                    scene,
                    "ctfr_shape_key_neg",
                    mesh_obj.data.shape_keys,
                    "key_blocks",
                    text="Shape Key -"
                )
        else:
            box.label(
                text="Set a target mesh with shape keys first",
                icon='ERROR'
            )

        box.prop(
            scene,
            "ctfr_use_custom_name"
        )

        if scene.ctfr_use_custom_name:
            box.prop(
                scene,
                "ctfr_custom_name",
                text="Bone Name"
            )

        box.prop(
            scene,
            "ctfr_custom_label",
            text="Label (optional)"
        )

        row = box.row()

        row.enabled = has_mesh

        row.operator(
            "ctfr.add_slider",
            icon='ADD'
        )

        box = layout.box()

        box.label(
            text="Add 2D Pad",
            icon='MESH_PLANE'
        )

        if has_mesh:
            box.prop_search(
                scene,
                "ctfr_shape_key_up",
                mesh_obj.data.shape_keys,
                "key_blocks",
                text="Up"
            )

            box.prop_search(
                scene,
                "ctfr_shape_key_down",
                mesh_obj.data.shape_keys,
                "key_blocks",
                text="Down"
            )

            box.prop_search(
                scene,
                "ctfr_shape_key_left",
                mesh_obj.data.shape_keys,
                "key_blocks",
                text="Left"
            )

            box.prop_search(
                scene,
                "ctfr_shape_key_right",
                mesh_obj.data.shape_keys,
                "key_blocks",
                text="Right"
            )
        else:
            box.label(
                text="Set a target mesh with shape keys first",
                icon='ERROR'
            )

        row = box.row()

        row.enabled = has_mesh

        row.operator(
            "ctfr.add_square",
            icon='ADD'
        )

        box = layout.box()

        box.label(
            text="Controls",
            icon='BONE_DATA'
        )

        box.template_list(
            "CTFR_UL_controls",
            "",
            rig_obj,
            "ctfr_controls",
            rig_obj,
            "ctfr_active_control_index",
            rows=6
        )

        box.operator(
            "ctfr.rebuild_layout",
            icon='FILE_REFRESH'
        )


classes = (
    CTFR_ControlItem,
    CTFR_GroupItem,
    CTFR_OT_detect_rig,
    CTFR_OT_new_rig,
    CTFR_OT_set_target_mesh,
    CTFR_OT_add_group,
    CTFR_OT_remove_group,
    CTFR_OT_remove_control,
    CTFR_OT_rebuild_layout,
    CTFR_OT_add_slider,
    CTFR_OT_add_square,
    CTFR_UL_controls,
    CTFR_UL_groups,
    CTFR_PT_main,
)


def _rig_poll(self, obj):
    return (
        obj.type == 'ARMATURE'
        and obj.get(
            "ctfr_is_facerig",
            False
        )
    )


def _mesh_poll(self, obj):
    return obj.type == 'MESH'


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.ctfr_controls = CollectionProperty(
        type=CTFR_ControlItem
    )

    bpy.types.Object.ctfr_groups = CollectionProperty(
        type=CTFR_GroupItem
    )

    bpy.types.Object.ctfr_active_group_index = IntProperty(
        default=0
    )

    bpy.types.Object.ctfr_active_control_index = IntProperty(
        default=0
    )

    bpy.types.Scene.ctfr_rig_object = PointerProperty(
        type=bpy.types.Object,
        poll=_rig_poll,
        name="Face Rig"
    )

    bpy.types.Scene.ctfr_target_mesh = PointerProperty(
        type=bpy.types.Object,
        poll=_mesh_poll,
        name="Target Mesh"
    )

    bpy.types.Scene.ctfr_new_group_name = StringProperty(
        name="New Group",
        default="Group"
    )

    bpy.types.Scene.ctfr_new_group_column = IntProperty(
        name="Column",
        default=0,
        min=0
    )

    bpy.types.Scene.ctfr_slider_type = EnumProperty(
        name="Range",
        items=[
            (
                'UNI',
                "One Side Shape Key",
                ""
            ),
            (
                'BI',
                "Two Side Shape Keys",
                ""
            )
        ],
        default='UNI'
    )

    bpy.types.Scene.ctfr_orientation = EnumProperty(
        name="Orientation",
        items=[
            (
                'HORIZONTAL',
                "Horizontal",
                ""
            ),
            (
                'VERTICAL',
                "Vertical",
                ""
            )
        ],
        default='HORIZONTAL'
    )

    bpy.types.Scene.ctfr_shape_key_pos = StringProperty(
        name="Shape Key +"
    )

    bpy.types.Scene.ctfr_shape_key_neg = StringProperty(
        name="Shape Key -"
    )

    bpy.types.Scene.ctfr_shape_key_up = StringProperty(
        name="Up"
    )

    bpy.types.Scene.ctfr_shape_key_down = StringProperty(
        name="Down"
    )

    bpy.types.Scene.ctfr_shape_key_left = StringProperty(
        name="Left"
    )

    bpy.types.Scene.ctfr_shape_key_right = StringProperty(
        name="Right"
    )

    bpy.types.Scene.ctfr_use_custom_name = BoolProperty(
        name="Custom Bone Name",
        default=False
    )

    bpy.types.Scene.ctfr_custom_name = StringProperty(
        name="Custom Name"
    )

    bpy.types.Scene.ctfr_custom_label = StringProperty(
        name="Custom Label"
    )


def unregister():
    del bpy.types.Scene.ctfr_custom_label
    del bpy.types.Scene.ctfr_custom_name
    del bpy.types.Scene.ctfr_use_custom_name
    del bpy.types.Scene.ctfr_shape_key_right
    del bpy.types.Scene.ctfr_shape_key_left
    del bpy.types.Scene.ctfr_shape_key_down
    del bpy.types.Scene.ctfr_shape_key_up
    del bpy.types.Scene.ctfr_shape_key_neg
    del bpy.types.Scene.ctfr_shape_key_pos
    del bpy.types.Scene.ctfr_orientation
    del bpy.types.Scene.ctfr_slider_type
    del bpy.types.Scene.ctfr_new_group_column
    del bpy.types.Scene.ctfr_new_group_name
    del bpy.types.Scene.ctfr_target_mesh
    del bpy.types.Scene.ctfr_rig_object

    del bpy.types.Object.ctfr_active_control_index
    del bpy.types.Object.ctfr_active_group_index
    del bpy.types.Object.ctfr_groups
    del bpy.types.Object.ctfr_controls

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)