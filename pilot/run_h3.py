"""Write pilot/h3_results_v2.json and pilot/h3_transcripts_v2.json with the pinned model.

v1 (pilot/h3_results.json) was generated before pytest joined the allowlist and
before the compiler reduced commands with arguments. It is frozen in the SWE-QA
snapshot manifest and kept unchanged. v2 is the H3 result for the design() that
the benchmark runs use.

Needs Ollama running with the model in pilot/model.json pulled. The client
refuses to start if the local digest differs from the pin.

    PYTHONPATH=src python3 pilot/run_h3.py
"""

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harnessspec.h3 import SEEDS, corpus_rows, fixture_rows, summarize
from harnessspec.llm import OllamaClient, load_pin
from harnessspec.parent import ALLOWED_COMMANDS


def main() -> None:
    pin = load_pin()
    client = OllamaClient(pin)
    rows, transcripts = fixture_rows(client)
    more_rows, more_transcripts = corpus_rows(client, seed=1)
    rows += more_rows
    transcripts += more_transcripts
    payload = {
        "hypothesis": "H3: first-pass validity rises from C to D",
        "version": "v2",
        "allowed_commands": sorted(ALLOWED_COMMANDS),
        "compiler_reduces_command_arguments": True,
        "date": date.today().isoformat(),
        "model": pin["name"],
        "model_digest": pin["digest"],
        "options": pin["options"],
        "fixture_seeds": list(SEEDS),
        "corpus_seed": 1,
        "summary": summarize(rows),
        "rows": rows,
    }
    out = ROOT / "pilot" / "h3_results_v2.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (ROOT / "pilot" / "h3_transcripts_v2.json").write_text(
        json.dumps(transcripts, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
