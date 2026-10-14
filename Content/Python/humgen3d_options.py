"""Import options of the Human Generator 3D Companion for Unreal Engine.

What the companion sets up can be changed in two places:

- the project defaults, in ``Config/HumGen3DCompanion.json`` of the project (so
  they go into version control), edited with Tools > Human Generator 3D >
  Project Defaults;
- per character, as the metadata tag ``HumGen3D.ImportOptions`` of its skeletal
  mesh, edited with Human Generator 3D > Import Settings in the context menu of
  the mesh. The tag is kept on reimport.

Both are JSON with a ``version`` (OPTIONS_VERSION; missing counts as 1) and
the enum-like options as stable strings, never indices.

After a character was imported in the editor for the first time, the companion
shows its import settings in a dialog before it sets it up, never in a
commandlet or an unattended run. Both dialogs are details views of the Python
classes below.
"""
import json
import os

import unreal

OPTIONS_TAG = "HumGen3D.ImportOptions"
CONFIG_FILE = "HumGen3DCompanion.json"
# Version of the stored options, in the config file and the metadata tag. Raise
# it when a stored value changes its meaning, and convert older ones on reading.
OPTIONS_VERSION = 1

HAIR_SHADING_MODEL = "hair_shading_model"
MASKED_LIT = "masked_lit"
HAIRCAP_SET_UP = "set_up"
HAIRCAP_AS_IMPORTED = "as_imported"

# What the companion does without options; the cutoff and specular match
# HAIR_CUTOFF and the skin entry of SPECULAR in humgen3d_companion
DEFAULTS = {
    "set_up_character": True,
    "hair_shading": HAIR_SHADING_MODEL,
    "hair_cutoff": 0.2,
    "haircap": HAIRCAP_SET_UP,
    "skin_subsurface": True,
    "skin_specular": 0.3,
}
PROJECT_DEFAULTS = dict(DEFAULTS, show_dialog_on_import=True)


# --------------------------------------------------------------------------- storage


def _config_path():
    return os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_config_dir()), CONFIG_FILE)


def _stored_version(stored, where):
    """The version of stored options, 1 when it has none; warns when it is newer."""
    version = stored.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool):
        version = 1
    if version > OPTIONS_VERSION:
        unreal.log_warning(
            f"Human Generator 3D Companion: the options in {where} were saved by a newer Companion "
            f"(version {version}), only the options this one knows are used"
        )
    return version


def project_defaults():
    """The project defaults, with the built-in default for every missing key."""
    values = dict(PROJECT_DEFAULTS)
    try:
        with open(_config_path(), encoding="utf-8") as f:
            stored = json.load(f)
        if not isinstance(stored, dict):
            raise ValueError("not a JSON object")
        _stored_version(stored, _config_path())
        values.update({k: v for k, v in stored.items() if k in PROJECT_DEFAULTS})
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        unreal.log_warning(f"Human Generator 3D Companion: could not read {_config_path()} ({e}), using the defaults")
    return values


def save_project_defaults(values):
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict({"version": OPTIONS_VERSION}, **{k: values[k] for k in PROJECT_DEFAULTS}), f, indent=4)
        f.write("\n")


def stored_options(mesh):
    """The tag of the mesh as a dict ``{"version": int, "use_project_defaults": bool, "options": {...}}``, or None."""
    try:
        text = unreal.EditorAssetLibrary.get_metadata_tag(mesh, OPTIONS_TAG)
    except Exception:
        return None
    if not text:
        return None
    try:
        stored = json.loads(text)
    except ValueError:
        return None
    if not isinstance(stored, dict):
        return None
    stored["version"] = _stored_version(stored, f"{OPTIONS_TAG} of {mesh.get_name()}")
    return stored


def store_options(mesh, use_project_defaults, options):
    unreal.EditorAssetLibrary.set_metadata_tag(
        mesh, OPTIONS_TAG, json.dumps({"version": OPTIONS_VERSION, "use_project_defaults": use_project_defaults, "options": options})
    )
    unreal.EditorAssetLibrary.save_loaded_asset(mesh, only_if_is_dirty=False)


