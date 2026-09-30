"""Detect NVIDIA hardware and driver without requiring the training environment."""
import csv
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

try:
    program = shutil.which("nvidia-smi.exe") or str(Path(os.environ.get("WINDIR","C:/Windows"))/"System32/nvidia-smi.exe")
    result = subprocess.run([program,"--query-gpu=name,memory.total,driver_version","--format=csv,noheader,nounits"],
        capture_output=True,text=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode: raise RuntimeError(result.stderr.strip() or "The NVIDIA driver query failed.")
    rows = list(csv.reader(io.StringIO(result.stdout)))
    if not rows: raise RuntimeError("No NVIDIA GPU was detected.")
    name,memory,driver = [s.strip() for s in rows[0]]
    print("@WB@"+json.dumps(dict(event="gpu",gpu=name,vram_gb=round(float(memory)/1024,1),driver=driver,devices=len(rows))),flush=True)
except Exception as exc:
    print("@WB@"+json.dumps(dict(event="error",message="GPU check: "+str(exc))),flush=True)
    sys.exit(1)
