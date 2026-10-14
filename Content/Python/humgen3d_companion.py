"""Human Generator 3D Companion for Unreal Engine.

Sets up a character exported from Human Generator for Blender after Unreal
Engine has imported its FBX. Only a skeletal mesh whose source file has the
export's manifest next to it (``<Name>.humgen3d.json``, written by Human
Generator 4.0.32 and later) is touched; the manifest says what every material
is and which texture files belong to it, so every naming scheme of the export
works. The companion imports the textures Interchange skips (ORM, flow),
fixes the texture settings, creates the four master materials (lit, skin with
subsurface scattering, dithered masked hair for the caps, and the same with
the Hair shading model for the cards, with the flow map of the export as the
strand tangent) and gives every material slot of the skeletal mesh a material
instance with the maps wired.

Entry point: ``setup(skeletal_mesh)``. Running it twice changes nothing.
"""
import glob
import json
import os
import re

import unreal

import humgen3d_options as options_module

LOG_PREFIX = "Human Generator 3D Companion"

# --------------------------------------------------------------------------- manifest

# The manifest format this companion reads. Human Generator only raises it when
# a companion that reads the current format would misread the new one.
MANIFEST_FORMAT = 1
MANIFEST_FORMAT_KEY = "humgen3d_export"
MANIFEST_EXTENSION = ".humgen3d.json"
# Material types of the manifest
SKIN_TYPES = ("skin",)
HAIRCAP_TYPES = ("haircap", "face_haircap")
CARD_TYPES = ("hair_cards",)
HAIR_TYPES = HAIRCAP_TYPES + CARD_TYPES

# --------------------------------------------------------------------------- masters

MASTER_FOLDER = "/Game/HumGen3D"
MASTER_NAME = "M_HumGen3D_Master"
SKIN_MASTER_NAME = "M_HumGen3D_Skin"
HAIR_MASTER_NAME = "M_HumGen3D_Hair"
CARDS_MASTER_NAME = "M_HumGen3D_HairCards"
# Metadata tag with the version of the graph and settings a master was built
# with. A master is (re)built only when it is missing or its stamp is lower than
# the version below, so edits to an up-to-date master are kept. Raise the
# version of a master whenever what _build_master makes for it changes.
MASTER_VERSION_TAG = "HumGen3D.MasterVersion"
MASTER_VERSIONS = {MASTER_NAME: 1, SKIN_MASTER_NAME: 1, HAIR_MASTER_NAME: 1, CARDS_MASTER_NAME: 1}
# The export of Human Generator 4.0.28 and later bakes a flow map for the
# cards: the direction of the strands in the UV space of the card (red and
# green) and a noise per strand (blue). The cards master feeds it to the
# Tangent of the Hair shading model, so the highlights run along the strands
# instead of across the flat card. Cards without the map get the cap master.
FLOW_PARAMETER = "Flow"
# Scatter, Backlit and Specular of the cards master, see _build_master.
# Scatter is the light that comes back out of the mass of the hair, the diffuse
# part of the Hair shading model: at 0 only the highlights are left and the hair
# is near black
CARDS_SCATTER = 0.8
CARDS_BACKLIT = 0.0
# The Hair shading model scatters the root of the base color (the color of a
# fibre the light passes through many times), which turns a baked hair color
# pale and grey. The cards master feeds it the baked color times this
# "Lightness" parameter, squared, so the hair scatters the color that was baked
CARDS_LIGHTNESS = 1.0
CARDS_COLOR_EXPONENT = 2.0
# A card seen from its side is a line with all its strands pressed into it. The
# cards master fades a card out before that: below this "EdgeFade" of how much
# the card faces the camera (0 from its side, 1 from the front). The cards
# around it, or the card across it that loose strands get, show the hair
# instead. 0 turns the fade off.
CARDS_EDGE_FADE = 0.25
# How much of the opacity a card keeps from its side ("EdgeFadeFloor"): faded
# out completely, a lock whose card turns its side to the camera halfway down
# is cut in two and its tip floats in the air
CARDS_EDGE_FADE_FLOOR = 0.7
# From the normal of the card itself, the normals of the mesh follow the head
EDGE_FADE_CODE = (
    "float3 CardNormal = normalize(cross(ddx(WorldPosition), ddy(WorldPosition)));\n"
    "float Facing = abs(dot(CardNormal, CameraVector));\n"
    "return Opacity * lerp(EdgeFadeFloor, 1.0, smoothstep(EdgeFade * 0.3, max(EdgeFade, 0.0001), Facing));"
)
# Default of the "Specular" scalar parameter of each master, where 0.5 is
# Unreal's default. The Blender skin material reflects far less (its specular
# averages 0.06), which made the skin look wet in the engine; real skin is
# around 0.3. The hair cards average 0.13 in Blender. The haircaps lie under
# the cards and have no roughness map: with more than a little specular they
# showed as a glossy spot in every parting.
SPECULAR = {MASTER_NAME: 0.5, SKIN_MASTER_NAME: 0.3, HAIR_MASTER_NAME: 0.05, CARDS_MASTER_NAME: 0.4}
# Alpha below which a hair card texel is cut out. The export bakes the strand
# coverage of the hair atlas into the alpha: solid strands with anti-aliased
# edges and faint fine strands. At the half alpha Unreal's own masked materials
# default to, the fine strands and the edges were lost: bangs were a stipple
# over the forehead and short hair showed the skin at the nape. 0.2 keeps them.
HAIR_CUTOFF = 0.2
# texture pass of the manifest -> material parameter. The other packings of
# the export (separate roughness and metallic, metallic-roughness,
# metallic-smoothness) have no parameter: those materials keep the master's
# default ORM texture. A separate alpha pass is not used either, the Unreal
# recipe packs the alpha of the hair into the base color.
PASS_PARAMETERS = {
    "base_color": "BaseColor",
    "normal": "Normal",
    "orm": "ORM",
    "flow": FLOW_PARAMETER,
}
# material parameter -> (sRGB, compression, sampler type, default texture of the master)
MAP_SETTINGS = {
    "BaseColor": (
        True,
        unreal.TextureCompressionSettings.TC_DEFAULT,
        unreal.MaterialSamplerType.SAMPLERTYPE_COLOR,
        "/Engine/EngineResources/DefaultTexture",
    ),
    "Normal": (
        False,
        unreal.TextureCompressionSettings.TC_NORMALMAP,
        unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL,
        "/Engine/EngineMaterials/DefaultNormal",
    ),
    "ORM": (
        False,
        unreal.TextureCompressionSettings.TC_MASKS,
        unreal.MaterialSamplerType.SAMPLERTYPE_MASKS,
        "/Engine/EngineMaterials/DefaultDiffuse_TC_Masks",
    ),
    FLOW_PARAMETER: (
        False,
        unreal.TextureCompressionSettings.TC_MASKS,
        unreal.MaterialSamplerType.SAMPLERTYPE_MASKS,
        "/Engine/EngineMaterials/DefaultDiffuse_TC_Masks",
    ),
}
# Characters Unreal does not allow in asset names, replaced with "_"
_INVALID_NAME_CHARACTERS = re.compile(r"[\s\"',.:&!~@#(){}\[\]=;^%$/\\*?<>|]")

