"""Single-writer, background Git synchronization of immutable progress batches."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from urllib.parse import urlsplit
from uuid import uuid4

from schemas.validate import canonical_json
from .archive import Archive, _sync


class SyncError(ValueError):
    pass


def _write(path, value):
    if path.is_symlink(): raise SyncError("sync metadata symlinks are refused")
    fd, name = tempfile.mkstemp(prefix=".sync-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(canonical_json(value)); f.flush(); os.fsync(f.fileno())
        os.replace(name, path); _sync(path.parent)
    finally:
        if os.path.exists(name): os.unlink(name)


def _read(path):
    if path.is_symlink(): raise SyncError("sync metadata symlinks are refused")
    if not path.exists(): return None
    with path.open("rb") as f: data = f.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024: raise SyncError("sync metadata exceeds limit")
    try: return json.loads(data)
    except ValueError: raise SyncError("invalid sync metadata") from None


class GitSync:
    def __init__(self, store, checkout, remote, *, branch="main", private_verified=False,
                 owner_verified=False, forbidden_roots=(), credential_askpass=None, timeout=30, legacy=None):
        if private_verified is not True or owner_verified is not True:
            raise SyncError("operator must explicitly verify destination privacy and ownership")
        if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", branch) or branch.endswith(".") or ".." in branch:
            raise SyncError("invalid progress branch")
        if not isinstance(remote, str): raise SyncError("invalid progress remote")
        parsed = urlsplit(remote)
        if parsed.scheme:
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise SyncError("use a credential-free HTTPS URL or absolute local remote")
        elif not Path(remote).is_absolute(): raise SyncError("local remote must be absolute")
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 120: raise SyncError("invalid Git timeout")
        self.store, self.checkout, self.remote, self.branch = store, Path(checkout).expanduser().resolve(), remote, branch
        self.legacy = legacy
        if legacy is not None and (legacy.path.parent != store.path.parent or legacy.remote != remote):
            raise SyncError("legacy ledger must use the same runtime and verified destination")
        if store.path.is_relative_to(self.checkout) or self.checkout.is_relative_to(store.path.parent):
            raise SyncError("managed progress checkout must be separate from runtime storage")
        package = Path(__file__).resolve().parents[1]
        code = next((p for p in package.parents if (p / ".git").exists()), package.parent)
        protected = [code, *(Path(p).resolve() for p in forbidden_roots)]
        with store._connection() as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='sources'").fetchone():
                protected.extend(Path(json.loads(row[0])["checkout"]).resolve() for row in c.execute("SELECT config_json FROM sources"))
        if any(self.checkout.is_relative_to(p) or p.is_relative_to(self.checkout) for p in protected):
            raise SyncError("managed checkout overlaps code or content")
        self.timeout, self.askpass = timeout, None
        if credential_askpass is not None:
            helper = Path(credential_askpass).resolve()
            if not helper.is_file() or helper.is_relative_to(self.checkout) or any(helper.is_relative_to(p) for p in protected):
                raise SyncError("credential helper must be operator-owned outside code/content checkouts")
            self.askpass = str(helper)
        self.state_path = store.path.parent / "progress-sync.json"
        binding = [str(self.checkout), remote, branch, str(Archive.NAMESPACE)]
        if legacy is not None:
            binding.append("voice-teacher/legacy-v1/batches")
        self.fingerprint = hashlib.sha256(canonical_json(binding).encode()).hexdigest()
        self.git_dir = self.checkout / ".git"
        with self._locked():
            # Binding reads/checks and every initialization write share the lock.
            # A stale pre-lock read must never replace another constructor's state.
            state = _read(self.state_path)
            if state is not None and state.get("destination") != self.fingerprint:
                raise SyncError("destination changed; use the verified handoff procedure and a fresh runtime")
            self.state = state or {"version": 1, "destination": self.fingerprint, "writer_id": str(uuid4()),
                                  "last_push_at": None, "last_push_commit": None, "pushed_ids": [], "error": None}
            if self.state.get("version") != 1: raise SyncError("unsupported sync metadata")
            self.checkout.mkdir(parents=True, mode=0o700, exist_ok=True)
            self.archive = Archive(self.checkout, forbidden_roots=forbidden_roots)
            self.legacy_archive = None
            if legacy is not None:
                from .legacy import LegacyArchive
                self.legacy_archive = LegacyArchive(self.checkout, forbidden_roots=forbidden_roots)
            if self.git_dir.is_symlink() or (self.git_dir.exists() and not self.git_dir.is_dir()):
                raise SyncError("managed checkout requires its own Git directory")
            if state is None and self.git_dir.exists():
                raise SyncError("refuse adoption of an existing checkout; use a new app-managed directory")
            if not self.git_dir.exists() and list(self.checkout.iterdir()):
                raise SyncError("new managed checkout must be empty")
            # Persist binding before initialization; interrupted setup can resume.
            _write(self.state_path, self.state)
            if not self.git_dir.exists():
                if list(self.checkout.iterdir()): raise SyncError("new managed checkout must be empty")
                self._git("init", "--template=", "-q", "-b", branch)
                self._git("remote", "add", "origin", remote)
            owner = self.git_dir / "voice-teacher-owner.json"
            identity = _read(owner)
            if identity is not None and identity != {"writer_id": self.state["writer_id"], "destination": self.fingerprint}:
                raise SyncError("managed checkout belongs to another writer")
            self._config()
            _write(owner, {"writer_id": self.state["writer_id"], "destination": self.fingerprint})
        self._stop = threading.Event()
        self._thread = None

    def _git(self, *args, allow_failure=False):
        env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "GIT_ATTR_NOSYSTEM": "1"}
        if self.askpass: env["GIT_ASKPASS"] = self.askpass
        try:
            p = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                "-c", "commit.gpgSign=false", "-c", "merge.gpgSign=false", "-c", "user.name=Voice Teacher",
                "-c", "user.email=voice-teacher@localhost.invalid", "-C", str(self.checkout), *args],
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired): raise SyncError("Git operation failed or timed out") from None
        if p.returncode and not allow_failure: raise SyncError("Git operation failed; local progress retained")
        return p

    @contextmanager
    def _locked(self):
        path = self.store.path.parent / "progress-sync.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise SyncError("progress sync is already running") from None
            yield
        finally: os.close(fd)

    def _config(self):
        if (self.git_dir / "config").is_symlink(): raise SyncError("Git config symlinks are refused")
        raw = self._git("config", "--local", "--no-includes", "--null", "--list").stdout.decode()
        expected = {"core.repositoryformatversion": "0", "core.filemode": "true", "core.bare": "false",
                    "core.logallrefupdates": "true", "remote.origin.url": self.remote,
                    "remote.origin.fetch": "+refs/heads/*:refs/remotes/origin/*"}
        values = {}
        for entry in raw.split("\0"):
            if not entry: continue
            key, _, value = entry.partition("\n")
            if key in values or expected.get(key) != value: raise SyncError("managed Git configuration changed; operator inspection required")
            values[key] = value
        if values != expected: raise SyncError("managed Git configuration is incomplete")
        if self._git("symbolic-ref", "--quiet", "--short", "HEAD", allow_failure=True).stdout.decode().strip() != self.branch:
            raise SyncError("managed checkout branch changed")
        if any((self.git_dir / n).exists() for n in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "index.lock")):
            raise SyncError("managed checkout has an unfinished Git operation")

    def _local_changes(self):
        # Only validated immutable untracked batches and abandoned temporary files
        # may survive an interrupted export. Never stage unrelated files.
        self.archive._read()
        if self.legacy_archive:
            self.legacy_archive.read()
        entries = self._git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout.split(b"\0")
        paths = []
        prefixes = [self.archive.NAMESPACE.as_posix() + "/"]
        if self.legacy_archive:
            prefixes.append(self.legacy_archive.NAMESPACE.as_posix() + "/")
        for entry in entries:
            if not entry: continue
            text = entry.decode("utf-8")
            state, path = text[:2], text[3:]
            prefix = next((p for p in prefixes if path.startswith(p)), None)
            if state not in {"??", "A "} or prefix is None: raise SyncError("managed checkout is dirty or conflicting; unrelated files retained")
            name = path[len(prefix):]
            if re.fullmatch(r"[a-f0-9]{64}\.json", name):
                if state == "A " and self._git("show", f":{path}").stdout != (self.checkout / path).read_bytes():
                    raise SyncError("staged batch differs from validated bytes")
                paths.append(path)
            elif state != "??" or not name.startswith(".pending-") or "/" in name:
                raise SyncError("unexpected or staged temporary file in managed checkout")
        return paths

    def _commit(self):
        paths = self._local_changes()
        if paths:
            self._git("add", "--", *paths)
            self._git("commit", "-qm", "Export committed voice-teacher progress")

    def _pull(self):
        refs = self._git("ls-remote", "--heads", "origin", f"refs/heads/{self.branch}").stdout
        if not refs: return
        self._git("fetch", "--no-tags", "origin", f"refs/heads/{self.branch}:refs/remotes/origin/{self.branch}")
        head = self._git("rev-parse", "--verify", "HEAD", allow_failure=True)
        if head.returncode:
            self._git("merge", "--ff-only", f"refs/remotes/origin/{self.branch}")
        else:
            self._git("merge", "--no-edit", f"refs/remotes/origin/{self.branch}")

    def run_once(self):
        with self._locked():
            self.state = _read(self.state_path)
            if self.state["destination"] != self.fingerprint: raise SyncError("destination changed")
            try:
                self._config(); self._commit(); self._pull()
                self.archive.restore(self.store)
                if self.legacy_archive:
                    self.legacy_archive.restore(self.legacy)
                # A crash can leave only some session batches locally; resolve
                # against Store during restore, then fill missing exported refs.
                present = {e["event_id"] for e in self.archive._read()[0]}
                present_decisions = {d["decision_id"] for d in self.archive.read_decisions()}
                with self.store._transaction() as c:
                    missing = [(r[0],) for r in c.execute("SELECT event_id FROM events") if r[0] not in present]
                    c.executemany("UPDATE outbox SET status='pending' WHERE job_id=?", missing)
                    missing_decisions = [(r[0],) for r in c.execute("SELECT decision_id FROM lesson_decisions") if r[0] not in present_decisions]
                    c.executemany("UPDATE lesson_decisions SET exported=0 WHERE decision_id=?", missing_decisions)
                self.archive.export(self.store)
                if self.legacy_archive:
                    self.legacy_archive.export(self.legacy)
                self._commit()
                head = self._git("rev-parse", "--verify", "HEAD", allow_failure=True)
                if head.returncode:
                    self.state["error"] = None; _write(self.state_path, self.state); return self.status()
                exported = self.archive.read()  # validate the complete archive before push
                decision_ids = [d["decision_id"] for d in self.archive.read_decisions()]
                legacy_ids = []
                if self.legacy_archive:
                    from .legacy import _validated
                    legacy_ids = ["legacy-import-" + _validated(b)[0] for b in self.legacy_archive.read()]
                self._git("push", "origin", f"HEAD:refs/heads/{self.branch}")
                self.state.update(last_push_at=datetime.now(timezone.utc).isoformat(),
                    last_push_commit=head.stdout.decode().strip(), pushed_ids=sorted([e["event_id"] for e in exported] + legacy_ids + decision_ids), error=None)
                _write(self.state_path, self.state)
            except Exception:
                self.state["error"] = "sync_failed_local_progress_retained"
                _write(self.state_path, self.state)
                raise
        return self.status()

    def status(self):
        state = _read(self.state_path)
        pushed = set(state["pushed_ids"])
        with self.store._connection() as c:
            events = [{"event_id": r[0], "state": "pushed" if r[0] in pushed else "exported" if r[1] == "done" else "locally_saved"}
                      for r in c.execute("SELECT e.event_id,o.status FROM events e JOIN outbox o ON o.job_id=e.event_id ORDER BY e.learner_id,e.session_id,e.sequence")]
            decisions = [{"decision_id": r[0], "state": "pushed" if r[0] in pushed else "exported" if r[1] else "locally_saved"}
                         for r in c.execute("SELECT decision_id,exported FROM lesson_decisions ORDER BY decision_id")]
        legacy = []
        if self.legacy is not None:
            with self.legacy._connection() as c:
                legacy = [{"import_id": r[0], "state": "pushed" if "legacy-import-" + r[0] in pushed else "exported" if r[1] else "locally_saved"}
                          for r in c.execute("SELECT import_id,exported FROM imports ORDER BY import_id")]
        result = {"events": events, "last_push_at": state["last_push_at"], "last_push_commit": state["last_push_commit"], "error": state["error"]}
        if self.legacy is not None:
            result["legacy_imports"] = legacy
        if decisions:
            result["lesson_decisions"] = decisions
        return result

    def start(self, *, interval=30):
        if not isinstance(interval, (int, float)) or not 0 < interval <= 3600: raise SyncError("invalid sync interval")
        if self._thread is not None and self._thread.is_alive(): raise SyncError("worker already started")
        self._stop.clear()
        def work():
            while not self._stop.is_set():
                try: self.run_once()
                except Exception: pass  # sanitized persistent status; retry next interval
                self._stop.wait(interval)
        self._thread = threading.Thread(target=work, name="voice-teacher-progress-sync", daemon=True)
        self._thread.start()

    def stop(self, *, timeout=5):
        if not isinstance(timeout, (int, float)) or not 0 <= timeout <= 60: raise SyncError("invalid stop timeout")
        self._stop.set()
        if self._thread is not None: self._thread.join(timeout=timeout)
        return self._thread is None or not self._thread.is_alive()
