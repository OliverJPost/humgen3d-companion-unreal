# Human Generator 3D Companion for Unreal Engine

A content-only Unreal Engine plugin (editor Python, no C++) that finishes what Unreal's own FBX
import leaves undone for a character exported from [Human Generator](https://humgen3d.com)'s
Process tab, made for the **Unreal** recipe.

It only touches a character whose export manifest, `<Name>.humgen3d.json`, is next to the imported
FBX (Human Generator 4.0.32 and later write it with every export). The manifest says which file
is the character, what each of its materials is (skin, eyes, teeth, haircap, hair cards,
clothing...) and which texture files belong to them, so the companion works with every naming
scheme of the export and never mistakes another character for a Human Generator one. A file
without a manifest is left exactly as Unreal imports it. A manifest made by a newer Human Generator
than the companion knows is skipped with a warning in the Output Log to update the companion.

Unreal 5 imports the character's FBX through Interchange and gets the mesh, the Mannequin skeleton
and the morph targets right, but every material becomes an instance of the generic FBX Phong
material, the ORM textures are not imported at all (nothing in the FBX references them) and hair
cards render opaque and single-sided. The companion sets up, right after the import or from a menu
entry:

- the ORM textures (occlusion R, roughness G, metallic B) and the flow maps of the hair cards
  (strand direction RG, a noise per strand B) imported from the files the manifest lists as
  **Masks** textures with sRGB off; normal maps checked to be **Normalmap** with sRGB off, with
  the green channel flipped when the export wrote OpenGL normal maps. Exports with another
  packing than ORM (metallic-smoothness, metallic-roughness, separate maps) get the master's
  default ORM texture
- four master materials in `/Game/HumGen3D/`: `M_HumGen3D_Master` (BaseColor, Normal and ORM
  texture parameters, the ORM channels split into Ambient Occlusion, Roughness and Metallic, a
  Specular scalar parameter, and Roughness, Metallic and UseORM scalar parameters for a material
  without an ORM map, which gets the plain values its manifest entry lists),
  `M_HumGen3D_Skin` (the same with the *Subsurface Profile* shading model, as the skin was
  rendered with subsurface scattering in Blender and looks flat and harsh without it; no profile
  is assigned, so the engine's default skin profile applies until you set one) and
  `M_HumGen3D_Hair` (the same, masked at 0.2 with *Dither Opacity Mask*, two-sided, base color
  alpha as the opacity mask: the export bakes the strand coverage of the hair atlas into the
  alpha, and the dithering under temporal anti-aliasing gives soft strands the way Blender's hashed
  transparency renders the cards) and `M_HumGen3D_HairCards` (the hair master with the *Hair*
  shading model: the red and green of the Flow texture parameter, scaled to -1..1, as the
  *Tangent*, so the highlights run along the strands instead of across the flat card, and
  Scatter 0.8 and Lightness 1 as scalar parameters; the base color is the baked color times Lightness, squared, as the Hair model scatters the root of its base color; the Backlit pin is not reachable from Python on Unreal 5.8, so it stays at the engine default). The Specular parameter defaults to 0.3 on the
  skin master, 0.05 on the hair master (the haircaps) and 0.4 on the cards master: the Blender materials reflect
  far less than Unreal's default of 0.5, which made the skin look wet
- the base color textures of the hair cards get *Alpha Coverage* mip scaling with the cutoff as
  threshold, so the strands keep their width at a distance instead of thinning out
- one material instance per material slot of the mesh that the manifest lists,
  `MI_<Name>_<Part>` next to the mesh, with the textures the manifest gives that material set
  (a material without an ORM map gets the plain roughness and metallic of its manifest entry); the skin uses the skin master, hair cards with a flow map the
  cards master, the haircaps and cards without one the hair master, everything else the lit master
- the instances assigned to the skeletal mesh's material slots

Running the setup again on a character that is already set up changes nothing.

The master materials are built once and stamped with their version (the asset metadata tag
`HumGen3D.MasterVersion`). An import only rebuilds a master that is missing or older than the
companion's own version of it, in place, so the instances keep working; edits to an up-to-date
master are kept.

What Unreal does by itself with the plain export, and what it does not, is on the
[Export to Unreal Engine](https://humgen3d.com/docs/process/export-to-unreal-engine) page.

## Install

The download and the install steps are on
[humgen3d.com/docs/process/unreal-engine-companion](https://humgen3d.com/docs/process/unreal-engine-companion).
In short: the folder goes into your project as `<Project>/Plugins/HumGen3DCompanion/`, and **Python
Editor Script Plugin** and the companion are enabled in **Edit > Plugins**.

The plugin has no C++ modules, so it needs no compiling. Tested with Unreal Engine 5.8 only, with
the Interchange FBX import (the engine's default); other versions and the legacy FBX importer are
not verified.

## Use

Import the character's FBX as usual (drag it into the Content Browser; keep the
`<Name>.humgen3d.json` manifest and the `Textures/` folder next to it). The companion hooks the
editor's post-import event (`ImportSubsystem.on_asset_post_import`, which Interchange raises for
every imported asset; verified with the import check below on 5.8), checks for the manifest next to
the imported file and sets the character up as soon as the import finishes. The Output Log shows `Human Generator 3D Companion: set up
<mesh>`. Reimporting the mesh runs it again, which changes nothing when everything is in place.

To run it by hand, for example on a character imported before the plugin was installed, select the
skeletal mesh in the Content Browser and use **Human Generator 3D > Set Up Selected Characters**,
either in the asset's right-click menu or in the main **Tools** menu. Meshes that are not Human
Generator exports (no manifest next to their source file) are left alone.

## Import settings

What the companion sets up can be changed in two places; the defaults below are what it does
without them.

**After the first import** of a character in the editor, the companion shows its import settings
in a dialog before it sets it up: *Use Project Defaults*, or the character's own options. *OK*
stores them, *Cancel* keeps the project defaults; the dialog is not shown again for that
character. Never in a commandlet or an unattended run, so automated imports never wait on it.

**Per character**: right-click the skeletal mesh and use **Human Generator 3D > Import
Settings...** (also in **Tools > Human Generator 3D**, for the selected meshes). The options are
stored as the metadata tag `HumGen3D.ImportOptions` of the skeletal mesh (JSON with a `version`),
so they are kept on reimport and travel with the asset. *OK* sets the character up again with them.

**Project defaults**: **Tools > Human Generator 3D > Project Defaults...**, saved in
`Config/HumGen3DCompanion.json` of the project (JSON with a `version`), so they go into version
control. After saving, the
companion offers to set up the characters that use the defaults again.

| Option | Default | What it does |
|---|---|---|
| Set Up Character | on | Off leaves the character as Interchange imported it |
| Card Shading | Hair Shading Model | *Masked Lit* gives the cards the hair master (lit as flat surfaces) instead of `M_HumGen3D_HairCards` |
| Hair Cutoff | 0.2 | Opacity below which the cards and haircaps are cut out (an override of *Opacity Mask Clip Value* on their instances), and the alpha coverage threshold of the card textures |
| Haircap | Set Up | *As Imported* gives the haircap slots the material Interchange made back (remembered in the metadata tag `HumGen3D.Original.<Part>`) |
| Subsurface Profile | on | Off gives the skin the plain master (Default Lit) |
| Skin Specular | 0.3 | The *Specular* parameter of the skin instance; 0.5 is the engine default, which made the skin look wet |
| Show Dialog On Import | on | Project defaults only: whether the dialog above is shown |

## Import check

`Scripts/unreal_check.py` imports an exported FBX through Interchange from the command line, runs
the setup on it twice (the FBX needs its manifest next to it) and writes a JSON report with the bones, morph targets, textures (with their
compression settings), master materials, material instances (parent, texture parameters, blend mode,
two-sidedness) and whether the second run changed anything. With the plugin and the Python Editor
Script Plugin enabled in a project:

```
HG_FBX=<path/Name.fbx> HG_REPORT=report.json UnrealEditor-Cmd <Project.uproject> -run=pythonscript -script=<Project>/Plugins/HumGen3DCompanion/Scripts/unreal_check.py -unattended -nopause -nosplash
```

## Status

Early access. Materials and textures are what the companion sets up today; an IK Rig and retargeter
for Mannequin animations are planned. Feedback on what the export should set up for you goes to
[https://humgen3d.com/feedback/process](https://humgen3d.com/feedback/process).

## License

MIT. The Human Generator add-on for Blender is a separate, paid product; this companion works on
what it exports.
