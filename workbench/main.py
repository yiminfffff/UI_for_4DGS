import sys
import traceback
from pathlib import Path


def launch():
    log_path = Path(__file__).resolve().parents[1] / ".cache/workbench/startup.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", buffering=1) as log:
        if sys.stdout is None:
            sys.stdout = log
        if sys.stderr is None:
            sys.stderr = log
        try:
            from gs_workbench.app import main
            return main()
        except Exception:
            details = traceback.format_exc()
            log.write(details)
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    None, f"The workbench could not start.\n\n{details}\nLog: {log_path}",
                    "4DGS Workbench - Startup Error", 0x10)
            except Exception:
                pass
            return 1

if __name__ == "__main__":
    raise SystemExit(launch())
