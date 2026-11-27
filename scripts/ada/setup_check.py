"""Check one SWE-bench instance's environment without the model.

Clones at the base commit and installs exactly as ``harnessspec.swebench`` does,
then runs the instance's fail_to_pass tests once with SWE-bench's test patch, the
same way the runner's hook does. At the base commit they should be collected and
fail. "not found" or "no tests ran" means the ids do not resolve or the
environment cannot run them; passing means the tests cannot tell a fix apart.

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

from harnessspec.swebench import SetupError, prepare_workspace, run_with_test_patch  # noqa: E402


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
        outcome = run_with_test_patch(instance, python, workspace, 900)
        text = outcome.output or ""
        # A collection error at the base commit is a failure, as in SWE-bench (pylint imports what the fix adds).
        broken = any(marker in text for marker in ("not found", "no tests ran", "did not apply"))
        report.update(
            tests_passed=outcome.passed,
            tests_ok=(not outcome.passed) and not broken and ("failed" in text or "error" in text),
            tests_tail=text.strip().splitlines()[-6:],
            tests_s=round(time.monotonic() - t0, 1),
        )
    (out_dir / f"{instance_id}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "error"}), flush=True)
    if report.get("error"):
        print(report["error"][-1500:], flush=True)
    return 0 if report.get("tests_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
