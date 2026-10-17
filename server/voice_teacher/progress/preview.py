"""Conservative historical reconciliation. This module never opens a Store.

The report is a proposal, not a progress-event stream or an apply authorization.
Only explicit operator mappings create observations; Markdown is evidence data.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat


class PreviewError(ValueError):
    """Safe category only: do not echo private source data in CLI errors."""


MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 10000
ASSISTANCE = {None, "modelled", "repeated", "cued", "independent", "corrected_repeated", "needs_turn"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PreviewError("duplicate manifest field")
        result[key] = value
    return result


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _text(value, limit=256):
    return isinstance(value, str) and 0 < len(value) <= limit and value.strip() == value and not any(ord(c) < 32 for c in value)


def _shape(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise PreviewError("invalid manifest shape")


def _source(value):
    _shape(value, ["source_id", "course_id", "lesson_id"])
    if not all(_text(v) for v in value.values()):
        raise PreviewError("invalid legacy source identity")


def _path(value):
    if not _text(value, 1024) or "\\" in value:
        raise PreviewError("invalid relative input path")
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in {"", ".", ".."} for x in value.split("/")):
        raise PreviewError("invalid relative input path")
    return p


def _read(root, relative, limit=MAX_FILE_BYTES):
    parts = _path(relative).parts
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise PreviewError("input must be a regular file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise PreviewError("input byte limit exceeded")
    return raw


def _cells(line):
    return [s.strip() for s in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def _separator(line):
    return bool(re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*", line))


def _blocks(text):
    """Retain rows and opaque prose/code blocks; never infer learner turns."""
    lines = text.splitlines(keepends=True)
    section, columns = [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            depth = len(heading[1])
            section = section[:depth - 1] + [heading[2]]
            columns = []
            i += 1
            continue
        if not line.strip():
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and _separator(lines[i + 1]):
            columns = _cells(line)
            i += 2
            continue
        start = i
        row = bool(columns and line.lstrip().startswith("|"))
        fenced = re.match(r"^\s*(`{3,}|~{3,})", line)
        i += 1
        if fenced:
            while i < len(lines):
                closing = re.match(r"^\s*" + re.escape(fenced[1][0]) + r"{" + str(len(fenced[1])) + r",}\s*$", lines[i])
                i += 1
                if closing:
                    break
        elif not row:
            while i < len(lines) and lines[i].strip() and not re.match(r"^#{1,6}\s", lines[i]):
                if lines[i].lstrip().startswith("|"):
                    break
                i += 1
        raw = "".join(lines[start:i])
        values = _cells(line) if row else []
        yield dict(section=list(section), line_start=start + 1, line_end=i, raw=raw,
                   columns=list(columns) if row else [], values=values,
                   parse_issue="table column count mismatch" if row and len(values) != len(columns) else None)


def _manifest(manifest):
    _shape(manifest, ["format_version", "namespace", "learner_id", "inputs", "mappings"])
    if type(manifest["format_version"]) is not int or manifest["format_version"] != 1:
        raise PreviewError("unsupported manifest version")
    if not all(_text(manifest[k]) for k in ("namespace", "learner_id")):
        raise PreviewError("invalid import identity")
    inputs, mappings = manifest["inputs"], manifest["mappings"]
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 128 or not isinstance(mappings, list) or len(mappings) > MAX_RECORDS:
        raise PreviewError("invalid manifest limits")
    seen = set()
    for source in inputs:
        _shape(source, ["path", "kind", "sha256"])
        _path(source["path"])
        if source["path"] in seen or not _text(source["kind"]) or source["kind"] not in {"tracker", "queue", "session"} or not isinstance(source["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", source["sha256"]):
            raise PreviewError("invalid or duplicate input")
        seen.add(source["path"])
    seen = set()
    for m in mappings:
        _shape(m, ["record_id", "observation_key", "original_source", "practice_source", "assistance", "correction", "repetition_of"])
        if not _text(m["record_id"]) or m["record_id"] in seen or not _text(m["observation_key"]):
            raise PreviewError("invalid or duplicate record mapping")
        seen.add(m["record_id"])
        _source(m["original_source"])
        _source(m["practice_source"])
        if not isinstance(m["assistance"], (str, type(None))) or m["assistance"] not in ASSISTANCE:
            raise PreviewError("unsupported assistance")
        if m["repetition_of"] is not None and not _text(m["repetition_of"]):
            raise PreviewError("invalid repetition reference")
        if m["correction"] is not None:
            _shape(m["correction"], ["attempt", "preferred", "reason"])
            if not all(_text(v, 8000) for v in m["correction"].values()):
                raise PreviewError("invalid correction")


def plan_preview(root, manifest):
    """Return a deterministic private proposal; all reads are bounded/read-only."""
    _manifest(manifest)
    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise PreviewError("input root must be a directory")
    records, inputs, total = [], [], 0
    for source in sorted(manifest["inputs"], key=lambda s: s["path"]):
        raw = _read(root, source["path"])
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise PreviewError("total input byte limit exceeded")
        if _hash(raw) != source["sha256"]:
            raise PreviewError("input hash changed; review the mapping again")
        text = raw.decode("utf-8")
        inputs.append({**source, "raw": text})
        duplicates = Counter()
        for block in _blocks(text):
            identity = [manifest["namespace"], source["path"], block["section"], block["raw"]]
            key = _json(identity)
            ordinal = duplicates[key]
            duplicates[key] += 1
            record_id = "record-" + _hash(_json([*identity, ordinal]).encode())
            records.append({**block, "record_id": record_id, "path": source["path"], "kind": source["kind"],
                            "status": "unresolved", "reason": "no explicit observation mapping", "proposal": None})
            if len(records) > MAX_RECORDS:
                raise PreviewError("record limit exceeded")
    mapping = {m["record_id"]: m for m in manifest["mappings"]}
    if set(mapping) - {r["record_id"] for r in records}:
        raise PreviewError("mapping references missing or changed evidence")
    groups = defaultdict(list)
    for r in records:
        m = mapping.get(r["record_id"])
        if m:
            r["proposal"] = {k: deepcopy(v) for k, v in m.items() if k != "record_id"}
            groups[m["observation_key"]].append(r)
    invalid = {}
    for key, group in groups.items():
        if any(r["parse_issue"] for r in group):
            invalid[key] = "malformed evidence row"
        elif len({_json(r["proposal"]) for r in group}) != 1:
            invalid[key] = "contradictory mappings for one observation"
        elif group[0]["proposal"]["repetition_of"] == key:
            invalid[key] = "self-repetition reference"
    # Only already resolved provenance can be repeated. Cycles are conflicts.
    resolved = set()
    def resolve(key, visiting):
        if key in resolved:
            return True
        if key in invalid:
            return False
        if len(visiting) >= 128:
            invalid[key] = "repetition chain exceeds supported depth"
            return False
        if key in visiting:
            invalid[key] = "cyclic repetition reference"
            return False
        p = groups[key][0]["proposal"]
        parent = p["repetition_of"]
        if parent is not None:
            if parent not in groups or not resolve(parent, visiting | {key}):
                invalid[key] = "unresolved repetition reference"
                return False
            if p["original_source"] != groups[parent][0]["proposal"]["original_source"]:
                invalid[key] = "original provenance differs from repeated observation"
                return False
        resolved.add(key)
        return True
    for key in sorted(groups):
        resolve(key, set())
    observations = []
    def proposed_id(key):
        return "legacy-" + _hash(_json([manifest["namespace"], manifest["learner_id"], key]).encode())
    for key, group in sorted(groups.items()):
        if key in invalid:
            for r in group:
                r.update(status="conflict", reason=invalid[key])
            continue
        p = deepcopy(group[0]["proposal"])
        if p["repetition_of"] is not None:
            p["repetition_of"] = proposed_id(p["repetition_of"])
        p.update(proposed_id=proposed_id(key), record_ids=sorted(r["record_id"] for r in group))
        observations.append(p)
        for r in group:
            r.update(status="proposed", reason="explicit operator mapping")
    counts = dict(records=len(records), proposed=0, unresolved=0, conflict=0, observations=len(observations))
    for r in records:
        counts[r["status"]] += 1
    by_input = []
    for source in inputs:
        rows = [r for r in records if r["path"] == source["path"]]
        by_input.append(dict(path=source["path"], kind=source["kind"], records=len(rows),
                             **{s: sum(r["status"] == s for r in rows) for s in ("proposed", "unresolved", "conflict")}))
    canonical_manifest = {**manifest, "inputs": sorted(manifest["inputs"], key=lambda s: s["path"]),
                          "mappings": sorted(manifest["mappings"], key=lambda m: m["record_id"])}
    return dict(format_version=1, kind="legacy_migration_preview", namespace=manifest["namespace"],
                learner_id=manifest["learner_id"], manifest_sha256=_hash(_json(canonical_manifest).encode()),
                inputs=inputs, records=records, observations=observations, counts=counts, by_input=by_input,
                apply_authorized=False, human_evidence_review="incomplete")


def write_report(report, output, *, forbidden_roots=()):
    """Publish one fresh private report; refuse code, source and operator roots."""
    output = Path(output).expanduser()
    parent = output.parent.resolve(strict=True)
    roots = [Path(p).expanduser().resolve() for p in forbidden_roots]
    package = Path(__file__).resolve()
    roots.append(next((p for p in package.parents if (p / ".git").exists()), package.parents[2]))
    if any(parent.is_relative_to(p) for p in roots) or any((p / ".git").exists() for p in [parent, *parent.parents]):
        raise PreviewError("report destination overlaps a protected checkout or data root")
    before = parent.stat()
    if before.st_mode & 0o077:
        raise PreviewError("report parent must be a private directory")
    data = (_json(report) + "\n").encode()
    directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        now = os.fstat(directory)
        if (before.st_dev, before.st_ino) != (now.st_dev, now.st_ino):
            raise PreviewError("report parent changed")
        fd = os.open(output.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    finally:
        os.close(directory)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preview historical migration without applying it")
    parser.add_argument("--root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--protected-root", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        manifest_path = Path(args.manifest).expanduser().absolute()
        manifest = json.loads(_read(manifest_path.parent, manifest_path.name).decode("utf-8"), object_pairs_hook=_unique_object)
        report = plan_preview(args.root, manifest)
        write_report(report, args.output, forbidden_roots=[args.root, *args.protected_root])
    except (ValueError, OSError, RecursionError):
        parser.exit(2, "migration preview refused; check private inputs, mapping and output settings\n")
    print(_json({"counts": report["counts"], "apply_authorized": False}))


if __name__ == "__main__":
    main()
