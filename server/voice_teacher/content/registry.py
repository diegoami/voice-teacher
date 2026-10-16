"""Persistent, read-only local-source registry with immutable compiled versions."""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

from schemas.validate import canonical_json, content_hash, validate_curriculum
from ..practice.models import Lesson
from ..storage.sqlite import _id
from .adapters import LegacyAdapter


class SourceError(ValueError):
    pass


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _relative(value):
    if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
        raise SourceError("expected a relative source path")
    p = PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts:
        raise SourceError("source path escapes configured root")
    return p


def _contained(root, relative):
    relative = _relative(relative)
    logical = root.joinpath(*relative.parts)
    p = root
    for part in relative.parts:
        p = p / part
        if p.is_symlink():
            raise SourceError("source input symlinks are not supported")
    actual = logical.resolve()
    if not actual.is_relative_to(root):
        raise SourceError("source path escapes configured root")
    return actual


def _git(root, *args, missing_ok=False):
    # Fixed plumbing only. status/diff may execute fsmonitor or clean filters.
    env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}
    try:
        p = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                            "--literal-pathspecs", "-C", str(root), *args], env=env,
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        raise SourceError("Git metadata inspection failed or timed out") from None
    if p.returncode:
        if missing_ok: return None
        raise SourceError("cannot read configured Git metadata")
    return p.stdout


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    name: str
    checkout: str
    subdirectory: str = "."
    adapter: str = "canonical_json"
    manifest: str = "voice-teacher.json"
    mapping: dict | None = None
    allow_dirty: bool = False


@dataclass(frozen=True)
class SourceSnapshot:
    version_id: str
    _payload_json: str

    @property
    def curriculum(self):
        return json.loads(self._payload_json)["curriculum"]

    @property
    def provenance(self):
        return json.loads(self._payload_json)["provenance"]

    def lesson(self, course_id, lesson_id):
        for course in self.curriculum["courses"]:
            if course["course_id"] == course_id:
                for lesson in course["lessons"]:
                    if lesson["lesson_id"] == lesson_id: return lesson
        raise SourceError("unknown course/lesson in this source version")

    def source_ref(self, course_id, lesson_id):
        self.lesson(course_id, lesson_id)
        p = self.provenance
        return {"source_id": self.curriculum["source_id"], "course_id": course_id, "lesson_id": lesson_id,
                "revision": {"commit": p["commit"], "content_sha256": content_hash(self.curriculum), "dirty": p["dirty"]}}

    def private_session_inputs(self, course_id, lesson_id):
        """Trusted server/operator use only; never serialize as a public catalogue."""
        self.lesson(course_id, lesson_id)
        for row in json.loads(self._payload_json)["session_inputs"]:
            if (row["course_id"], row["lesson_id"]) == (course_id, lesson_id): return row["inputs"]
        raise SourceError("content needs its mode-specific planner before session creation")

    def prepared_lesson(self, course_id, lesson_id):
        # Source selection alone does not authorize applying historical personal
        # context. The safe plan omits private introduction/settings by default.
        data = self.private_session_inputs(course_id, lesson_id)["lesson"]
        data["introduction"] = ""
        for step in data["steps"]: step["setting"] = ""
        return Lesson.from_dict(data)