_warned_manifests = set()


def log(message):
    unreal.log(f"{LOG_PREFIX}: {message}")


def warn(message):
    unreal.log_warning(f"{LOG_PREFIX}: {message}")


# --------------------------------------------------------------------------- detection


def _folder_of(asset):
    return asset.get_path_name().rsplit("/", 1)[0]


def _asset_name(name):
    """The name Unreal gives an asset made from a name of the export."""
    return _INVALID_NAME_CHARACTERS.sub("_", name)


def source_file(asset):
    """The full path of the file the asset was imported from, or None."""
    try:
        import_data = asset.get_editor_property("asset_import_data")
    except Exception:
        return None
    if import_data is None:
        return None
    try:
        path = import_data.get_first_filename()
    except Exception:
        return None
    return unreal.Paths.convert_relative_path_to_full(path) if path else None


def _same_file(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _read_manifest(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and MANIFEST_FORMAT_KEY in data else None


def _lists_file(manifest, manifest_path, source):
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False
    listed = [files.get("character")] + list(files.get("animations") or [])
    folder = os.path.dirname(manifest_path)
    return any(isinstance(p, str) and _same_file(os.path.join(folder, p), source) for p in listed)


def _warn_newer(path, export_format):
    key = (path, os.path.getmtime(path) if os.path.exists(path) else 0)
    if key in _warned_manifests:
        return
    _warned_manifests.add(key)
    warn(
        f"{os.path.basename(path)} was made by a newer Human Generator 3D (export format "
        f"{export_format}, this Companion reads {MANIFEST_FORMAT}): update the Companion. "
        "The character is left as Unreal imported it."
    )


def find_manifest(mesh):
    """The manifest of the export the mesh was imported from, as ``(dict, path)``.

    The manifest is the ``*.humgen3d.json`` next to the source file that lists
    it as the character or one of the animations. None when there is none, or
    when it was made by a newer Human Generator than this companion reads
    (with a warning).
    """
    source = source_file(mesh)
    if not source or not os.path.isfile(source):
        return None
    folder = os.path.dirname(source)
    candidates = [os.path.splitext(source)[0] + MANIFEST_EXTENSION]
    candidates += sorted(glob.glob(os.path.join(glob.escape(folder), "*" + MANIFEST_EXTENSION)))
    seen = set()
    for path in candidates:
        if path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        manifest = _read_manifest(path)
        if manifest is None or not _lists_file(manifest, path, source):
            continue
        export_format = manifest[MANIFEST_FORMAT_KEY]
        if not isinstance(export_format, int) or isinstance(export_format, bool) or export_format < 1:
            warn(f"{path} has no valid {MANIFEST_FORMAT_KEY} format, left alone")
            return None
        if export_format > MANIFEST_FORMAT:
            _warn_newer(path, export_format)
            return None
        return manifest, path
    return None


def is_human_generator_export(mesh):
    """Whether the skeletal mesh was imported from a file a Human Generator
    manifest lists, in a format this companion reads."""
    return isinstance(mesh, unreal.SkeletalMesh) and find_manifest(mesh) is not None


def _manifest_materials(manifest):
    materials = manifest.get("materials")
    if not isinstance(materials, dict):
        return {}
    return {k: v for k, v in materials.items() if isinstance(v, dict)}


def _instance_names(name, materials):
    """``MI_<Name>_<Part>`` per manifest material, or ``MI_<material>`` for the
    materials that share their part with another one."""
    parts = [str(m.get("part") or "") for m in materials.values()]
    names = {}
    for material_name, material in materials.items():
        part = str(material.get("part") or "")
        if part and parts.count(part) == 1:
            names[material_name] = _asset_name(f"MI_{name}_{part}")
        else:
            names[material_name] = _asset_name(f"MI_{material_name}")
    return names


def _slot_material(slot, lookup):
    """The manifest material of a slot: by the slot name, the material's name,
    or the name of the instance the companion gave it."""
    names = [str(slot.material_slot_name)]
    if slot.material_interface is not None:
        names.append(slot.material_interface.get_name())
    for candidate in names:
        if candidate in lookup:
            return lookup[candidate]
    return None


# --------------------------------------------------------------------------- textures


def _import_texture(path, folder, asset_name):
    task = unreal.AssetImportTask()
    task.filename = path
    task.destination_path = folder
    task.destination_name = asset_name
    task.automated = True
    task.save = False
    task.replace_existing = False
    try:
        # the legacy texture factory: synchronous, and safe to call from inside
        # the completion of an Interchange import
        task.factory = unreal.TextureFactory()
    except Exception as e:
        warn(f"could not use the texture factory, importing through Interchange ({e})")
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    for object_path in task.imported_object_paths:
        texture = unreal.load_asset(str(object_path))
        if isinstance(texture, unreal.Texture):
            return texture
    return None


def _differs(current, wanted):
    """Whether a property has another value than the wanted one. The engine
    stores floats in single precision, so 0.2 does not read back as 0.2 and a
    plain comparison saw a change on every import."""
    if isinstance(wanted, float):
        return abs(current - wanted) > 1e-5
    if isinstance(wanted, unreal.Vector4):
        return any(
            abs(getattr(current, axis) - getattr(wanted, axis)) > 1e-5 for axis in "xyzw"
        )
    return current != wanted


def _apply_texture_settings(texture, parameter, cards=False, cutoff=HAIR_CUTOFF, flip_green=False):
    """Set sRGB and compression for the map kind, the green flip of OpenGL
    normal maps, and for the base color of hair cards the mipmaps that keep the
    strand coverage; returns whether anything changed."""
    srgb, compression, _, _ = MAP_SETTINGS[parameter]
    wanted = {"srgb": srgb, "compression_settings": compression}
    if parameter == "Normal":
        # Unreal reads normal maps with green pointing down (DirectX)
        wanted["flip_green_channel"] = flip_green
    if cards and parameter == "BaseColor":
        # Averaging the alpha of thin strands for a mip drops it below the cutoff,
        # so cut-out hair thinned out and vanished with distance. Unreal can scale
        # the alpha of every mip so the share of texels above the threshold stays.
        wanted["do_scale_mips_for_alpha_coverage"] = True
        wanted["alpha_coverage_thresholds"] = unreal.Vector4(0.0, 0.0, 0.0, cutoff)
    changed = False
    for name, value in wanted.items():
        try:
            current = texture.get_editor_property(name)
            if isinstance(value, bool):
                current = bool(current)
            if _differs(current, value):
                texture.set_editor_property(name, value)
                changed = True
        except Exception as e:  # older engines lack some properties
            warn(f"could not set {name} on {texture.get_name()} ({e})")
    if changed:
        unreal.EditorAssetLibrary.save_loaded_asset(texture, only_if_is_dirty=False)
    return changed


def _find_texture_asset(folder, image):
    for asset_name in dict.fromkeys((image, _asset_name(image))):
        path = f"{folder}/{asset_name}"
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            texture = unreal.EditorAssetLibrary.load_asset(path)
            if isinstance(texture, unreal.Texture):
                return texture
    return None


def _textures_for_material(material, manifest_folder, folder, summary, cards, cutoff, flip_green):
    """The textures of a manifest material keyed by material parameter,
    importing the files Interchange skipped."""
    textures = {}
    entries = material.get("textures")
    if not isinstance(entries, dict):
        return textures
    for pass_id, entry in entries.items():
        parameter = PASS_PARAMETERS.get(pass_id)
        if parameter is None or not isinstance(entry, dict) or not entry.get("image"):
            continue
        image = str(entry["image"])
        texture = _find_texture_asset(folder, image)
        if texture is None:
            relative = entry.get("file")
            path = os.path.join(manifest_folder, relative) if isinstance(relative, str) else None
            if path is None or not os.path.isfile(path):
                warn(f"texture {image} is neither imported nor next to the manifest, {parameter} not set")
                continue
            texture = _import_texture(path, folder, _asset_name(image))
            if texture is None:
                warn(f"could not import {path}")
                continue
            summary["imported_textures"].append(texture.get_name())
            summary["changed"] = True
        if _apply_texture_settings(texture, parameter, cards=cards, cutoff=cutoff, flip_green=flip_green):
            summary["fixed_textures"].append(texture.get_name())
            summary["changed"] = True
        textures[parameter] = texture
    return textures


# --------------------------------------------------------------------------- master materials


def _default_texture(parameter):
    _, compression, _, path = MAP_SETTINGS[parameter]
    texture = unreal.load_asset(path)
    if texture is None:
        warn(f"default texture {path} not found, the {parameter} parameter of the master has no default")
        return None
    if texture.get_editor_property("compression_settings") != compression:
        warn(f"default texture {path} is not {compression}, the {parameter} parameter of the master has no default")
        return None
    return texture


def _scalar_parameter(material, name, default, x, y):
    node = unreal.MaterialEditingLibrary.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, x, y
    )
    node.set_editor_property("parameter_name", name)
    node.set_editor_property("default_value", default)
    return node


def _texture_parameter(material, parameter, x, y):
    node = unreal.MaterialEditingLibrary.create_material_expression(
        material, unreal.MaterialExpressionTextureSampleParameter2D, x, y
    )
    node.set_editor_property("parameter_name", parameter)
    node.set_editor_property("sampler_type", MAP_SETTINGS[parameter][2])
    default = _default_texture(parameter)
    if default is not None:
        node.set_editor_property("texture", default)
    return node


def _connect_backlit(material, node):
    """Connects a node (or None) to the Backlit pin of the Hair shading model,
    the first custom data input. The engine hides that pin from the Python enum
    of material properties, so it is set through the editor-only inputs of the
    material instead; returns whether that worked. Unreal 5.8 does not expose
    those inputs to Python either: there the pin stays unconnected and the
    Backlit parameter is not added."""
    try:
        editor_only = material.get_editor_property("editor_only_data")
        backlit = editor_only.get_editor_property("clear_coat")
        backlit.set_editor_property("expression", node)
        editor_only.set_editor_property("clear_coat", backlit)
        return True
    except Exception as e:
        if node is not None:
            log(f"the Backlit pin of {material.get_name()} cannot be connected from Python here, left at the engine default ({e})")
        return False


def _add_edge_fade(material, base_color):
    """The fade of cards seen from their side, between the alpha of the base
    color and the opacity mask."""
    mel = unreal.MaterialEditingLibrary
    position = mel.create_material_expression(material, unreal.MaterialExpressionWorldPosition, -450, -700)
    # relative to the camera, the derivatives of absolute positions are too coarse far from the origin
    position.set_editor_property("world_position_shader_offset", unreal.WorldPositionIncludedOffsets.WPT_CAMERA_RELATIVE)
    camera = mel.create_material_expression(material, unreal.MaterialExpressionCameraVectorWS, -450, -600)
    fade = _scalar_parameter(material, "EdgeFade", CARDS_EDGE_FADE, -450, -500)
    floor = _scalar_parameter(material, "EdgeFadeFloor", CARDS_EDGE_FADE_FLOOR, -450, -420)
    custom = mel.create_material_expression(material, unreal.MaterialExpressionCustom, -200, -600)
    custom.set_editor_property("description", "Edge Fade")
    custom.set_editor_property("code", EDGE_FADE_CODE)
    custom.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT1)
    names = ("WorldPosition", "CameraVector", "EdgeFade", "EdgeFadeFloor", "Opacity")
    inputs = []
    for name in names:
        custom_input = unreal.CustomInput()
        custom_input.set_editor_property("input_name", name)
        inputs.append(custom_input)
    custom.set_editor_property("inputs", inputs)
    mel.connect_material_expressions(position, "", custom, "WorldPosition")
    mel.connect_material_expressions(camera, "", custom, "CameraVector")
    mel.connect_material_expressions(fade, "", custom, "EdgeFade")
    mel.connect_material_expressions(floor, "", custom, "EdgeFadeFloor")
    mel.connect_material_expressions(base_color, "A", custom, "Opacity")
    mel.connect_material_property(custom, "", unreal.MaterialProperty.MP_OPACITY_MASK)


