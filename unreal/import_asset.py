"""Run inside Unreal's Python commandlet. Import only into a new asset folder."""
import json
import math
import os
from pathlib import Path
import traceback

import unreal

request = json.loads(Path(os.environ["GS4D_IMPORT_REQUEST"]).read_text(encoding="utf-8-sig"))
report = Path(request["report"])
try:
    destination = request["destination"]
    if unreal.EditorAssetLibrary.does_directory_exist(destination):
        raise RuntimeError("The destination asset folder already exists. Choose a new asset name.")
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", request["file"])
    task.set_editor_property("destination_path", destination)
    task.set_editor_property("destination_name", "Sequence")
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", False)
    task.set_editor_property("save", False)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    paths = task.get_editor_property("imported_object_paths")
    if not paths:
        raise RuntimeError("The GS4D importer did not create an asset. Check the binary format and plugin log.")
    asset = unreal.load_asset(paths[0])
    material = unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_Gaussian", destination,
        unreal.Material, unreal.MaterialFactoryNew())
    material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    material.set_editor_property("two_sided", True)
    edit = unreal.MaterialEditingLibrary
    uv = edit.create_material_expression(material, unreal.MaterialExpressionTextureCoordinate)
    color = edit.create_material_expression(material, unreal.MaterialExpressionVertexColor)
    opacity = edit.create_material_expression(material, unreal.MaterialExpressionCustom)
    opacity.set_editor_property("code", "float2 p=(UV-0.5)*6.0; return min(0.99, Alpha*exp(-0.5*dot(p,p)));")
    opacity.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT1)
    inputs = []
    for name in ("UV", "Alpha"):
        entry = unreal.CustomInput()
        entry.set_editor_property("input_name", name)
        inputs.append(entry)
    opacity.set_editor_property("inputs", inputs)
    assert edit.connect_material_expressions(uv, "", opacity, "UV"), "UV connection failed"
    assert edit.connect_material_expressions(color, "A", opacity, "Alpha"), "Alpha connection failed"
    linear = edit.create_material_expression(material, unreal.MaterialExpressionCustom)
    linear.set_editor_property("code", "return lerp(C/12.92, pow((C+0.055)/1.055, 2.4), step(0.04045,C));")
    linear.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    input_color = unreal.CustomInput()
    input_color.set_editor_property("input_name", "C")
    linear.set_editor_property("inputs", [input_color])
    assert edit.connect_material_expressions(color, "", linear, "C"), "Color space input failed"
    assert edit.connect_material_property(linear, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR), "Color connection failed"
    assert edit.connect_material_property(opacity, "", unreal.MaterialProperty.MP_OPACITY), "Opacity connection failed"
    edit.recompile_material(material)
    asset.set_editor_property("splat_material", material)
    if not unreal.EditorAssetLibrary.save_loaded_asset(material) or not unreal.EditorAssetLibrary.save_loaded_asset(asset):
        raise RuntimeError("Unreal could not save the imported assets.")
    result = dict(status="complete", asset=asset.get_path_name(), material=material.get_path_name(),
                  points=asset.get_editor_property("point_count"), frames=asset.get_editor_property("frame_count"))
    if request.get("create_test_level"):
        level = destination + "/PlaybackTest"
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).new_level(level)
        actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        actor = actors.spawn_actor_from_class(unreal.GS4DActor, unreal.Vector(0, 0, 0))
        actor.set_actor_label("4DGS Playback")
        component = actor.get_editor_property("gaussian_component")
        component.set_sequence(asset)
        component.set_editor_property("preview_in_editor", True)
        camera = actors.spawn_actor_from_class(unreal.CameraActor, unreal.Vector(350, 0, 150))
        camera.set_actor_rotation(unreal.MathLibrary.find_look_at_rotation(camera.get_actor_location(), unreal.Vector()), False)
        camera.get_component_by_class(unreal.CameraComponent).set_field_of_view(54.433)
        unreal.EditorLevelLibrary.set_level_viewport_camera_info(camera.get_actor_location(), camera.get_actor_rotation())
        unreal.EditorLevelLibrary.save_current_level()
        result["level"] = level
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    unreal.log("GS4D_IMPORT_COMPLETE " + json.dumps(result))
except Exception:
    report.write_text(json.dumps(dict(status="failed", error=traceback.format_exc()), indent=2), encoding="utf-8")
    raise
