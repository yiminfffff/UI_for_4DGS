"""Read-only plugin checks independent of trained models or CUDA."""
from . import core


def inspect(project,engine):
    try:
        if not project.is_file() or project.suffix.lower() != ".uproject":
            return dict(status="Select Project",message="Choose an existing .uproject file.",can_install=False)
        version = core.read_json(engine/"Engine/Build/Build.version")
        if (version["MajorVersion"],version["MinorVersion"]) != (5,8):
            raise ValueError("The bundled GS4D player targets UE 5.8. Choose a matching engine or rebuild the plugin.")
        source = core.ROOT/"unreal/GS4D"
        expected = core.read_json(source/"Binaries/Win64/UnrealEditor.modules")
        engine_id = core.read_json(engine/"Engine/Binaries/Win64/UnrealEditor.modules")["BuildId"]
        if expected["BuildId"] != engine_id:
            raise ValueError("The bundled binary does not match this exact engine build. Rebuild GS4D for this engine.")
        target = project.parent/"Plugins/GS4D"
        if not (target/"GS4D.uplugin").is_file():
            return dict(status="Missing",message="GS4D is missing from this project. Install Plugin copies the player and enables its import dependencies.",can_install=True)
        descriptor = core.read_json(project)
        enabled = {p["Name"] for p in descriptor.get("Plugins",[]) if p.get("Enabled")}
        if not {"GS4D","PythonScriptPlugin","EditorScriptingUtilities"}.issubset(enabled):
            return dict(status="Disabled",message="GS4D or its import dependencies are disabled. Install / Update Plugin will enable them.",can_install=True)
        modules = target/"Binaries/Win64/UnrealEditor.modules"
        if not modules.is_file() or core.read_json(modules).get("BuildId") != engine_id:
            return dict(status="Needs Update",message="The project plugin binaries are missing or belong to another engine build.",can_install=True)
        for name in ("UnrealEditor-GS4D.dll","UnrealEditor-GS4DEditor.dll"):
            if not (target/"Binaries/Win64"/name).is_file():
                return dict(status="Needs Update",message="A required GS4D binary is missing: "+name,can_install=True)
        marker = target/"workbench-install.json"
        previous = core.read_json(marker).get("files",{}) if marker.is_file() else {}
        outdated = False
        for path in source.rglob("*"):
            if not path.is_file() or any(x in path.parts for x in ("Intermediate","Saved")) or path.suffix in (".pdb",".obj"): continue
            relative = path.relative_to(source); installed = target/relative
            if not installed.is_file(): outdated = True; continue
            checksum = core.digest(installed)
            if checksum != core.digest(path):
                if checksum != previous.get(relative.as_posix()):
                    return dict(status="Modified",message="The project plugin has local edits. Back up and update it manually; automatic installation will preserve these files.",can_install=False)
                outdated = True
        return dict(status="Needs Update" if outdated else "Ready",message="A newer bundled player is available." if outdated else
            "GS4D runtime/editor binaries match the engine. The player and import dependencies are enabled for this project.",can_install=outdated)
    except Exception as exc:
        return dict(status="Incompatible",message=str(exc),can_install=False)
