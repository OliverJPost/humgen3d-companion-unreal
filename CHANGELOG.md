# Changelog

## 0.6.0

- The eyes (`eyes` in the manifest) get a fifth master, `M_HumGen3D_Eye`: it samples the iris
  where the view ray refracted at the cornea meets it, so the iris shifts and bulges with the
  view angle, darkens the limbus, uses half of the baked iris normal so the glint stays one
  highlight, reflects at the roughness of the manifest and the reflectance of water, and has
  the pupil size as a parameter (IrisRadius, PupilRadius, IrisDepth, CorneaIOR, PupilSize,
  LimbusDarken, LimbusWidth, IrisNormal, Roughness, Specular). Default Lit, so it needs no
  project setting. *Eye Master* or *Lit* under *Eyes* in the import settings. The lit master
  with the maps as they are shaded the one-surface game eyes like a painted ball. The engine's
  Eye shading model was tried and dropped: its shadow term drew the shadow of the upper lid as
  a hard dark band across the eye.
- A material without an ORM map gets the plain roughness and metallic its manifest entry lists
  (`values`, Human Generator 4.0.35 and later) as the `Roughness` and `Metallic` parameters of
  its instance, with `UseORM` 0 so the master reads them instead of the ORM texture. The eyes
  have a roughness of 0.1 and were shaded with the grey of the default ORM texture. The four
  masters are rebuilt once for the new parameters (version 2); exports without `values` keep the
  defaults (roughness 0.5, metallic 0).

## 0.5.0

- A character is only set up when the export manifest `<Name>.humgen3d.json` (Human Generator
  4.0.32 and later) is next to its source file and lists that file as the character or one of its
  animations. Exports without a manifest are no longer set up: they stay as Unreal imports them.
  The recognition by the `*_Skin` / `*_Eyes` material names and the `<Name>_Skin` textures is gone.
- The manifest's material types and texture files are used instead of name suffixes to find the
  skin, hair cards, haircaps, eyes and their textures, so exports with the plain or a custom
  naming scheme are set up too, not only the Unreal prefixes. Normal maps of exports with OpenGL
  normals get their green channel flipped.
- A manifest of a newer export format than this companion reads is skipped with a warning to
  update the companion.
- The master materials carry a version stamp (asset metadata `HumGen3D.MasterVersion`). An import
  only rebuilds a master that is missing or older, in place; edits to an up-to-date master are no
  longer reverted. Masters of 0.4.0 and earlier have no stamp and are rebuilt once. This replaces
  the checks for the default values of earlier versions.
- A rebuilt master is cleared completely first (one call of the engine's delete-all only removes
  part of the nodes). The Backlit pin of the cards master was never connected on Unreal 5.8 (the
  pin is not reachable from Python there); it is now logged as such instead of a warning, and the
  README no longer claims a Backlit parameter.
- `Config/HumGen3DCompanion.json` and the `HumGen3D.ImportOptions` metadata carry a `version` (1).
- The README states the tested range: Unreal Engine 5.8 with the Interchange FBX import. Install
  steps and download moved to the
  [documentation](https://humgen3d.com/docs/process/unreal-engine-companion).

## 0.4.0

- Import settings. After the first import of a character in the editor a dialog shows its
  options before it is set up (never in a commandlet or an unattended run); **Human Generator 3D >
  Import Settings...** on the skeletal mesh changes them later, stored as the metadata tag
  `HumGen3D.ImportOptions` of the mesh; **Tools > Human Generator 3D > Project Defaults...** sets
  the project defaults, saved in `Config/HumGen3DCompanion.json`. The options: set up the
  character at all, card shading (Hair shading model or masked lit), hair cutoff (an override on
  the instances and the coverage threshold of the card textures), haircap set up or as imported
  (the Interchange material is remembered and given back), Subsurface Profile on the skin, skin
  specular, and whether the dialog is shown. The defaults are what 0.3.0 did.

## 0.3.0

- New master `M_HumGen3D_HairCards` for the hair cards: the hair master with the *Hair* shading
  model, the `*_Flow` map of the export (Human Generator 4.0.28 and later) as the strand tangent
  and Scatter, Backlit and Lightness scalar parameters, so the highlights run along the strands.
  The base color is the baked color times Lightness, squared: the Hair model scatters the root
  of its base color, which turned the baked color pale. Scatter (0.8) is a parameter on the
  Metallic pin; the metallic of the ORM map that every master starts with there is 0 for hair,
  which left only the highlights and the hair near black. Cards of an export without the flow
  map keep the hair master.
- The Specular of the hair master, which the haircaps use, is 0.05 instead of 0.25: the caps
  have no roughness map and showed as a glossy spot in every parting. A master that still has
  the old default is updated. Its Metallic is 0 instead of the blue of the ORM map, which for
  a haircap is the grey of the default texture.
- `*_Flow` textures are imported as Masks with sRGB off.
- The cards master fades a card out when the camera looks along it (`EdgeFade` scalar parameter,
  0.25; 0 turns it off), where it would be a line with all its strands pressed into it. The card
  keeps a share of its opacity (`EdgeFadeFloor`, 0.7). Added
  to a cards master of an earlier version on the next import.
- Hair is cut out at alpha 0.2 instead of 0.5. At 0.5 the fine strands and the anti-aliased
  edges of the baked alpha were lost: bangs were a stipple over the forehead and short hair
  showed the skin at the nape. Masters and textures of an earlier version are updated.


## 0.2.0

- Hair cards are cut out at alpha 0.5, the Unreal default, as the export now bakes the strand
  coverage of the hair atlas into the alpha; the hair master dithers the opacity mask, which
  temporal anti-aliasing resolves to soft strands.
- The base color textures of the hair cards get alpha coverage mip scaling with the cutoff as
  threshold, so the strands keep their width at a distance.
- New master `M_HumGen3D_Skin` with the Subsurface Profile shading model, used by the `_Skin`
  material instance.
- Every master gets a Specular scalar parameter, 0.3 on the skin and 0.25 on the hair master,
  closer to the Blender materials than Unreal's default of 0.5. Masters of version 0.1.0 are
  updated in place.
- The import check reports the dithering, shading model and alpha coverage settings.

## 0.1.0

First version of the Human Generator 3D Companion for Unreal Engine.

- Sets up a character exported with the Unreal recipe of Human Generator's Process tab after
  Unreal imports its FBX, from the editor's post-import event or from **Human Generator 3D > Set Up
  Selected Characters** in the Tools menu and the skeletal mesh context menu.
- Imports the ORM textures Interchange skips as Masks textures with sRGB off, and checks that the
  normal maps are Normalmap textures with sRGB off.
- Creates the master materials `M_HumGen3D_Master` and `M_HumGen3D_Hair` (masked, two-sided,
  base color alpha as opacity mask) in `/Game/HumGen3D/`.
- Creates a material instance `MI_<Name>_<Part>` per material slot with the base color, normal and
  ORM maps set, hair cards and caps on the hair master, and assigns them to the mesh.
- Recognises both the `T_<Name>_<Part>_BC` and the `<Name>_<Part>_BaseColor` texture naming.
- Running the setup twice changes nothing.
- `Scripts/unreal_check.py` imports an FBX from the command line, runs the setup twice and reports
  the result as JSON.
