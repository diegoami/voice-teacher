"""Transactional legacy evidence. Unknown historical turns remain unknown."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from .preview import (_json, _hash, _shape, _text, plan_preview, plan_from_bytes,
                      PreviewError)
from .archive import Archive, _directory

APPLICATION_ID = 0x56544C31
VERSION = 1
MAX_BATCH_BYTES = 64 * 1024 * 1024


class LegacyError(ValueError):
    pass


def _approval(report, approval):
    _shape(approval, ["format_version", "reviewed", "approved_by", "preview_sha256",
                      "selected_observation_ids", "course_positions", "destination_remote"])
    if type(approval["format_version"]) is not int or approval["format_version"] != 1 or approval["reviewed"] is not True or not _text(approval["approved_by"]):
        raise LegacyError("explicit reviewed approval required")
    if approval["preview_sha256"] != _hash(_json(report).encode()):
        raise LegacyError("preview changed since approval")
    selected = approval["selected_observation_ids"]
    if not isinstance(selected, list) or not selected or not all(_text(x) for x in selected) or len(set(selected)) != len(selected):
        raise LegacyError("nonempty unique selected observations required")
    available = {o["proposed_id"]: o for o in report["observations"]}
    if set(selected) - available.keys():
        raise LegacyError("selected observation is unresolved or missing")
    if any(available[x]["repetition_of"] is not None and available[x]["repetition_of"] not in selected for x in selected):
        raise LegacyError("selected repetition requires its selected original")
    positions = approval["course_positions"]
    if not isinstance(positions, list) or len(positions) > 128:
        raise LegacyError("invalid course positions")
    proposed = {r["record_id"] for r in report["records"] if r["status"] == "proposed"}
    seen = set()
    for p in positions:
        _shape(p, ["source_id", "course_id", "covered_lesson_ids", "next_lesson_id", "evidence_record_ids"])
        if not all(_text(p[k]) for k in ("source_id", "course_id")):
            raise LegacyError("invalid legacy course identity")
        key = (p["source_id"], p["course_id"])
        if key in seen:
            raise LegacyError("duplicate course position")
        seen.add(key)
        covered, evidence = p["covered_lesson_ids"], p["evidence_record_ids"]
        if not isinstance(covered, list) or not all(_text(x) for x in covered) or len(set(covered)) != len(covered):
            raise LegacyError("invalid covered lesson identities")
        if p["next_lesson_id"] is not None and (not _text(p["next_lesson_id"]) or p["next_lesson_id"] in covered):
            raise LegacyError("invalid next lesson identity")
        if not isinstance(evidence, list) or not evidence or not all(_text(x) for x in evidence) or len(set(evidence)) != len(evidence) or set(evidence) - proposed:
            raise LegacyError("course position requires mapped evidence")
        references = [r["proposal"]["original_source"] for r in report["records"] if r["record_id"] in evidence]
        if any((r["source_id"], r["course_id"]) != key for r in references):
            raise LegacyError("course position evidence belongs to another source/course")
    return [available[x] for x in sorted(selected)]


def build_batch(root, manifest, approval):
    report = plan_preview(root, manifest)
    _approval(report, approval)
    return dict(format_version=1, kind="private_legacy_history_batch", report=report, approval=approval)


def _validated(batch):
    """Rebuild archived reports from their retained bytes before activating data."""
    _shape(batch, ["format_version", "kind", "report", "approval"])
    if type(batch["format_version"]) is not int or batch["format_version"] != 1 or batch["kind"] != "private_legacy_history_batch":
        raise LegacyError("unsupported legacy batch")
    report = batch["report"]
    try:
        manifest = dict(format_version=1, namespace=report["namespace"], learner_id=report["learner_id"],
                        inputs=[{k: s[k] for k in ("path", "kind", "sha256")} for s in report["inputs"]],
                        mappings=[dict(record_id=r["record_id"], **r["proposal"]) for r in report["records"] if r["proposal"] is not None])
        inputs = {s["path"]: s["raw"].encode("utf-8") for s in report["inputs"]}
        if plan_from_bytes(manifest, inputs) != report:
            raise LegacyError("archived preview differs from original evidence")
        observations = _approval(report, batch["approval"])
    except (KeyError, TypeError, PreviewError):
        raise LegacyError("invalid archived legacy evidence") from None
    data = _json(batch).encode()
    if len(data) > MAX_BATCH_BYTES:
        raise LegacyError("legacy batch exceeds byte limit")
    return _hash(data), data, observations


class LegacyLedger:
    """Separate branded SQLite ledger; canonical practice sessions are untouched."""
    def __init__(self, directory, *, destination_remote, private_verified=False,
                 owner_verified=False, forbidden_roots=()):
        if private_verified is not True or owner_verified is not True:
            raise LegacyError("verify private destination ownership and visibility first")
        if not isinstance(destination_remote, str):
            raise LegacyError("invalid legacy destination")
        url = urlsplit(destination_remote)
        if url.scheme:
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise LegacyError("use a credential-free destination")
        elif not Path(destination_remote).is_absolute():
            raise LegacyError("local test destination must be absolute")
        directory = Path(directory).expanduser().resolve()
        code = next((p for p in Path(__file__).resolve().parents if (p / ".git").exists()), Path(__file__).resolve().parents[2])
        protected = [code, *(Path(p).resolve() for p in forbidden_roots)]
        if any(directory.is_relative_to(p) or p.is_relative_to(directory) for p in protected) or any((p / ".git").exists() for p in [directory, *directory.parents]):
            raise LegacyError("legacy runtime overlaps code/content/Git")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.stat().st_mode & 0o077:
            raise LegacyError("legacy runtime must be private")
        self.path = directory / "legacy-import.sqlite"
        self.remote = destination_remote
        if self.path.is_symlink():
            raise LegacyError("legacy database symlinks refused")
        if self.path.exists():
            with sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True) as c:
                self._version(c)
        else:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600))
            except FileExistsError:
                pass
        with self._transaction() as c:
            version = self._version(c)
            if version == 0:
                c.execute("CREATE TABLE imports (import_id TEXT PRIMARY KEY, learner_id TEXT NOT NULL, body_json TEXT NOT NULL, exported INTEGER NOT NULL DEFAULT 0)")
                c.execute("CREATE TABLE observations (learner_id TEXT NOT NULL, observation_id TEXT NOT NULL, body_json TEXT NOT NULL, PRIMARY KEY(learner_id,observation_id))")
                c.execute("CREATE TABLE course_positions (learner_id TEXT NOT NULL, source_id TEXT NOT NULL, course_id TEXT NOT NULL, body_json TEXT NOT NULL, PRIMARY KEY(learner_id,source_id,course_id))")
                c.execute("CREATE TABLE destination (remote TEXT NOT NULL)")
                c.execute("INSERT INTO destination VALUES (?)", (self.remote,))
                c.execute(f"PRAGMA application_id={APPLICATION_ID}")
                c.execute(f"PRAGMA user_version={VERSION}")
            if c.execute("SELECT remote FROM destination").fetchone()[0] != self.remote:
                raise LegacyError("legacy destination changed; use an explicit verified handoff")

    @staticmethod
    def _version(c):
        version, brand = c.execute("PRAGMA user_version").fetchone()[0], c.execute("PRAGMA application_id").fetchone()[0]
        if version not in {0, VERSION} or (version and brand != APPLICATION_ID):
            raise LegacyError("unsupported legacy database")
        if version == 0 and (brand not in {0, APPLICATION_ID} or c.execute("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone()):
            raise LegacyError("refuse foreign unversioned legacy database")
        return version

    @contextmanager
    def _connection(self):
        if self.path.is_symlink():
            raise LegacyError("legacy database symlinks refused")
        c = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA synchronous=FULL")
            yield c
        finally:
            c.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.commit()
            except BaseException:
                c.rollback()
                raise

    def _insert_observation(self, c, learner, observation):
        body = _json(observation)
        old = c.execute("SELECT body_json FROM observations WHERE learner_id=? AND observation_id=?", (learner, observation["proposed_id"])).fetchone()
        if old is not None and old[0] != body:
            raise LegacyError("historical observation ID has conflicting evidence")
        c.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?)", (learner, observation["proposed_id"], body))
        return int(old is None)

    def _insert(self, c, batch):
        identity, data, observations = _validated(batch)
        report, approval = batch["report"], batch["approval"]
        if approval["destination_remote"] != self.remote:
            raise LegacyError("approval belongs to another private destination")
        learner = report["learner_id"]
        old = c.execute("SELECT body_json FROM imports WHERE import_id=?", (identity,)).fetchone()
        if old:
            if old[0].encode() != data:
                raise LegacyError("legacy import collision")
            return dict(imports=0, observations=0)
        added = sum(self._insert_observation(c, learner, observation) for observation in observations)
        for position in approval["course_positions"]:
            body = _json(position)
            key = (learner, position["source_id"], position["course_id"])
            old = c.execute("SELECT body_json FROM course_positions WHERE learner_id=? AND source_id=? AND course_id=?", key).fetchone()
            if old is not None and old[0] != body:
                raise LegacyError("historical position conflict requires explicit review")
            c.execute("INSERT OR IGNORE INTO course_positions VALUES (?,?,?,?)", (*key, body))
        c.execute("INSERT INTO imports VALUES (?,?,?,0)", (identity, learner, data.decode()))
        return dict(imports=1, observations=added)

    def apply(self, root, manifest, approval):
        batch = build_batch(root, manifest, approval)
        with self._transaction() as c:
            return self._insert(c, batch)

    def history(self, learner):
        with self._connection() as c:
            return [json.loads(r[0]) for r in c.execute("SELECT body_json FROM observations WHERE learner_id=? ORDER BY observation_id", (learner,))]

    def positions(self, learner):
        with self._connection() as c:
            return [json.loads(r[0]) for r in c.execute("SELECT body_json FROM course_positions WHERE learner_id=? ORDER BY source_id,course_id", (learner,))]

    def batches(self):
        with self._connection() as c:
            return [json.loads(r[0]) for r in c.execute("SELECT body_json FROM imports ORDER BY import_id")]

    def restore(self, batches):
        # Validate the complete incoming set before activating any projections.
        for batch in batches:
            _validated(batch)
        result = dict(imports=0, observations=0)
        with self._transaction() as c:
            for batch in batches:
                added = self._insert(c, batch)
                for key in result:
                    result[key] += added[key]
        return result


class LegacyArchive(Archive):
    """Immutable private evidence batches; same guarded publication as T11."""
    NAMESPACE = Path("voice-teacher/legacy-v1/batches")

    def __init__(self, destination, **kwargs):
        kwargs.setdefault("max_batch_bytes", MAX_BATCH_BYTES)
        super().__init__(destination, **kwargs)

    def read(self):
        path = self.root / self.NAMESPACE
        if not path.exists():
            # Refuse existing symlink components even if their target is absent.
            current = self.root
            for part in self.NAMESPACE.parts:
                current /= part
                if current.is_symlink():
                    raise LegacyError("legacy archive symlinks refused")
            return []
        directory = _directory(self.root, self.NAMESPACE)
        result, consumed = [], 0
        paths = sorted(directory.iterdir())
        if len(paths) > self.max_batches:
            raise LegacyError("legacy archive count limit exceeded")
        for p in paths:
            if p.is_symlink():
                raise LegacyError("legacy archive symlinks refused")
            if p.name.startswith(".pending-"):
                continue
            if not p.is_file() or not re.fullmatch(r"[a-f0-9]{64}\.json", p.name):
                raise LegacyError("unexpected legacy batch file")
            with p.open("rb") as stream:
                data = stream.read(self.max_batch_bytes + 1)
            consumed += len(data)
            if len(data) > self.max_batch_bytes or consumed > self.max_archive_bytes:
                raise LegacyError("legacy archive byte limit exceeded")
            value = json.loads(data)
            identity, canonical, _ = _validated(value)
            if data != canonical or p.stem != identity:
                raise LegacyError("legacy archive checksum or canonical format mismatch")
            result.append(value)
        return result

    def export(self, ledger):
        if ledger.path.is_relative_to(self.root) or self.root.is_relative_to(ledger.path.parent):
            raise LegacyError("legacy runtime and archive must be separate")
        written = []
        for batch in ledger.batches():
            identity, _, _ = _validated(batch)
            name = self._publish(batch)
            with ledger._transaction() as c:
                c.execute("UPDATE imports SET exported=1 WHERE import_id=?", (identity,))
            written.append(name)
        return written

    def restore(self, ledger):
        if ledger.path.is_relative_to(self.root) or self.root.is_relative_to(ledger.path.parent):
            raise LegacyError("legacy runtime and archive must be separate")
        return ledger.restore(self.read())


def main(argv=None):
    """Explicit local application/export; Git push remains the configured worker."""
    import argparse
    from .preview import _read, _unique_object
    parser = argparse.ArgumentParser(description="Apply a reviewed private legacy-history sample")
    parser.add_argument("--root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--remote", required=True)
    parser.add_argument("--private-verified", action="store_true", required=True)
    parser.add_argument("--owner-verified", action="store_true", required=True)
    args = parser.parse_args(argv)
    def load(name):
        p = Path(name).expanduser().absolute()
        return json.loads(_read(p.parent, p.name).decode(), object_pairs_hook=_unique_object)
    try:
        manifest, approval = load(args.manifest), load(args.approval)
        batch = build_batch(args.root, manifest, approval)
        if approval["destination_remote"] != args.remote:
            raise LegacyError("approval belongs to another destination")
        ledger = LegacyLedger(args.runtime, destination_remote=args.remote, private_verified=args.private_verified,
                              owner_verified=args.owner_verified, forbidden_roots=[args.root, args.destination])
        archive = LegacyArchive(args.destination, forbidden_roots=[args.root, args.runtime])
        result = ledger.restore([batch])
        archive.export(ledger)
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
        parser.exit(2, "legacy import refused or incomplete; private local state retained for retry\n")
    print(_json({**result, "locally_exported": True, "remote_push": "not performed"}))


if __name__ == "__main__":
    main()
