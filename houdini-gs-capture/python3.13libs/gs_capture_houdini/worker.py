"""Isolated hython capture worker. The source HIP is never saved by this process."""
import argparse
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import sys
import tempfile
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gs_capture_houdini import dataset


def emit(event, **values):
    print("@GSC@" + json.dumps(dict(event=event, **values), ensure_ascii=True), flush=True)


def preview_plan(plan):
    plan = copy.deepcopy(plan)
    sequences = sorted({r["sequence"] for r in plan["records"]})
    wanted = {(sequences[0], "CAM001"), (sequences[len(sequences) // 2], "CAM009"),
              (sequences[-1], "CAM005")}
    plan["records"] = [r for r in plan["records"] if (r["sequence"], r["camera"]) in wanted]
    plan["preview"] = True
    plan.pop("fingerprint")
    return dict(plan, fingerprint=dataset.fingerprint(plan))


@contextmanager
def output_lock(root):
    # Place the lock beside the output so an empty dataset stays recognizably empty.
    import msvcrt
    root = Path(root).resolve()
    root.parent.mkdir(parents=True, exist_ok=True)
    lock_path = root.parent / ("." + root.name + ".gs_capture.lock")
    stream = open(lock_path, "a+b")
    locked = False
    try:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            locked = True
        except OSError as exc:
            raise RuntimeError("Another capture process is using this output folder.") from exc
        yield
    finally:
        if locked:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        stream.close()


def run(job):
    import hou
    from gs_capture_houdini import scene, render
    full_plan = job["plan"]
    source = full_plan["source"]
    contract = {key: value for key, value in full_plan.items() if key != "fingerprint"}
    if dataset.fingerprint(contract) != full_plan["fingerprint"]:
        raise ValueError("The capture job was modified after validation.")
    if dataset.digest_file(source["scene"]) != source["scene_sha256"]:
        raise ValueError("The HIP file changed after validation. Validate again before rendering.")
    hou.hipFile.load(source["scene"], suppress_save_prompt=True, ignore_load_warnings=True)
    if hou.licenseCategory() == hou.licenseCategoryType.Apprentice:
        emit("status", message="Apprentice license: renders contain a Houdini watermark. Use a suitable license for training captures.")
    emit("status", message="Checking the saved scene and fixed cameras...")
    actual = scene.collect_plan(full_plan["settings"], source["source_lop"], source["targets"], require_saved=False)
    if actual["fingerprint"] != full_plan["fingerprint"]:
        raise ValueError("The saved scene differs from the validated scene. Save and validate it again.")
    plan = preview_plan(full_plan) if job["preview"] else full_plan
    with output_lock(job["output"]):
        manifest_path = Path(job["output"]) / "capture_manifest.json"
        license_category = str(hou.licenseCategory())
        if manifest_path.is_file():
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            if old.get("license_category", license_category) != license_category:
                raise ValueError("The Houdini license category changed. Choose a new output folder to avoid mixing watermarked and clean renders.")
        session = dataset.OutputSession(job["output"], plan, preview=job["preview"])
        session.state["license_category"] = license_category
        session.flush()
        renderer = None
        try:
            with tempfile.TemporaryDirectory(prefix=".gs_work_", dir=session.root) as scratch:
                for index, record in enumerate(plan["records"]):
                    if Path(job["stop_file"]).exists():
                        session.stop()
                        emit("cancelled", message="Stopped. Resume with the same scene and settings.")
                        return
                    skipped = session.done(record)
                    emit("status", message=f"{record['camera']} | Frame {record['houdini_frame']} | {index + 1}/{len(plan['records'])}")
                    if not skipped:
                        if renderer is None:
                            renderer = render.KarmaRenderer(plan)
                        session.commit(record, renderer.render(record, scratch))
                    emit("progress", completed=index + 1, total=len(plan["records"]), skipped=skipped)
            session.finish()
            emit("complete", output=str(session.root), preview=job["preview"])
        except Exception as exc:
            session.stop(exc)
            raise
        finally:
            if renderer:
                renderer.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    try:
        run(json.loads(Path(args.job).read_text(encoding="utf-8")))
        return 0
    except Exception as exc:
        traceback.print_exc()
        emit("error", message=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
