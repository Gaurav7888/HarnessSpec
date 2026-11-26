"""Prepare the private, blinded packet from completed v2 traces without inference."""
import argparse
import json
from pathlib import Path
import shutil

from harnessspec.llm import load_pin
from harnessspec.results import result_key, write_json
from harnessspec.sweqa import load_manifest
from pilot.run_sweqa import EXPERIMENT, RUBRIC, grading_packet, load_artifact


def prepare(directory):
    manifest = {i["question_id"]: i for i in load_manifest(Path("pilot/sweqa_instances.json"))}
    pin = load_pin()
    packets = []
    for path in sorted((directory / "traces").glob("*.json")):
        key = result_key(json.loads(path.read_text()))
        record = load_artifact(path, key, manifest[key[1]], pin)
        write_json(directory / "diagnostics" / path.name, {
            **dict(zip(("benchmark", "task_id", "designer", "seed"), key)),
            **record["diagnostics"], "evidence": record["evidence"],
        })
        if record["grading_id"]:
            packets.append(grading_packet(record, manifest[key[1]]))
    packets.sort(key=lambda p: p["grading_id"])
    if packets != json.loads((directory / "grading_packet.json").read_text()):
        raise ValueError("runner packet does not cover all accepted nonempty answers exactly")
    reviewer = directory / "reviewer"
    write_json(reviewer / "packet.json", packets)
    write_json(reviewer / "grade_template.json", {
        p["grading_id"]: {**dict.fromkeys(RUBRIC), "rationale": ""} for p in packets})
    shutil.copyfile("pilot/review/sweqa-ad-seed1-v1/REVIEW.md", reviewer / "REVIEW.md")
    (reviewer / "provenance_template.txt").write_text(
        "Reviewer name or pseudonym:\nGrading date:\n"
        "Rubric: five dimensions, 0–10 each, total 2 × sum, pass at 70.\n"
        "Independence and prior exposure to candidates, public results or assignments:\n"
        "Adjudication and date, if applicable:\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, default=EXPERIMENT)
    prepare(parser.parse_args().experiment)
