"""Exercise real CUDA training, safe pause/resume, rendering, and dataset guards."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gs_workbench import core

OUT = core.ROOT / "workbench/test-results"
OUT.mkdir(parents=True, exist_ok=True)


def execute(action, run=None, pause=False):
    args = [str(core.PYTHON), str(core.ROOT / "workbench/worker.py"), action]
    if run: args += ["--run", str(run)]
    if action == "render": args += ["--mode", "orbit", "--fps", "30"]
    events = []
    with (OUT / f"{action}.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(args, cwd=core.REPO, env=core.environment(), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for line in process.stdout:
            log.write(line); log.flush()
            if "@WB@" in line:
                event = json.loads(line.split("@WB@", 1)[1]); events.append(event)
                print(json.dumps(event)[:400], flush=True)
                if pause and event["event"] == "progress" and event["stage"] == pause and event["iteration"] >= 10:
                    (run / "stop.request").write_text("stop", encoding="ascii")
        code = process.wait()
    assert code == 0, f"{action} failed with code {code}; see {OUT / (action + '.log')}"
    return events


def main():
    execute("check")
    dataset = core.validate_dataset(core.REPO / "data/dnerf/bouncingballs", stride=5)
    assert dataset["train_images"] > 0 and dataset["test_images"] > 0
    run = Path(tempfile.mkdtemp(prefix="cuda_", dir=str(OUT))) / "run with spaces"
    settings = dict(coarse=30, fine=40, checkpoint_every=20, stride=5, sh_degree=3,
                    temporal_grid=10, background="white", opacity_deformation=False)
    core.create_run(run, dataset, settings)
    core.load_run(run)
    events = execute("train", run, pause="coarse")
    assert any(e["event"] == "stopped" for e in events), "Training did not pause"
    assert (run / "latest.pt").is_file()
    stopped_at = core.read_json(run / "checkpoint.json")
    (run / "stop.request").unlink()
    events = execute("resume", run, pause="fine")
    assert any(e["event"] == "stopped" for e in events)
    fine_stop = core.read_json(run / "checkpoint.json")
    assert fine_stop["stage"] == "fine"
    (run / "stop.request").unlink()
    events = execute("resume", run)
    assert not any(e["event"] == "stage" and e["stage"] == "coarse" for e in events)
    assert any(e["event"] == "complete" for e in events)
    assert core.read_json(run / "status.json")["status"] == "complete"
    assert (run / "model/point_cloud/iteration_40/point_cloud.ply").is_file()
    events = execute("render", run)
    report = core.read_json(run / "latest_render.json")
    assert len(report["frames"]) == 160
    assert Path(report["video"]).stat().st_size > 1000
    assert all(Path(f["path"]).is_file() for f in report["frames"])
    core.write_json(OUT / "integration.json", dict(status="passed", run=str(run), paused_at=stopped_at,
                    fine_paused_at=fine_stop, resumed_to=40, rendered_frames=160, video=report["video"]))
    print("INTEGRATION PASSED", flush=True)


if __name__ == "__main__":
    main()
