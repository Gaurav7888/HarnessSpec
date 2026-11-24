"""Reproduce the curated Peng et al. SWE-QA selection from its pinned Git release."""

import argparse
import json
import re
import subprocess
from pathlib import Path

from harnessspec.results import write_json
from harnessspec.sweqa import download_archive, parse_manifest, source_snapshot, verify_evidence

SOURCE = "https://github.com/peng-weihan/SWE-QA-Bench"
RELEASE = "c13deac7a0d99b0ca2e593e004c4739475785b08"
DATASET = "swe-qa/SWE-QA-Benchmark"
SELECTION = (
    ("pallets/flask", "85c5d93cbd049c4bd0679c36fd1ddcae8c37b642", (1, 17, 35, 43)),
    ("psf/requests", "46e939b5525d9c72b677340985582b04b128478a", (30, 48)),
    ("pytest-dev/pytest", "5989efe3efec31a9d14f550d89903b6311dfc828", (18, 24, 34, 44)),
)
PATH = r"((?:\./)?[\w.-]+(?:/[\w.-]+)+\.(?:py|rst|md|txt))"
LINES = r"(\d+)(?:\s*[-–]\s*(\d+))?"
REFERENCES = re.compile(
    r"`" + PATH + r"(?:\:" + LINES + r"`|`(?:\s*(?:\(lines?\s+|at lines?\s+|lines?\s+)"
    + LINES + r")?)", re.IGNORECASE,
)


def source_file(checkout: Path, name: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(checkout), "show", f"{RELEASE}:{name}"], text=True, encoding="utf-8",
    )


def evidence(answer: str) -> tuple[list[str], list[dict]]:
    files = set()
    ranges = set()
    for file, inline_start, inline_end, start, end in REFERENCES.findall(answer):
        file = file.removeprefix("./")
        files.add(file)
        first = inline_start or start
        if first:
            ranges.add((file, int(first), int(inline_end or end or first)))
    return sorted(files), [dict(file=file, start=start, end=end) for file, start, end in sorted(ranges)]


def select(checkout: Path, cache: Path) -> dict:
    published_revisions = dict(line.split() for line in source_file(checkout, "repo_commit.txt").splitlines()
                               if line.strip())
    instances = []
    for repo, revision, indexes in SELECTION:
        if not revision.startswith(published_revisions[f"https://github.com/{repo}"]):
            raise ValueError(f"published revision mismatch for {repo}")
        short_name = repo.split("/")[-1]
        source_path = f"Benchmark/{short_name}.jsonl"
        lines = source_file(checkout, source_path).splitlines()
        archive = download_archive(repo, revision, cache)
        with source_snapshot(archive, revision) as workspace:
            for index in indexes:
                row = json.loads(lines[index - 1])
                files, ranges = evidence(row["answer"])
                instance = {
                    "question_id": f"{short_name}:{index}", "repo": repo, "revision": revision,
                    "question": row["question"], "reference_answer": row["answer"],
                    "gold_files": files, "gold_evidence": ranges,
                    "question_type": row["question"].split()[0].lower(),
                    "source_line": index,
                    "source": f"{SOURCE}/blob/{RELEASE}/{source_path}#L{index}",
                }
                verify_evidence(instance, workspace)
                instances.append(instance)

    manifest = {
        "dataset": DATASET, "release": RELEASE,
        "source": f"{SOURCE}/tree/{RELEASE}/Benchmark",
        "revision_source": f"{SOURCE}/blob/{RELEASE}/repo_commit.txt",
        "id_policy": "Published JSONL has no ID field. IDs are project:one-based-source-line.",
        "instances": instances,
    }
    parse_manifest(manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_checkout", type=Path)
    parser.add_argument("--archive-cache", type=Path, default=Path("pilot/tmp/sweqa-archives"))
    parser.add_argument("--output", type=Path, default=Path("pilot/sweqa_instances.json"))
    args = parser.parse_args()
    manifest = select(args.source_checkout, args.archive_cache)
    write_json(args.output, manifest)
    print(f"Verified {len(manifest['instances'])} released questions")


if __name__ == "__main__":
    main()
