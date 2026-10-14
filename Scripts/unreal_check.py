# Imports an exported FBX through Interchange, runs the companion's setup on the
# result (twice, the second run must change nothing) and writes a JSON report of
# what arrived: bones, morph targets, materials, textures, material instances.
#
# The FBX needs its manifest (<Name>.humgen3d.json) next to it. HG_DEST is the
# content folder to import into (default /Game/HumGenInterchange).
#
# HG_FBX=<Name.fbx> HG_REPORT=<report.json> [HG_DEST=/Game/...] UnrealEditor-Cmd <Project.uproject> \
#   -run=pythonscript -script=<plugin>/Scripts/unreal_check.py -unattended -nopause -nosplash
import json
import os
import sys
import traceback

import unreal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Content", "Python"))
import humgen3d_companion as companion  # noqa: E402

OUT = os.environ.get("HG_REPORT", "/tmp/unreal_report.json")
FBX = os.environ["HG_FBX"]
DEST = os.environ.get("HG_DEST", "/Game/HumGenInterchange")
report = {"fbx": FBX, "engine": unreal.SystemLibrary.get_engine_version()}
post_import_events = []


def probe(name, fn):
    try:
        report[name] = fn()
    except Exception as e:
        report[name] = f"ERROR {type(e).__name__}: {e}\n{traceback.format_exc()}"


def record_post_import(factory, created_object):
    post_import_events.append({
        "factory": factory.get_name() if factory else None,
        "asset": created_object.get_name() if created_object else None,
        "class": created_object.get_class().get_name() if created_object else None,
    })


def import_fbx(dest):
    task = unreal.AssetImportTask()
    task.filename = FBX
    task.destination_path = dest
    task.automated = True
    task.save = False
    task.replace_existing = True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    return [str(p) for p in task.imported_object_paths]


def bones(mesh):
    sub = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
    names = []

    def walk(name):
        names.append(str(name))
        for child in sub.get_bone_children(mesh, name):
            walk(child)

    for root in ("root", "Root", "Hips", "mixamorig:Hips", "pelvis"):
        try:
            if sub.get_bone_children(mesh, root) or root in ("root", "Root"):
                walk(root)
                break
        except Exception:
            continue
    return names


def enum_name(value):
    return str(value).split(".")[-1].split(":")[0]


def describe_instance(obj):
    parent = obj.get_editor_property("parent")
    m = {"name": obj.get_name(), "parent": parent.get_name() if parent else None}
    try:
        ov = obj.get_editor_property("base_property_overrides")
        base = parent if isinstance(parent, unreal.Material) else None
        if ov.get_editor_property("override_blend_mode") or base is None:
            m["blend_mode"] = enum_name(ov.get_editor_property("blend_mode"))
        else:
            m["blend_mode"] = enum_name(base.get_editor_property("blend_mode")) + " (inherited)"
        if ov.get_editor_property("override_two_sided") or base is None:
            m["two_sided"] = ov.get_editor_property("two_sided")
        else:
            m["two_sided"] = base.get_editor_property("two_sided")
    except Exception as e:
        m["props"] = str(e)
    try:
        m["texture_params"] = {
            str(t.parameter_info.name): (t.parameter_value.get_name() if t.parameter_value else None)
            for t in obj.get_editor_property("texture_parameter_values")
        }
    except Exception as e:
        m["texture_params"] = str(e)
    return m


def describe_master(obj):
    mel = unreal.MaterialEditingLibrary
    m = {
        "name": obj.get_name(),
        "blend_mode": enum_name(obj.get_editor_property("blend_mode")),
        "two_sided": obj.get_editor_property("two_sided"),
        "opacity_mask_clip_value": obj.get_editor_property("opacity_mask_clip_value"),
        "dither_opacity_mask": obj.get_editor_property("dither_opacity_mask"),
        "shading_model": enum_name(obj.get_editor_property("shading_model")),
    }
    try:
        inputs = {}
        for prop in ("MP_BASE_COLOR", "MP_NORMAL", "MP_AMBIENT_OCCLUSION", "MP_ROUGHNESS", "MP_METALLIC", "MP_OPACITY_MASK", "MP_SPECULAR"):
            node = mel.get_material_property_input_node(obj, getattr(unreal.MaterialProperty, prop))
            if node is None:
                continue
            output = mel.get_material_property_input_node_output_name(obj, getattr(unreal.MaterialProperty, prop))
            param = node.get_editor_property("parameter_name") if hasattr(node, "parameter_name") else None
            inputs[prop] = f"{param}.{output}" if param else f"{node.get_name()}.{output}"
            if prop == "MP_SPECULAR" and hasattr(node, "default_value"):
                m["specular_default"] = float(node.get_editor_property("default_value"))
        m["inputs"] = inputs
    except Exception as e:
        m["inputs"] = str(e)
    return m


