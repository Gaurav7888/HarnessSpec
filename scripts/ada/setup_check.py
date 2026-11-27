"""Check one SWE-bench instance's environment without the model.

Clones at the base commit and installs exactly as ``harnessspec.swebench`` does,
then runs the instance's fail_to_pass tests once. At the base commit they should
be collected and fail (pytest exit 1). Exit 4 or 5 means the node ids do not
resolve or the environment cannot run them.

    python scripts/ada/setup_check.py INSTANCE_ID WORKDIR OUT_DIR
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from harnessspec.swebench import SetupError, prepare_workspace  # noqa: E402


def main() -> int:
    instance_id, workdir, out_dir = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    out_dir.mkdir(parents=True, exist_ok=True)
    document = json.loads((ROOT / "pilot" / "swebench_instances.json").read_text(encoding="utf-8"))
    instance = next(row for row in document["instances"] if row["instance_id"] == instance_id)
    report = {"instance_id": instance_id, "python": instance["python"]}
    started = time.monotonic()
    try:
        workspace, python = prepare_workspace(instance, workdir)
        report["setup"] = "ok"
    except (SetupError, subprocess.CalledProcessError, OSError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        report.update(setup="failed", error=str(detail)[-3000:])
        workspace = None
    report["setup_s"] = round(time.monotonic() - started, 1)
    if workspace is not None:
        t0 = time.monotonic()
        completed = subprocess.run(
            [python, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider", *instance["fail_to_pass"]],
            cwd=workspace, capture_output=True, text=True, timeout=900, check=False,
        )
        tail = (completed.stdout + completed.stderr).strip().splitlines()[-6:]
        report.update(
            tests_exit=completed.returncode,
            tests_ok=completed.returncode == 1,  # collected and failing at the base commit
            tests_tail=tail,
            tests_s=round(time.monotonic() - t0, 1),
        )
    (out_dir / f"{instance_id}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "error"}), flush=True)
    if report.get("error"):
        print(report["error"][-1500:], flush=True)
    return 0 if report.get("tests_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