def options_for(mesh):
    """The options a character is set up with: its own, or the project defaults."""
    values = {k: v for k, v in project_defaults().items() if k in DEFAULTS}
    stored = stored_options(mesh)
    if stored and not stored.get("use_project_defaults", True):
        values.update({k: v for k, v in stored.get("options", {}).items() if k in DEFAULTS})
    return values


# --------------------------------------------------------------------------- dialogs


@unreal.uenum()
class HumGen3DHairShading(unreal.EnumBase):
    HAIR_SHADING_MODEL = unreal.uvalue(0, meta={"DisplayName": "Hair Shading Model", "ToolTip": "The cards with the Hair shading model, highlights along the strands from the flow map of the export"})
    MASKED_LIT = unreal.uvalue(1, meta={"DisplayName": "Masked Lit", "ToolTip": "The cards lit as flat surfaces, like the haircaps"})


@unreal.uenum()
class HumGen3DHaircap(unreal.EnumBase):
    SET_UP = unreal.uvalue(0, meta={"DisplayName": "Set Up", "ToolTip": "Dithered masked hair material, matte"})
    AS_IMPORTED = unreal.uvalue(1, meta={"DisplayName": "As Imported", "ToolTip": "The material Interchange made"})


_HAIR_SHADING = {HAIR_SHADING_MODEL: HumGen3DHairShading.HAIR_SHADING_MODEL, MASKED_LIT: HumGen3DHairShading.MASKED_LIT}
_HAIRCAP = {HAIRCAP_SET_UP: HumGen3DHaircap.SET_UP, HAIRCAP_AS_IMPORTED: HumGen3DHaircap.AS_IMPORTED}


@unreal.uclass()
class HumGen3DImportOptions(unreal.Object):
    """The options of one character, shown in its import settings dialog."""

    character = unreal.uproperty(str, meta={"Category": "Character", "DisplayName": "Character", "ToolTip": "The skeletal mesh these options are for"})
    use_project_defaults = unreal.uproperty(bool, meta={"Category": "Character", "DisplayName": "Use Project Defaults", "ToolTip": "Set up this character with the project defaults (Tools > Human Generator 3D > Project Defaults). Off uses the options below."})
    set_up_character = unreal.uproperty(bool, meta={"Category": "Character", "DisplayName": "Set Up Character", "ToolTip": "Off leaves the character as Interchange imported it"})
    hair_shading = unreal.uproperty(HumGen3DHairShading, meta={"Category": "Hair", "DisplayName": "Card Shading"})
    hair_cutoff = unreal.uproperty(float, meta={"Category": "Hair", "DisplayName": "Hair Cutoff", "ClampMin": "0.0", "ClampMax": "1.0", "UIMin": "0.0", "UIMax": "1.0", "ToolTip": "Opacity below which the hair cards and haircaps are cut out, also the threshold of the alpha coverage mips of the cards"})
    haircap = unreal.uproperty(HumGen3DHaircap, meta={"Category": "Hair", "DisplayName": "Haircap"})
    skin_subsurface = unreal.uproperty(bool, meta={"Category": "Skin", "DisplayName": "Subsurface Profile", "ToolTip": "The skin with the Subsurface Profile shading model. Off: Default Lit"})
    skin_specular = unreal.uproperty(float, meta={"Category": "Skin", "DisplayName": "Specular", "ClampMin": "0.0", "ClampMax": "1.0", "UIMin": "0.0", "UIMax": "1.0", "ToolTip": "Specular of the skin; 0.5 is the engine default, which made the skin look wet"})