def _add_cards_inputs(material, base_color):
    """The edge fade, lightness, scatter, backlit and strand tangent of the
    cards master."""
    mel = unreal.MaterialEditingLibrary
    mp = unreal.MaterialProperty
    _add_edge_fade(material, base_color)
    # the baked color times Lightness, squared: the Hair model scatters its root
    multiply = mel.create_material_expression(material, unreal.MaterialExpressionMultiply, -250, -300)
    lightness = _scalar_parameter(material, "Lightness", CARDS_LIGHTNESS, -450, -150)
    mel.connect_material_expressions(base_color, "RGB", multiply, "A")
    mel.connect_material_expressions(lightness, "", multiply, "B")
    power = mel.create_material_expression(material, unreal.MaterialExpressionPower, -100, -300)
    power.set_editor_property("const_exponent", CARDS_COLOR_EXPONENT)
    mel.connect_material_expressions(multiply, "", power, "Base")
    mel.connect_material_property(power, "", mp.MP_BASE_COLOR)
    # Scatter is the Metallic pin of the Hair shading model
    mel.connect_material_property(
        _scalar_parameter(material, "Scatter", CARDS_SCATTER, -450, 700), "", mp.MP_METALLIC
    )
    backlit = _scalar_parameter(material, "Backlit", CARDS_BACKLIT, -450, 1100)
    if not _connect_backlit(material, backlit):
        mel.delete_material_expression(material, backlit)
    # Tangent: the flow map's red and green, from 0..1 to -1..1, with a zero
    # third component: a direction in tangent space, like a normal map
    flow = _texture_parameter(material, FLOW_PARAMETER, -1050, 900)
    mask = mel.create_material_expression(material, unreal.MaterialExpressionComponentMask, -800, 900)
    for channel, on in (("r", True), ("g", True), ("b", False), ("a", False)):
        mask.set_editor_property(channel, on)
    unpack = mel.create_material_expression(material, unreal.MaterialExpressionConstantBiasScale, -650, 900)
    unpack.set_editor_property("bias", -0.5)
    unpack.set_editor_property("scale", 2.0)
    zero = mel.create_material_expression(material, unreal.MaterialExpressionConstant, -650, 1000)
    zero.set_editor_property("r", 0.0)
    append = mel.create_material_expression(material, unreal.MaterialExpressionAppendVector, -450, 900)
    mel.connect_material_expressions(flow, "RGB", mask, "")
    mel.connect_material_expressions(mask, "", unpack, "")
    mel.connect_material_expressions(unpack, "", append, "A")
    mel.connect_material_expressions(zero, "", append, "B")
    mel.connect_material_property(append, "", mp.MP_TANGENT)