def inspect(dest):
    r = {}
    assets = unreal.EditorAssetLibrary.list_assets(dest, recursive=True)
    r["assets"] = sorted(a.split("/")[-1].split(".")[0] for a in assets)
    r["textures"] = []
    r["materials"] = []
    r["material_instances"] = []
    mesh = None
    for a in assets:
        obj = unreal.EditorAssetLibrary.load_asset(a)
        if isinstance(obj, unreal.Texture2D):
            entry = {
                "name": obj.get_name(),
                "srgb": obj.get_editor_property("srgb"),
                "compression": enum_name(obj.get_editor_property("compression_settings")),
            }
            try:
                entry["scale_mips_for_alpha_coverage"] = obj.get_editor_property("do_scale_mips_for_alpha_coverage")
                entry["alpha_coverage_threshold"] = float(obj.get_editor_property("alpha_coverage_thresholds").w)
            except Exception as e:
                entry["alpha_coverage"] = str(e)
            r["textures"].append(entry)
        elif isinstance(obj, unreal.MaterialInstanceConstant):
            r["material_instances"].append(describe_instance(obj))
        elif isinstance(obj, unreal.Material):
            r["materials"].append(describe_master(obj))
        elif isinstance(obj, unreal.SkeletalMesh):
            mesh = obj
    if mesh is None:
        r["skeletal_mesh"] = None
        return r
    r["skeletal_mesh"] = mesh.get_name()
    b = mesh.get_bounds()
    r["height_cm"] = float(b.box_extent.z) * 2
    for name, fn in [
        ("morph_count", lambda: len(mesh.get_all_morph_target_names())),
        ("morph_targets_sample", lambda: [str(n) for n in mesh.get_all_morph_target_names()][:12]),
        ("lod_count", lambda: unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem).get_lod_count(mesh)),
        ("materials_on_mesh", lambda: [str(sm.material_interface.get_name()) if sm.material_interface else None for sm in mesh.materials]),
        ("skeleton", lambda: mesh.skeleton.get_name()),
        ("bones", lambda: bones(mesh)),
    ]:
        try:
            r[name] = fn()
        except Exception as e:
            r[name] = f"ERROR {type(e).__name__}: {e}"
    return r


def find_mesh(dest):
    for a in unreal.EditorAssetLibrary.list_assets(dest, recursive=True):
        obj = unreal.EditorAssetLibrary.load_asset(a)
        if isinstance(obj, unreal.SkeletalMesh):
            return obj
    raise RuntimeError("no skeletal mesh imported")


def run_setup():
    return companion.setup(find_mesh(DEST))


try:
    # keep the delegate wrapper alive, or garbage collection drops the callable mid-import
    import_subsystem = unreal.get_editor_subsystem(unreal.ImportSubsystem)
    post_import_delegate = import_subsystem.on_asset_post_import
    post_import_delegate.add_callable(record_post_import)
    # UE 5.8 imports skeletal meshes through Interchange by default
    probe("interchange_import_paths", lambda: import_fbx(DEST))
    report["post_import_events"] = post_import_events
    probe("interchange", lambda: inspect(DEST))
    probe("setup_first_run", run_setup)
    probe("after_setup", lambda: inspect(DEST))
    probe("setup_second_run", run_setup)
    probe("after_second_setup", lambda: inspect(DEST))
    probe("master_materials", lambda: inspect(companion.MASTER_FOLDER)["materials"])
    report["second_run_unchanged"] = report.get("after_setup") == report.get("after_second_setup")
except Exception:
    report["fatal"] = traceback.format_exc()
with open(OUT, "w") as f:
    json.dump(report, f, indent=2, default=str)
unreal.log("REPORT WRITTEN " + OUT)
