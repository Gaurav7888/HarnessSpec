"""SWE-QA manifest parsing and read-only source snapshot preparation."""

from contextlib import contextmanager
import gzip
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
from tempfile import NamedTemporaryFile, TemporaryDirectory
from urllib.request import urlopen

from harnessspec.parent import CapabilityCard, ToolGrant

REPO = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*")
COMMIT = re.compile(r"[a-f0-9]{40}")
TEXT_EXTENSIONS = {".py", ".pyi", ".rst", ".md", ".txt", ".toml", ".cfg", ".ini",
                   ".yaml", ".yml", ".json", ".html", ".css", ".js", ".in"}


def source_path(path: PurePosixPath) -> bool:
    return (
        bool(path.parts)
        and not path.is_absolute()
        and not any(part.startswith(".") for part in path.parts)
        and "\\" not in str(path)
        and (path.suffix in TEXT_EXTENSIONS or path.name in {"LICENSE", "Makefile"})
    )


def parse_manifest(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("instances"), list):
        raise ValueError("SWE-QA manifest must contain an instances array")
    seen = set()
    for instance in payload["instances"]:
        if not isinstance(instance, dict):
            raise ValueError("SWE-QA instance must be an object")
        for key in ("question_id", "repo", "revision", "question", "reference_answer"):
            if not isinstance(instance.get(key), str) or not instance[key].strip():
                raise ValueError(f"SWE-QA instance requires a non-empty {key}")
        if not REPO.fullmatch(instance["repo"]) or not COMMIT.fullmatch(instance["revision"]):
            raise ValueError("SWE-QA instance requires owner/repo and a full commit SHA")
        task_id = instance["question_id"]
        if task_id in seen:
            raise ValueError(f"duplicate question_id {task_id}")
        seen.add(task_id)
        files = instance.get("gold_files")
        if not isinstance(files, list) or not files or any(
            not isinstance(file, str) or not source_path(PurePosixPath(file))
            or file != PurePosixPath(file).as_posix() for file in files
        ) or len(set(files)) != len(files):
            raise ValueError(f"{task_id}: invalid gold_files")
        evidence = instance.get("gold_evidence", [])
        if not isinstance(evidence, list):
            raise ValueError(f"{task_id}: invalid gold_evidence")
        for entry in evidence:
            if (not isinstance(entry, dict) or entry.get("file") not in files
                    or type(entry.get("start")) is not int or type(entry.get("end")) is not int
                    or not 1 <= entry["start"] <= entry["end"]):
                raise ValueError(f"{task_id}: invalid gold_evidence entry")
    return payload["instances"]


def load_manifest(path: Path) -> list[dict]:
    return parse_manifest(json.loads(path.read_text(encoding="utf-8")))


def read_only_card() -> CapabilityCard:
    """The workspace contains only the authorized repository source slice."""
    return CapabilityCard(
        tools={name: ToolGrant("read", (".",)) for name in ("read_file", "list_dir")},
        context_paths=(".",), max_steps=12, max_tokens=8000, max_seconds=900,
        allowed_tiers=("7-14B",),
    )


def download_archive(repo: str, revision: str, cache: Path) -> Path:
    if not REPO.fullmatch(repo) or not COMMIT.fullmatch(revision):
        raise ValueError("invalid repository or revision")
    path = cache / (revision + ".tar.gz")
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        url = f"https://codeload.github.com/{repo}/tar.gz/{revision}"
        with NamedTemporaryFile(dir=cache, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with temporary.open("wb") as handle, urlopen(url, timeout=120) as response:
                shutil.copyfileobj(response, handle)
            with gzip.open(temporary) as stream:
                while stream.read(1024 * 1024):
                    pass  # Validate the gzip footer before publishing the archive.
            with tarfile.open(temporary) as archive:
                archive.next()
                if archive.pax_headers.get("comment") != revision:
                    raise ValueError(f"{repo}: archive commit does not match {revision}")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return path


@contextmanager
def source_snapshot(archive_path: Path, revision: str):
    """Materialize regular, non-hidden source files, without symlinks or VCS metadata."""
    with TemporaryDirectory(prefix="harnessspec-sweqa-") as directory:
        root = Path(directory)
        with tarfile.open(archive_path) as archive:
            first = archive.next()
            if first is None or archive.pax_headers.get("comment") != revision:
                raise ValueError(f"archive commit does not match {revision}")
            prefix = PurePosixPath(first.name)
            if not first.isdir() or len(prefix.parts) != 1 or prefix.is_absolute():
                raise ValueError("unexpected archive root")
            for item in archive:
                path = PurePosixPath(item.name)
                if not item.isfile() or not path.is_relative_to(prefix):
                    continue
                relative = path.relative_to(prefix)
                if not source_path(relative):
                    continue
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(item) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
        yield root


def verify_evidence(instance: dict, workspace: Path) -> None:
    """Verify every released citation path and extracted line range."""
    for file in instance["gold_files"]:
        if not (workspace / file).is_file():
            raise ValueError(f"{instance['question_id']}: missing evidence path {file}")
    for entry in instance.get("gold_evidence", []):
        line_count = len((workspace / entry["file"]).read_bytes().splitlines())
        if entry["end"] > line_count:
            raise ValueError(f"{instance['question_id']}: evidence line exceeds {entry['file']}")