def _build_master(material, hair, skin, cards):
    """Replaces the graph and settings of a master with the ones of this
    version and stamps it.

    Every master samples BaseColor, Normal and ORM texture parameters (occlusion
    R, roughness G, metallic B) and has a Specular scalar parameter. The hair
    master is masked at HAIR_CUTOFF with a dithered opacity mask, which temporal
    anti-aliasing resolves to soft, translucent-looking strands, the way
    Blender's hashed transparency renders the cards; its metallic is 0 (hair is
    no metal, and a haircap without ORM map got the grey of the default
    texture). The cards master is the same with the Hair shading model, the
    strand direction of the flow map as its tangent and Scatter, Backlit,
    Lightness and the edge fade as parameters: a card lit as a flat surface has
    its highlight across the card, hair has it along the strands. The skin
    master uses the Subsurface Profile shading model with the engine's default
    profile: the skin was rendered with subsurface scattering in Blender and
    looks flat and harsh without it.
    """
    mel = unreal.MaterialEditingLibrary
    mp = unreal.MaterialProperty
    name = material.get_name()
    # one call deletes only part of the nodes on 5.8, repeat until none are left
    for _ in range(64):
        if mel.get_num_material_expressions(material) == 0:
            break
        mel.delete_all_material_expressions(material)
    else:
        warn(f"could not clear the graph of {name}, unused nodes are left in it")
    _connect_backlit(material, None)

    base_color = _texture_parameter(material, "BaseColor", -700, -300)
    normal = _texture_parameter(material, "Normal", -700, 0)
    orm = _texture_parameter(material, "ORM", -700, 300)
    mel.connect_material_property(normal, "RGB", mp.MP_NORMAL)
    mel.connect_material_property(orm, "R", mp.MP_AMBIENT_OCCLUSION)
    mel.connect_material_property(orm, "G", mp.MP_ROUGHNESS)
    specular = _scalar_parameter(material, "Specular", SPECULAR.get(name, 0.5), -450, 600)
    mel.connect_material_property(specular, "", mp.MP_SPECULAR)
    if cards:
        _add_cards_inputs(material, base_color)
    else:
        mel.connect_material_property(base_color, "RGB", mp.MP_BASE_COLOR)
        if hair:
            mel.connect_material_property(base_color, "A", mp.MP_OPACITY_MASK)
            zero = mel.create_material_expression(material, unreal.MaterialExpressionConstant, -250, 500)
            zero.set_editor_property("r", 0.0)
            mel.connect_material_property(zero, "", mp.MP_METALLIC)
        else:
            mel.connect_material_property(orm, "B", mp.MP_METALLIC)

    settings = {
        "blend_mode": unreal.BlendMode.BLEND_MASKED if hair else unreal.BlendMode.BLEND_OPAQUE,
        "two_sided": hair,
        "shading_model": (
            unreal.MaterialShadingModel.MSM_SUBSURFACE_PROFILE
            if skin
            else unreal.MaterialShadingModel.MSM_HAIR
            if cards
            else unreal.MaterialShadingModel.MSM_DEFAULT_LIT
        ),
        "dither_opacity_mask": hair,
        "opacity_mask_clip_value": HAIR_CUTOFF if hair else 0.3333,
    }
    for key, value in settings.items():
        material.set_editor_property(key, value)
    for usage in ("used_with_skeletal_mesh", "used_with_morph_targets"):
        try:
            material.set_editor_property(usage, True)
        except Exception:
            pass
    mel.recompile_material(material)
    unreal.EditorAssetLibrary.set_metadata_tag(material, MASTER_VERSION_TAG, str(MASTER_VERSIONS[name]))
    unreal.EditorAssetLibrary.save_loaded_asset(material, only_if_is_dirty=False)


