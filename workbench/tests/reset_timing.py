"""Exercise reset and preview order on an isolated short CUDA training run."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gs_workbench import core
import worker
sys.path.insert(0, str(core.REPO))

out = core.ROOT / "workbench/test-results"
run = Path(tempfile.mkdtemp(prefix="reset_", dir=out))
data = core.validate_dataset(core.REPO / "data/dnerf/bouncingballs", stride=5)
config = core.create_run(run, data, dict(coarse=4, fine=4, checkpoint_every=2, stride=5,
    sh_degree=3, temporal_grid=10, background="white", opacity_deformation=False))
original = worker.configure
def configure(*args):
    result = original(*args)
    result[2].opacity_reset_interval = 2
    result[2].densify_until_iter = 20
    return result
worker.configure = configure
with (out / "reset-timing.log").open("w", encoding="utf-8") as stream, contextlib.redirect_stdout(stream):
    worker.train(run, core.load_run(run), False)
events = [json.loads(line.split("@WB@", 1)[1]) for line in (out / "reset-timing.log").read_text(encoding="utf-8").splitlines() if "@WB@" in line]
for stage in ("coarse", "fine"):
    preview = next(i for i,e in enumerate(events) if e["event"] == "preview" and e["stage"] == stage and e["iteration"] == 4)
    reset = next(i for i,e in enumerate(events) if e["event"] == "opacity_reset" and e["stage"] == stage and e["iteration"] == 4)
    assert preview < reset
assert (run / "validation.jsonl").is_file()
core.write_json(out / "reset-timing.json", dict(status="passed", run=str(run), preview_before_reset=True))
print("RESET TIMING PASSED")