def _canonical(root, spec):
    path = _contained(root, spec["manifest"])
    try:
        with path.open("rb") as f: data = f.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024: raise SourceError("catalogue exceeds byte limit")
        catalogue = json.loads(data)
    except (OSError, ValueError):
        raise SourceError("cannot read a valid canonical catalogue") from None
    validate_curriculum(catalogue)
    if catalogue["source_id"] != spec["source_id"]:
        raise SourceError("catalogue namespace does not match registered source")
    private = []
    for course in catalogue["courses"]:
        items = {i["item_id"]: i for i in course["items"]}
        for lesson in course["lessons"]:
            # Do not invent missing phases or infer target sentences. T13/T14
            # supply planners for independent modes and partial lesson shapes.
            if not all(lesson[k] for k in ("repetition_item_ids", "guided_steps", "recall_goals")):
                continue
            native = {"source_id": catalogue["source_id"], "course_id": course["course_id"],
                "lesson_id": lesson["lesson_id"], "title": lesson["title"], "introduction": "",
                "language": course["language"], "instruction_language": course["instruction_language"],
                "opening": [items[i]["text"]["speech"] for i in lesson["repetition_item_ids"]],
                "opening_item_ids": lesson["repetition_item_ids"], "steps": [], "recall": []}
            for number, step in enumerate(lesson["guided_steps"], 1):
                native["steps"].append({"number": number, "step_id": step["step_id"], "teacher_line": step["teacher"]["speech"],
                    "expected": step["goal"], "targets": [items[i]["text"]["speech"] for i in step["target_item_ids"]], "target_item_ids": step["target_item_ids"]})
            for number, goal in enumerate(lesson["recall_goals"], 1):
                native["recall"].append({"number": number, "goal_id": goal["goal_id"], "prompt": goal["prompt"]["speech"],
                    "targets": [items[i]["text"]["speech"] for i in goal["target_item_ids"]], "target_item_ids": goal["target_item_ids"]})
            private.append({"course_id": course["course_id"], "lesson_id": lesson["lesson_id"],
                            "inputs": {"lesson": Lesson.from_dict(native).to_dict()}})
    return catalogue, private, {str(_relative(spec["manifest"])): _hash(data)}