def master_version(material):
    """The version stamp of a master, 0 when it has none."""
    try:
        return int(unreal.EditorAssetLibrary.get_metadata_tag(material, MASTER_VERSION_TAG) or 0)
    except (ValueError, TypeError):
        return 0


def ensure_master_material(hair=False, skin=False, cards=False):
    """The master material, built when it is missing or older than this
    version of the companion; returns ``(material, built)``.

    An up-to-date master is left as it is, so edits to it are kept. A master
    without a version stamp, made by the companion 0.4.0 or earlier, is rebuilt
    in place, which keeps the material instances that use it.
    """
    hair = hair or cards
    name = CARDS_MASTER_NAME if cards else HAIR_MASTER_NAME if hair else SKIN_MASTER_NAME if skin else MASTER_NAME
    path = f"{MASTER_FOLDER}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        material = unreal.EditorAssetLibrary.load_asset(path)
        if not isinstance(material, unreal.Material):
            raise RuntimeError(f"{path} exists but is not a material")
        version = master_version(material)
        if version >= MASTER_VERSIONS[name]:
            return material, False
        _build_master(material, hair, skin, cards)
        log(f"rebuilt {path} (version {version} -> {MASTER_VERSIONS[name]})")
        return material, True

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset(name, MASTER_FOLDER, unreal.Material, unreal.MaterialFactoryNew())
    if material is None:
        raise RuntimeError(f"could not create {path}")
    _build_master(material, hair, skin, cards)
    log(f"created {path}")
    return material, True


