"""List the test node ids pytest collects for an instance (after its test patch).

    python scripts/ada/collect_ids.py INSTANCE_ID WORKDIR
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from harnessspec import swebench  # noqa: E402

instance_id, workdir = sys.argv[1], Path(sys.argv[2])
doc = json.loads((ROOT / "pilot" / "swebench_instances.json").read_text(encoding="utf-8"))
inst = next(r for r in doc["instances"] if r["instance_id"] == instance_id)
workspace, python = swebench.prepare_workspace(inst, workdir)
files = sorted({t.split("::")[0] for t in inst["fail_to_pass"]})


def collect(_python, ws, _tests, timeout):
    done = subprocess.run([python, "-m", "pytest", "--collect-only", "-q", *files], cwd=ws,
                          capture_output=True, text=True, timeout=timeout, check=False)
    print(done.stdout[-6000:], done.stderr[-3000:], sep="\n", flush=True)
    return swebench.HookOutcome("test", "pytest", done.returncode == 0, done.stdout)


swebench._pytest_nodes = collect
swebench.run_with_test_patch(inst, python, workspace, 600)
