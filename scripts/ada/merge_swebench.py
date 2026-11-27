"""Merge per-instance SWE-bench row files into pilot/swebench_results.json.

    python scripts/ada/merge_swebench.py
Rejects duplicate (benchmark, task, designer, seed) identities and invalid rows.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from harnessspec.results import read_results, write_json  # noqa: E402

parts = sorted((ROOT / "pilot" / "swebench").glob("*.json"))
rows = read_results(parts)
write_json(ROOT / "pilot" / "swebench_results.json", rows)
print(f"{len(rows)} rows from {len(parts)} instance files")