# --------------------------------------------------------------------------- material instances


def _ensure_instance(folder, name, parent, textures):
    """A material instance of the parent with the textures set; returns (instance, changed)."""
    path = f"{folder}/{name}"
    mel = unreal.MaterialEditingLibrary
    changed = False
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        instance = unreal.EditorAssetLibrary.load_asset(path)
        if not isinstance(instance, unreal.MaterialInstanceConstant):
            raise RuntimeError(f"{path} exists but is not a material instance")
    else:
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        instance = tools.create_asset(
            name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew()
        )
        if instance is None:
            raise RuntimeError(f"could not create {path}")
        changed = True
    if instance.get_editor_property("parent") != parent:
        mel.set_material_instance_parent(instance, parent)
        changed = True
    for parameter, texture in textures.items():
        if mel.get_material_instance_texture_parameter_value(instance, parameter) != texture:
            mel.set_material_instance_texture_parameter_value(instance, parameter, texture)
            changed = True
    if changed:
        unreal.EditorAssetLibrary.save_loaded_asset(instance, only_if_is_dirty=False)
    return instance, changed


def _set_cutoff(instance, cutoff):
    """Override the cut-out of the hair master on the instance, or drop the
    override when the cutoff is the master's; returns whether anything changed."""
    overrides = instance.get_editor_property("base_property_overrides")
    override = abs(cutoff - HAIR_CUTOFF) > 1e-5
    changed = False
    if bool(overrides.get_editor_property("override_opacity_mask_clip_value")) != override:
        overrides.set_editor_property("override_opacity_mask_clip_value", override)
        changed = True
    if override and _differs(overrides.get_editor_property("opacity_mask_clip_value"), float(cutoff)):
        overrides.set_editor_property("opacity_mask_clip_value", float(cutoff))
        changed = True
    if changed:
        instance.set_editor_property("base_property_overrides", overrides)
        unreal.MaterialEditingLibrary.update_material_instance(instance)
    return changed