class SourceRegistry:
    def __init__(self, store):
        self.store = store

    def register(self, spec: SourceSpec):
        value = asdict(spec)
        _id(value["source_id"])
        if not isinstance(value["name"], str) or not value["name"].strip(): raise SourceError("source name required")
        if value["adapter"] not in {"legacy", "canonical_json"} or type(value["allow_dirty"]) is not bool:
            raise SourceError("unknown adapter or invalid dirty-snapshot policy")
        checkout = Path(value["checkout"]).expanduser().resolve()
        if not checkout.is_dir(): raise SourceError("configured checkout does not exist")
        if self.store.path.parent.is_relative_to(checkout):
            raise SourceError("runtime database must be outside the content checkout")
        root = _contained(checkout, value["subdirectory"])
        if not root.is_dir(): raise SourceError("configured content subdirectory does not exist")
        value["checkout"] = str(checkout)
        if value["adapter"] == "legacy":
            LegacyAdapter(value["mapping"])
            if value["mapping"]["source_id"] != value["source_id"]: raise SourceError("legacy namespace does not match source")
        else:
            _relative(value["manifest"])
            if value["mapping"] is not None: raise SourceError("canonical source must not have a legacy mapping")
        with self.store._transaction() as c:
            c.execute("INSERT INTO sources(source_id,config_json) VALUES (?,?) ON CONFLICT(source_id) DO UPDATE SET config_json=excluded.config_json",
                      (value["source_id"], canonical_json(value)))

    def _config(self, source_id):
        with self.store._connection() as c:
            row = c.execute("SELECT config_json FROM sources WHERE source_id=?", (_id(source_id),)).fetchone()
            if row is None: raise SourceError("source is not registered")
            return row[0]

    def refresh(self, source_id):
        body = self._config(source_id)
        spec = json.loads(body)
        try:
            checkout = Path(spec["checkout"])
            root = _contained(checkout, spec["subdirectory"])
            raw_head = _git(checkout, "rev-parse", "--verify", "HEAD", missing_ok=True)
            top = _git(checkout, "rev-parse", "--show-toplevel", missing_ok=True)
            if top is not None and Path(top.decode().strip()).resolve() != checkout:
                raise SourceError("configure the Git checkout root and use subdirectory for content")
            if raw_head is not None and top is None:
                raise SourceError("a normal working checkout is required")
            commit = raw_head.decode().strip() if raw_head is not None else None
            if commit is not None and not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", commit): raise SourceError("invalid Git revision")
            if spec["adapter"] == "legacy":
                adapted = LegacyAdapter(spec["mapping"]).load(root, source_id=source_id)
                catalogue, hashes = adapted.curriculum, adapted.input_hashes
                private = [{"course_id": c, "lesson_id": l, "inputs": v} for (c, l), v in adapted.session_inputs.items()]
            else:
                catalogue, private, hashes = _canonical(root, spec)
            dirty = commit is None
            for relative, digest in hashes.items():
                path = _contained(root, relative)
                git_path = path.relative_to(checkout).as_posix()
                size = _git(checkout, "cat-file", "-s", f"{commit}:{git_path}", missing_ok=True) if commit else None
                blob = _git(checkout, "cat-file", "blob", f"{commit}:{git_path}", missing_ok=True) if size is not None and size.strip().isdigit() and int(size) <= 4 * 1024 * 1024 else None
                if blob is None or _hash(blob) != digest: dirty = True
            after = _git(checkout, "rev-parse", "--verify", "HEAD", missing_ok=True)
            if after != raw_head: raise SourceError("checkout revision changed during compilation; retry refresh")
            if dirty and not spec["allow_dirty"]:
                raise SourceError("content has uncommitted/untracked bytes; explicitly enable dirty snapshots or commit it")
            payload = {"curriculum": catalogue, "session_inputs": private,
                       "provenance": {"commit": commit, "dirty": dirty, "input_hashes": hashes,
                                      "adapter": spec["adapter"], "mapping_hash": _hash(canonical_json(spec["mapping"]).encode())}}
            encoded = canonical_json(payload)
            version_id = _hash(encoded.encode())
            with self.store._transaction() as c:
                if c.execute("SELECT config_json FROM sources WHERE source_id=?", (source_id,)).fetchone()[0] != body:
                    raise SourceError("source configuration changed during refresh; retry")
                for course in catalogue["courses"]:
                    for item in course["items"]:
                        key = (source_id, course["course_id"], item["item_id"], item["item_revision"])
                        digest = _hash(canonical_json(item).encode())
                        old = c.execute("SELECT definition_hash FROM source_items WHERE source_id=? AND course_id=? AND item_id=? AND item_revision=?", key).fetchone()
                        if old is not None and old[0] != digest:
                            raise SourceError("an item revision already names different content; review and increase its revision")
                        c.execute("INSERT OR IGNORE INTO source_items VALUES (?,?,?,?,?)", (*key, digest))
                c.execute("INSERT OR IGNORE INTO source_versions VALUES (?,?,?)", (version_id, source_id, encoded))
                c.execute("INSERT INTO source_active VALUES (?,?) ON CONFLICT(source_id) DO UPDATE SET version_id=excluded.version_id", (source_id, version_id))
                c.execute("UPDATE sources SET last_error=NULL WHERE source_id=?", (source_id,))
            return SourceSnapshot(version_id, encoded)
        except Exception as error:
            # Schema/domain errors expose field paths, not private record dumps.
            message = str(error) if isinstance(error, ValueError) else "source refresh failed; prior catalogue retained"
            with self.store._transaction() as c:
                c.execute("UPDATE sources SET last_error=? WHERE source_id=? AND config_json=?", (message, source_id, body))
            raise SourceError(message) from None

    def active(self, source_id):
        with self.store._connection() as c:
            row = c.execute("SELECT v.version_id, v.payload_json FROM source_active a JOIN source_versions v ON v.version_id=a.version_id WHERE a.source_id=?", (_id(source_id),)).fetchone()
            if row is None: raise SourceError("source has no validated active catalogue")
            return SourceSnapshot(row[0], row[1])

    def list_sources(self):
        with self.store._connection() as c:
            rows = c.execute("SELECT s.source_id, s.config_json, s.last_error, a.version_id FROM sources s LEFT JOIN source_active a USING(source_id) ORDER BY s.source_id").fetchall()
            return [{"source_id": r["source_id"], "name": json.loads(r["config_json"])["name"],
                     "version_id": r["version_id"], "error": r["last_error"]} for r in rows]
