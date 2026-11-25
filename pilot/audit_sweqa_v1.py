"""Replay the frozen seed-1 action classifications and verify the published token ledger."""

from collections import Counter
import hashlib
import json
from pathlib import Path

from harnessspec.llm import load_pin
from harnessspec.results import read_results, result_key
from harnessspec.subagent import action_from_reply
from harnessspec.sweqa import load_manifest
from pilot.run_sweqa import fingerprint

PILOT = Path(__file__).resolve().parent


def main() -> None:
    pin = load_pin()
    instances = {r["question_id"]: r for r in load_manifest(PILOT / "sweqa_instances.json")}
    expected = {("sweqa", task, designer, 1) for task in instances for designer in "AD"}
    actual = set()
    costs = Counter()
    scored = []
    rejected = []
    for path in sorted((PILOT / "traces/sweqa").glob("*.json")):
        trace = json.loads(path.read_text())
        key = result_key(trace)
        row = trace["row"]
        assert key == result_key(row) and key not in actual
        actual.add(key)
        assert trace["protocol"] == "sweqa-ad-v1"
        assert trace["instance_hash"] == fingerprint(instances[key[1]])
        assert trace["pin_hash"] == fingerprint(pin)
        assert (row["model"], row["model_digest"]) == (pin["name"], pin["digest"])
        energy = json.loads((PILOT / "traces/sweqa-energy" / path.name).read_text())
        assert result_key(energy) == key
        assert all(energy["energy"][device]["joules"] is None for device in ("cpu", "gpu"))
        if row["resolved"] is not None:
            scored.append(row)
        totals = Counter()
        log = trace["design"]["log"]
        stage_indices = Counter()
        for number, call in enumerate(trace["transcript"], start=1):
            assert call["seed"] == key[3] and call["json_mode"]
            assert call["server_tokens"] == call["prompt_tokens"] + call["output_tokens"]
            stage = call["stage"]
            index = stage_indices[stage]
            stage_indices[stage] += 1
            totals[stage] += call["server_tokens"]
            if stage == "design":
                assert log[index]["reply"] == call["reply"]
                costs[log[index]["kind"]] += call["server_tokens"]
                continue
            action = action_from_reply(call["reply"], call["output_tokens"], 0)
            code = call["observation"]["code"]
            if code == "action.unknown":
                raw = json.loads(call["reply"])
                assert action.kind == "unparsed" and raw["kind"] in ("read", "read_file")
                missing = [name for name in ("tool", "permission", "path") if name not in raw]
                checksum = hashlib.sha256(call["reply"].encode()).hexdigest()
                rejected.append((key[1], index + 1, number, raw["kind"], ",".join(missing) or "-",
                                 call["prompt_tokens"], checksum, path.name))
            if code == "budget.exhausted":
                assert action.kind == "return" and call["charged_tokens"] == 0
                costs["intercepted_return"] += call["server_tokens"]
        for stage in ("design", "subagent"):
            assert totals[stage] == row[stage + "_tokens"]
        assert totals["design"] == trace["design"]["design_tokens"]
        assert len(log) == stage_indices["design"]
        if not trace["design"]["valid"]:
            assert trace["runtime_trace"] is None and stage_indices["subagent"] == 0
    assert actual == expected and len(rejected) == 48
    assert sorted(scored, key=result_key) == read_results([PILOT / "sweqa_results.json"])
    assert costs == {"design": 15682, "repair": 16157, "intercepted_return": 2813}
    print("task_id\tsubagent_call\ttranscript_call\tkind\tmissing_arguments\tprompt_tokens\treply_sha256\ttrace_file")
    for entry in sorted(rejected):
        print(*entry, sep="\t")


if __name__ == "__main__":
    main()