def _set_scalar(instance, parameter, value):
    mel = unreal.MaterialEditingLibrary
    if not _differs(mel.get_material_instance_scalar_parameter_value(instance, parameter), float(value)):
        return False
    mel.set_material_instance_scalar_parameter_value(instance, parameter, float(value))
    return True


def _original_tag(part):
    return f"HumGen3D.Original.{part}"


def _remember_original(mesh, part, material, instance_name):
    """Keep the path of the material Interchange gave a slot, so Haircap As
    Imported can give it back after the companion replaced it."""
    if material is None or material.get_name() == instance_name:
        return False
    tag = _original_tag(part)
    if unreal.EditorAssetLibrary.get_metadata_tag(mesh, tag) == material.get_path_name():
        return False
    unreal.EditorAssetLibrary.set_metadata_tag(mesh, tag, material.get_path_name())
    return True


def _original_material(mesh, part):
    path = unreal.EditorAssetLibrary.get_metadata_tag(mesh, _original_tag(part))
    return unreal.load_asset(path) if path else None


# --------------------------------------------------------------------------- setup


def setup(skeletal_mesh, options=None):
    """Set up one imported Human Generator character.

    Accepts a SkeletalMesh or its asset path. ``options`` are the import options
    (see humgen3d_options); by default the character's own or the project
    defaults. Returns a summary dict, or None when the mesh has no manifest of
    a format this companion reads (it is then left alone).
    """
    mesh = skeletal_mesh
    if isinstance(mesh, str):
        mesh = unreal.load_asset(mesh)
    if not isinstance(mesh, unreal.SkeletalMesh):
        return None
    found = find_manifest(mesh)
    if found is None:
        return None
    manifest, manifest_path = found
    if options is None:
        options = options_module.options_for(mesh)
    materials = _manifest_materials(manifest)
    name = str(manifest.get("name") or os.path.splitext(os.path.basename(manifest_path))[0].split(".")[0])
    folder = _folder_of(mesh)
    manifest_folder = os.path.dirname(manifest_path)
    texture_settings = (manifest.get("settings") or {}).get("textures") or {}
    flip_green = texture_settings.get("normal_map") == "opengl"
    summary = {
        "mesh": mesh.get_name(),
        "name": name,
        "manifest": manifest_path,
        "changed": False,
        "set_up": bool(options["set_up_character"]),
        "masters_built": [],
        "imported_textures": [],
        "fixed_textures": [],
        "instances": {},
        "skipped_slots": [],
    }
    if not options["set_up_character"]:
        log(f"{mesh.get_name()} left as imported (Set Up Character is off)")
        return summary
    cutoff = float(options["hair_cutoff"])

    masters = {}
    for kind, flags in (("lit", {}), ("skin", {"skin": True}), ("hair", {"hair": True}), ("cards", {"cards": True})):
        masters[kind], built = ensure_master_material(**flags)
        if built:
            summary["masters_built"].append(masters[kind].get_name())
            summary["changed"] = True

    instance_names = _instance_names(name, materials)
    lookup = {}
    for material_name, instance_name in instance_names.items():
        for key in (material_name, _asset_name(material_name), instance_name):
            lookup.setdefault(key, material_name)

    slots = list(mesh.materials)
    new_slots = []
    slots_changed = False
    mesh_tagged = False
    for slot in slots:
        slot_name = str(slot.material_slot_name)
        material_name = _slot_material(slot, lookup)
        if material_name is None:
            summary["skipped_slots"].append(slot_name)
            new_slots.append(slot)
            continue
        material = materials[material_name]
        kind = str(material.get("type") or "clothing")
        part = str(material.get("part") or material_name)
        instance_name = instance_names[material_name]
        mesh_tagged |= _remember_original(mesh, part, slot.material_interface, instance_name)
        if kind in HAIRCAP_TYPES and options["haircap"] == options_module.HAIRCAP_AS_IMPORTED:
            # the material Interchange made, also after an earlier setup replaced it
            original = _original_material(mesh, part)
            if original is not None and slot.material_interface != original:
                slot.material_interface = original
                slots_changed = True
            summary["skipped_slots"].append(slot_name)
            new_slots.append(slot)
            continue
        textures = _textures_for_material(
            material, manifest_folder, folder, summary, kind in CARD_TYPES, cutoff, flip_green
        )
        if (
            kind in CARD_TYPES
            and FLOW_PARAMETER in textures
            and options["hair_shading"] == options_module.HAIR_SHADING_MODEL
        ):
            parent = masters["cards"]
        elif kind in HAIR_TYPES:
            parent = masters["hair"]
        elif kind in SKIN_TYPES:
            parent = masters["skin"] if options["skin_subsurface"] else masters["lit"]
        else:
            parent = masters["lit"]
        instance, changed = _ensure_instance(folder, instance_name, parent, textures)
        overridden = False
        if kind in HAIR_TYPES:
            overridden |= _set_cutoff(instance, cutoff)
        if kind in SKIN_TYPES:
            overridden |= _set_scalar(instance, "Specular", options["skin_specular"])
        if overridden:
            unreal.EditorAssetLibrary.save_loaded_asset(instance, only_if_is_dirty=False)
        summary["changed"] |= changed or overridden
        summary["instances"][instance.get_name()] = sorted(textures)
        if slot.material_interface != instance:
            slot.material_interface = instance
            slots_changed = True
        new_slots.append(slot)
    if slots_changed:
        mesh.set_editor_property("materials", new_slots)
    if slots_changed or mesh_tagged:
        unreal.EditorAssetLibrary.save_loaded_asset(mesh, only_if_is_dirty=False)
        summary["changed"] = True

    if summary["changed"]:
        log(f"set up {mesh.get_name()}")
    else:
        log(f"{mesh.get_name()} was already set up, nothing changed")
    return summary


