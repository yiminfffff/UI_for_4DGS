"""Install the local player, bake a selected snapshot, and import into a closed UE project."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback

from gs_workbench import core
from ue_export import bake


def emit(event, **payload):
    print("@WB@" + json.dumps(dict(event=event, **payload)), flush=True)


def install_plugin(project):
    source = core.ROOT / "unreal/GS4D"
    target = project.parent / "Plugins/GS4D"
    marker = target / "workbench-install.json"
    files = [p for p in source.rglob("*") if p.is_file() and
             not any(name in p.parts for name in ("Intermediate", "Saved")) and p.suffix not in (".pdb", ".obj")]
    if not (source / "Binaries/Win64/UnrealEditor-GS4D.dll").is_file():
        raise ValueError("The local UE 5.8 plugin has not been built. See unreal/README.md.")
    if target.exists():
        previous = core.read_json(marker).get("files", {}) if marker.is_file() else {}
        for path in files:
            relative = path.relative_to(source).as_posix()
            existing = target / relative
            if existing.is_file() and core.digest(existing) not in (core.digest(path), previous.get(relative)):
                raise ValueError("The target GS4D plugin has local modifications. Back it up and update it manually.")
    target.mkdir(parents=True, exist_ok=True)
    installed = {}
    for path in files:
        relative = path.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_file() or core.digest(destination) != core.digest(path):
            shutil.copy2(path, destination)
        installed[relative.as_posix()] = core.digest(destination)
    core.write_json(marker, dict(version=1, files=installed))
    value = core.read_json(project)
    backup = project.with_suffix(".uproject.before-gs4d")
    if not backup.exists():
        shutil.copy2(project, backup)
    plugins = value.setdefault("Plugins", [])
    for name in ("GS4D", "PythonScriptPlugin", "EditorScriptingUtilities"):
        existing = next((item for item in plugins if item["Name"] == name), None)
        if existing is None:
            plugins.append(dict(Name=name, Enabled=True))
        else:
            existing["Enabled"] = True
    core.write_json(project, value)


def transfer(run, project, engine, iteration=None):
    import psutil
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise ValueError("Choose an existing .uproject file.")
    version = core.read_json(engine / "Engine/Build/Build.version")
    if (version["MajorVersion"], version["MinorVersion"]) != (5, 8):
        raise ValueError("This plugin build targets UE 5.8.")
    editor = engine / "Engine/Binaries/Win64/UnrealEditor-Cmd.exe"
    for process in psutil.process_iter(["name"]):
        if (process.info["name"] or "").lower() in ("unrealeditor.exe", "unrealeditor-cmd.exe"):
            raise ValueError("Close Unreal Editor instances before importing assets into a project.")
    local_modules = core.read_json(core.ROOT / "unreal/GS4D/Binaries/Win64/UnrealEditor.modules")
    engine_modules = core.read_json(engine / "Engine/Binaries/Win64/UnrealEditor.modules")
    if local_modules["BuildId"] != engine_modules["BuildId"]:
        raise ValueError("The plugin binary does not match this exact UE build. Rebuild GS4D for the selected engine.")
    name = re.sub("[^A-Za-z0-9_]", "_", run.name) + "_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    output = run / "ue-exports" / (name + ".gs4d")
    emit("status", message="Baking the selected model snapshot for Unreal...")
    def progress(current, total):
        if (run / "stop.request").exists():
            raise InterruptedError("UE export stopped. Training files are unchanged.")
        emit("status", message=f"Baking UE frame {current} / {total}")
    metadata = bake(run, output, iteration, progress)
    if (run / "stop.request").exists():
        raise InterruptedError("UE export stopped before project installation.")
    emit("status", message="Installing the local GS4D plugin and importing the asset...")
    install_plugin(project)
    job = project.parent / "Saved/GS4DImport" / name
    job.mkdir(parents=True, exist_ok=False)
    report = job / "result.json"
    request = job / "request.json"
    destination = "/Game/GS4D/" + name
    core.write_json(request, dict(file=output.as_posix(), destination=destination, report=report.as_posix()))
    environment = dict(os.environ, GS4D_IMPORT_REQUEST=request.as_posix())
    for key in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
        environment.pop(key, None)
    with (job / "commandlet.log").open("w", encoding="utf-8") as log:
        result = subprocess.run([str(editor), project.as_posix(), "-run=pythonscript",
            "-script=" + (core.ROOT / "unreal/import_asset.py").as_posix(), "-unattended", "-NullRHI", "-nosplash",
            "-abslog=" + (job / "unreal.log").as_posix()], env=environment, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
    status = core.read_json(report) if report.is_file() else {}
    if result.returncode != 0 or status.get("status") != "complete":
        raise RuntimeError("UE import did not complete. See " + str(job) + "\n" + status.get("error", ""))
    emit("ue_complete", message="Asset added to Unreal: " + status["asset"], project=str(project),
         asset=status["asset"], report=str(report), export=metadata)
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path)
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--iteration", type=int)
    args = parser.parse_args()
    try:
        if args.install_only:
            from gs_workbench.plugin_status import inspect
            status = inspect(args.project.resolve(),args.engine.resolve())
            if not status.get("can_install") and status["status"] != "Ready": raise ValueError(status["message"])
            listing = subprocess.check_output(["tasklist.exe","/fo","csv","/nh"],creationflags=subprocess.CREATE_NO_WINDOW).decode(errors="replace").lower()
            if '"unrealeditor.exe"' in listing or '"unrealeditor-cmd.exe"' in listing:
                raise ValueError("Close Unreal Editor before installing the plugin.")
            install_plugin(args.project.resolve())
            emit("complete",message="GS4D installed and enabled for this project.")
        else:
            if args.run is None: raise ValueError("Choose a trained run before exporting an asset.")
            transfer(args.run.resolve(), args.project.resolve(), args.engine.resolve(), args.iteration)
    except InterruptedError as exc:
        emit("stopped", message=str(exc))
    except Exception as exc:
        traceback.print_exc()
        emit("error", message=str(exc))
        sys.exit(1)
