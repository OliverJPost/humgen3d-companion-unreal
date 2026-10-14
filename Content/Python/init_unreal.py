"""Editor start-up of the Human Generator 3D Companion for Unreal Engine.

The Python Editor Script Plugin runs this file from the plugin's
Content/Python folder when the editor starts. It hooks the import subsystem,
so a character exported from Human Generator is set up right after Unreal
imports it, when the export's manifest (<Name>.humgen3d.json) is next to
the imported file (after showing the import settings of a new character, see
humgen3d_options), and adds "Human Generator 3D" with Set Up Selected
Characters and Import Settings to the Tools menu and the context menu of
skeletal meshes in the Content Browser, and Project Defaults to the Tools menu.
"""
import unreal

import humgen3d_companion as companion
import humgen3d_options as options

OWNER = "HumGen3DCompanion"
_pending = []
_tick_handle = None
# Python callables bound to a delegate are UObjects that only a live Python wrapper of
# that delegate keeps referenced; without these globals garbage collection drops the hooks
_import_subsystem = None
_post_import_delegate = None
_reimport_delegate = None


def _running_as_commandlet():
    # a commandlet has no Slate ticks, so deferred work would never run there
    return "-run=" in unreal.SystemLibrary.get_command_line().lower()


def _run_pending(_delta_seconds=0.0):
    global _tick_handle
    if _tick_handle is not None:
        unreal.unregister_slate_post_tick_callback(_tick_handle)
        _tick_handle = None
    paths, _pending[:] = list(_pending), []
    # only meshes whose source file has a Human Generator manifest next to it
    meshes = []
    for mesh in (unreal.load_asset(p) for p in paths):
        if mesh is None:
            continue
        if companion.is_human_generator_export(mesh):
            meshes.append(mesh)
        else:
            companion.log(
                f"{mesh.get_name()} left as imported: no Human Generator manifest (*.humgen3d.json) "
                f"lists its source file {companion.source_file(mesh)}"
            )
    _ask_new_characters(meshes)
    for mesh in meshes:
        try:
            companion.setup(mesh)
        except Exception as e:
            unreal.log_error(f"{companion.LOG_PREFIX}: setting up {mesh.get_path_name()} failed: {e}")


def _ask_new_characters(meshes):
    """Show the import settings of characters imported for the first time, when
    someone is there to answer. Cancel keeps the project defaults; either way
    the dialog is not shown again for them."""
    new = [m for m in meshes if options.stored_options(m) is None]
    if not new or not options.interactive() or not options.project_defaults()["show_dialog_on_import"]:
        return
    try:
        if options.edit_character_options(new):
            return
    except Exception as e:
        unreal.log_warning(f"{companion.LOG_PREFIX}: could not show the import settings ({e})")
    defaults = options.options_for(new[0])
    for mesh in new:
        options.store_options(mesh, True, defaults)


def _schedule(mesh):
    global _tick_handle
    path = mesh.get_path_name()
    if path in _pending:
        return
    _pending.append(path)
    if _running_as_commandlet():
        _run_pending()
        return
    # Interchange broadcasts while its completion task still runs; do the work on the next tick
    if _tick_handle is None:
        _tick_handle = unreal.register_slate_post_tick_callback(_run_pending)


def _on_asset_imported(event, created_object):
    if not isinstance(created_object, unreal.SkeletalMesh):
        return
    # whether it is a Human Generator export is decided on the next tick, when
    # the import has finished and the source file of the mesh is recorded
    _schedule(created_object)


def _on_asset_post_import(_factory, created_object):
    _on_asset_imported("post-import", created_object)


def _on_asset_reimport(created_object):
    # Interchange also reports a finished skeletal mesh here, right after the import
    _on_asset_imported("reimport", created_object)