def human_generator_meshes():
    """Every Human Generator skeletal mesh under /Game."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    found = []
    for data in registry.get_assets_by_class(unreal.TopLevelAssetPath("/Script/Engine", "SkeletalMesh")):
        if not str(data.package_path).startswith("/Game"):
            continue
        mesh = data.get_asset()
        if is_human_generator_export(mesh):
            found.append(mesh)
    return found


def setup_selected(context=None):
    """Run setup on the skeletal meshes selected in the Content Browser."""
    assets = []
    if context is not None:
        try:
            browser = context.find_by_class(unreal.ContentBrowserAssetContextMenuContext)
            if browser is not None:
                assets = list(browser.load_selected_objects())
        except Exception:
            assets = []
    if not assets:
        try:
            assets = list(unreal.EditorUtilityLibrary.get_selected_assets())
        except Exception:
            assets = []
    meshes = [a for a in assets if isinstance(a, unreal.SkeletalMesh)]
    if not meshes:
        warn("select the skeletal mesh of a Human Generator character first")
        return []
    results = []
    for mesh in meshes:
        try:
            result = setup(mesh)
        except Exception as e:
            unreal.log_error(f"{LOG_PREFIX}: setting up {mesh.get_name()} failed: {e}")
            continue
        if result is None:
            log(f"{mesh.get_name()} has no Human Generator manifest (<Name>.humgen3d.json) next to its source file, left alone")
        else:
            results.append(result)
    return results