@unreal.uclass()
class HumGen3DProjectDefaults(unreal.Object):
    """The project defaults, shown by Tools > Human Generator 3D > Project Defaults."""

    set_up_character = unreal.uproperty(bool, meta={"Category": "Character", "DisplayName": "Set Up Character", "ToolTip": "Off leaves characters as Interchange imports them"})
    show_dialog_on_import = unreal.uproperty(bool, meta={"Category": "Character", "DisplayName": "Show Dialog On Import", "ToolTip": "Show the import settings of a character after its first import in the editor. Never in a commandlet or an unattended run."})
    hair_shading = unreal.uproperty(HumGen3DHairShading, meta={"Category": "Hair", "DisplayName": "Card Shading"})
    hair_cutoff = unreal.uproperty(float, meta={"Category": "Hair", "DisplayName": "Hair Cutoff", "ClampMin": "0.0", "ClampMax": "1.0", "UIMin": "0.0", "UIMax": "1.0"})
    haircap = unreal.uproperty(HumGen3DHaircap, meta={"Category": "Hair", "DisplayName": "Haircap"})
    skin_subsurface = unreal.uproperty(bool, meta={"Category": "Skin", "DisplayName": "Subsurface Profile"})
    skin_specular = unreal.uproperty(float, meta={"Category": "Skin", "DisplayName": "Specular", "ClampMin": "0.0", "ClampMax": "1.0", "UIMin": "0.0", "UIMax": "1.0"})


def _to_object(cls, values):
    obj = cls()
    for key, value in values.items():
        if key == "hair_shading":
            value = _HAIR_SHADING.get(value, HumGen3DHairShading.HAIR_SHADING_MODEL)
        elif key == "haircap":
            value = _HAIRCAP.get(value, HumGen3DHaircap.SET_UP)
        elif isinstance(value, float):
            value = float(value)
        try:
            obj.set_editor_property(key, value)
        except Exception:
            pass
    return obj


def _from_object(obj, keys):
    values = {}
    for key in keys:
        value = obj.get_editor_property(key)
        if key == "hair_shading":
            value = next(k for k, v in _HAIR_SHADING.items() if v == value)
        elif key == "haircap":
            value = next(k for k, v in _HAIRCAP.items() if v == value)
        elif isinstance(value, float):
            value = round(value, 4)
        values[key] = value
    return values


def interactive():
    """Whether a dialog can be shown: not in a commandlet or an unattended run."""
    command_line = unreal.SystemLibrary.get_command_line().lower()
    return "-run=" not in command_line and "-unattended" not in command_line


def _dialog_options():
    options = unreal.EditorDialogLibraryObjectDetailsViewOptions()
    try:
        options.set_editor_property("show_object_name", False)
        options.set_editor_property("allow_search", False)
    except Exception:
        pass
    return options


def edit_character_options(meshes, title="Human Generator 3D Import Settings"):
    """Show the import settings of the meshes in one dialog; on OK store them.

    Returns the meshes whose options were stored (all of them on OK, none on
    Cancel)."""
    defaults = project_defaults()
    objects = []
    for mesh in meshes:
        stored = stored_options(mesh)
        use_defaults = not stored or stored.get("use_project_defaults", True)
        values = dict(options_for(mesh), use_project_defaults=use_defaults, character=mesh.get_name())
        if use_defaults:
            values.update({k: defaults[k] for k in DEFAULTS})
        objects.append(_to_object(HumGen3DImportOptions, values))
    if not unreal.EditorDialog.show_objects_details_view(title, objects, _dialog_options()):
        return []
    for mesh, obj in zip(meshes, objects):
        store_options(mesh, obj.get_editor_property("use_project_defaults"), _from_object(obj, DEFAULTS))
    return list(meshes)


def edit_project_defaults():
    """Show the project defaults; on OK save them. Returns whether they were saved."""
    obj = _to_object(HumGen3DProjectDefaults, project_defaults())
    if not unreal.EditorDialog.show_object_details_view("Human Generator 3D Project Defaults", obj, _dialog_options()):
        return False
    save_project_defaults(_from_object(obj, PROJECT_DEFAULTS))
    return True