def _register_import_hooks():
    global _import_subsystem, _post_import_delegate, _reimport_delegate
    _import_subsystem = unreal.get_editor_subsystem(unreal.ImportSubsystem)
    if _import_subsystem is None:
        unreal.log_warning(f"{companion.LOG_PREFIX}: no import subsystem, characters are set up from the menu only")
        return
    _post_import_delegate = _import_subsystem.on_asset_post_import
    _post_import_delegate.add_callable(_on_asset_post_import)
    _reimport_delegate = _import_subsystem.on_asset_reimport
    _reimport_delegate.add_callable(_on_asset_reimport)


@unreal.uclass()
class HumGen3DSetUpSelectedCharacters(unreal.ToolMenuEntryScript):
    @unreal.ufunction(override=True)
    def execute(self, context):
        companion.setup_selected(context)


@unreal.uclass()
class HumGen3DImportSettingsEntry(unreal.ToolMenuEntryScript):
    @unreal.ufunction(override=True)
    def execute(self, context):
        meshes = [m for m in _selected_meshes(context) if companion.is_human_generator_export(m)]
        if not meshes:
            unreal.log_warning(f"{companion.LOG_PREFIX}: select the skeletal mesh of a Human Generator character first")
            return
        for mesh in options.edit_character_options(meshes):
            companion.setup(mesh)


@unreal.uclass()
class HumGen3DProjectDefaultsEntry(unreal.ToolMenuEntryScript):
    @unreal.ufunction(override=True)
    def execute(self, context):
        if not options.edit_project_defaults():
            return
        users = [m for m in companion.human_generator_meshes() if (options.stored_options(m) or {}).get("use_project_defaults", True)]
        if not users:
            return
        answer = unreal.EditorDialog.show_message(
            "Human Generator 3D Project Defaults",
            f"Set up the {len(users)} characters that use the project defaults again with the new defaults?",
            unreal.AppMsgType.YES_NO,
        )
        if answer == unreal.AppReturnType.YES:
            for mesh in users:
                companion.setup(mesh)


def _selected_meshes(context):
    assets = []
    try:
        browser = context.find_by_class(unreal.ContentBrowserAssetContextMenuContext) if context else None
        if browser is not None:
            assets = list(browser.load_selected_objects())
    except Exception:
        assets = []
    if not assets:
        assets = list(unreal.EditorUtilityLibrary.get_selected_assets())
    return [a for a in assets if isinstance(a, unreal.SkeletalMesh)]


ENTRIES = (
    (HumGen3DSetUpSelectedCharacters, "SetUpSelectedCharacters", "Set Up Selected Characters",
     "Create the material instances of the selected Human Generator characters and import their missing textures"),
    (HumGen3DImportSettingsEntry, "ImportSettings", "Import Settings...",
     "How the companion sets up the selected Human Generator characters: the project defaults or their own options"),
    (HumGen3DProjectDefaultsEntry, "ProjectDefaults", "Project Defaults...",
     "How the companion sets up Human Generator characters in this project, saved in Config/HumGen3DCompanion.json"),
)


def _add_entries(menus, parent_menu_name, section, entries):
    parent = menus.extend_menu(parent_menu_name)
    submenu = parent.add_sub_menu(OWNER, section, "HumGen3D", "Human Generator 3D")
    for cls, name, label, tooltip in entries:
        entry = cls()
        entry.init_entry(OWNER, submenu.menu_name, "", name, label, tooltip)
        submenu.add_menu_entry_object(entry)


def _register_menus():
    menus = unreal.ToolMenus.get()
    if menus is None:
        return
    _add_entries(menus, "LevelEditor.MainMenu.Tools", "Tools", ENTRIES)
    _add_entries(menus, "ContentBrowser.AssetContextMenu.SkeletalMesh", "GetAssetActions", ENTRIES[:2])
    menus.refresh_all_widgets()


for _step in (_register_import_hooks, _register_menus):
    try:
        _step()
    except Exception as _e:
        unreal.log_warning(f"{companion.LOG_PREFIX}: {_step.__name__} failed: {_e}")
