"""Merge per-instance SWE-bench row files into pilot/swebench_results.json.

    python scripts/ada/merge_swebench.py [v1|v2]
Rejects duplicate (benchmark, task, designer, seed) identities and invalid rows.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from harnessspec.results import read_results, write_json  # noqa: E402

variant = sys.argv[1] if len(sys.argv) > 1 else "v1"
folder, target = {"v1": ("swebench", "swebench_results.json"),
                  "v2": ("swebench_v2", "swebench_results_v2.json")}[variant]
parts = sorted((ROOT / "pilot" / folder).glob("*.json"))
rows = read_results(parts)
write_json(ROOT / "pilot" / target, rows)
print(f"{len(rows)} rows from {len(parts)} instance files")
