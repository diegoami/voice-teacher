"""Operator-allowlisted, read-only Git transport feeding the validated registry."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
from urllib.parse import urlsplit

from schemas.validate import canonical_json
from ..storage.sqlite import _id
from .registry import SourceRegistry, SourceSpec, SourceError, _relative
from .adapters import LegacyAdapter

FAILED = "Git source refresh failed; the prior validated catalogue is retained"


def _remote(value):
    if not isinstance(value,str) or not value or len(value)>4096 or any(ord(c)<32 or ord(c)==127 for c in value):raise SourceError("invalid Git source remote")
    parsed=urlsplit(value)
    if parsed.scheme:
        if parsed.scheme!="https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise SourceError("use a credential-free HTTPS source URL or an allowed absolute local remote")
    elif not Path(value).is_absolute():raise SourceError("local source remote must be absolute")
    return value


def _digest(value):return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _private(path):
    if path.is_symlink() or (path.exists() and not path.is_dir()):raise SourceError("managed source paths must be directories without symlinks")
    path.mkdir(mode=0o700,exist_ok=True)
    if path.stat().st_mode & 0o077:raise SourceError("managed source directories must be private")


def _write(path,value):
    if path.is_symlink():raise SourceError("managed source metadata symlinks are refused")
    body=canonical_json(value)
    if len(body.encode())>32768:raise SourceError("managed source configuration exceeds limit")
    fd,name=tempfile.mkstemp(prefix=".pending-",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf8") as f:f.write(body);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(name):os.unlink(name)


def _read(path):
    if path.is_symlink():raise SourceError("managed source metadata symlinks are refused")
    with path.open("rb") as f:data=f.read(32769)
    if len(data)>32768:raise SourceError("managed source configuration exceeds limit")
    try:return json.loads(data)
    except ValueError:raise SourceError("invalid managed source configuration") from None


@dataclass(frozen=True)
class GitSourcePolicy:
    allowed_remotes: tuple[str,...]
    allowed_local_roots: tuple[str,...] = ()
    credential_askpass: str | None = None
    timeout: float = 30
    max_file_bytes: int = 64*1024*1024
    max_cache_bytes: int = 256*1024*1024
    max_entries: int = 50000

    @classmethod
    def from_file(cls,path,*,forbidden_roots=()):
        path=Path(path).expanduser()
        if not path.is_absolute() or any(p.is_symlink() for p in (path,*path.parents)) or any((p/".git").exists() for p in path.parents) or any(path.resolve().is_relative_to(Path(root).resolve()) for root in forbidden_roots):raise SourceError("source policy must be a private server configuration outside Git/content")
        if not path.is_file() or path.stat().st_mode & 0o077:raise SourceError("source policy must be a private regular file")
        value=_read(path)
        if not isinstance(value,dict):raise SourceError("unsupported source policy format")
        version=value.pop("schema_version",None)
        if type(version) is not int or version!=1:raise SourceError("unsupported source policy format")
        for name in ("allowed_remotes","allowed_local_roots"):
            if name in value:
                if not isinstance(value[name],list) or not all(isinstance(v,str) for v in value[name]):raise SourceError("invalid source policy allowlist")
                value[name]=tuple(value[name])
        try:return cls(**value)
        except TypeError:raise SourceError("unknown or missing source policy field") from None

    def validate(self):
        if not isinstance(self.allowed_remotes,tuple) or not self.allowed_remotes or len(self.allowed_remotes)>32:raise SourceError("configure one to 32 explicit allowed source remotes")
        if type(self.timeout) not in {int,float} or not 0<self.timeout<=120:raise SourceError("invalid source timeout")
        for value in (self.max_file_bytes,self.max_cache_bytes,self.max_entries):
            if type(value) is not int or value<=0:raise SourceError("invalid managed source budget")
        if self.max_file_bytes>1024**3 or self.max_cache_bytes>4*1024**3 or self.max_entries>1000000:raise SourceError("managed source budget exceeds supported limit")
        if not isinstance(self.allowed_local_roots,tuple) or not all(isinstance(v,str) and Path(v).is_absolute() for v in self.allowed_local_roots):raise SourceError("local source roots must be absolute")
        for remote in self.allowed_remotes:self.check(remote)

    def check(self,remote):
        _remote(remote)
        if remote not in self.allowed_remotes:raise SourceError("source remote is not in the server's allowlist")
        if not urlsplit(remote).scheme:
            path=Path(remote)
            # Reject logical symlinks as well as escapes after canonicalization.
            if any(p.is_symlink() for p in (path,*path.parents)):raise SourceError("local remote symlinks are refused")
            if not any(path.resolve().is_relative_to(Path(root).resolve()) for root in self.allowed_local_roots):raise SourceError("local remote is outside allowed source roots")


@dataclass(frozen=True)
class GitSourceSpec:
    source_id: str
    name: str
    remote: str
    ref_kind: str = "branch"
    ref_name: str = "main"
    subdirectory: str = "."
    adapter: str = "canonical_json"
    manifest: str = "voice-teacher.json"
    mapping: dict | None = None


class GitSources:
    def __init__(self,store,policy):
        policy.validate()
        self.store,self.policy,self.registry=store,policy,SourceRegistry(store)
        self.root=store.path.parent/"lesson-sources"
        _private(self.root)
        self.configs=self.root/"configs";_private(self.configs)
        self.repositories=self.root/"repositories";_private(self.repositories)
        self.git=shutil.which("git",path="/usr/bin:/bin")
        self.prlimit=shutil.which("prlimit",path="/usr/bin:/bin")
        if not self.git or not self.prlimit:raise SourceError("managed Git sources require Git and util-linux prlimit")
        code=next((p for p in Path(__file__).resolve().parents if (p/".git").exists()),Path(__file__).resolve().parents[2])
        self.protected=(code,store.path.parent)
        self.askpass="/bin/false"
        if policy.credential_askpass is not None:
            helper=Path(policy.credential_askpass)
            code=next((p for p in Path(__file__).resolve().parents if (p/".git").exists()),Path(__file__).resolve().parents[3])
            protected=[code,self.root,*[Path(r) for r in policy.allowed_remotes if not urlsplit(r).scheme]]
            with store._connection() as c:
                protected.extend(Path(json.loads(r[0])["checkout"]) for r in c.execute("SELECT config_json FROM sources"))
            if not helper.is_absolute() or not re.fullmatch(r"[A-Za-z0-9/._-]+",str(helper)) or any(p.is_symlink() or (p/".git").exists() for p in (helper,*helper.parents)) or not helper.is_file() or helper.stat().st_mode & 0o022 or not os.access(helper,os.X_OK) or any(helper.resolve().is_relative_to(p.resolve()) for p in protected):raise SourceError("credential helper must be a trusted executable outside code and content")
            self.askpass=str(helper.resolve())

    @contextmanager
    def _locked(self):
        if any(p.is_symlink() for p in (self.root,self.configs,self.repositories)):raise SourceError("managed source directory symlinks are refused")
        fd=os.open(self.root/"manager.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise SourceError("another source operation is active; retry later") from None
            yield
        finally:os.close(fd)

    def _budget(self):
        total,count=0,0;pending=[self.root]
        while pending:
            path=pending.pop()
            with os.scandir(path) as entries:
                for entry in entries:
                    count+=1
                    if entry.is_dir(follow_symlinks=False):pending.append(Path(entry.path))
                    else:total+=entry.stat(follow_symlinks=False).st_size
                    if total>self.policy.max_cache_bytes or count>self.policy.max_entries:raise SourceError("managed source cache limit reached; operator inspection required")

    def _git(self,checkout,*args):
        self._budget()
        command=[self.prlimit,f"--fsize={self.policy.max_file_bytes}:{self.policy.max_file_bytes}","--",self.git,
            "-c","core.hooksPath=/dev/null","-c","core.fsmonitor=false","-c","core.attributesFile=/dev/null",
            "-c","http.followRedirects=false","-c","protocol.ext.allow=never","-c","protocol.https.allow=always",
            "-c","protocol.file.allow=always","-c","submodule.recurse=false","-c","gc.auto=0","-C",str(checkout),*args]
        env={"PATH":"/usr/bin:/bin","HOME":"/nonexistent","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"/dev/null",
             "GIT_TERMINAL_PROMPT":"0","GIT_ASKPASS":self.askpass,"LC_ALL":"C"}
        with tempfile.TemporaryFile(dir=self.root) as out,tempfile.TemporaryFile(dir=self.root) as err:
            p=subprocess.Popen(command,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
            try:
                try:p.wait(timeout=self.policy.timeout)
                except subprocess.TimeoutExpired:raise SourceError("Git source operation timed out") from None
                out.seek(0);data=out.read(65537)
                if p.returncode or len(data)>65536:raise SourceError("Git source operation failed")
            finally:
                try:os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                p.wait()
        self._budget();return data

    def _validate(self,spec):
        _id(spec.source_id);self.policy.check(spec.remote)
        if not urlsplit(spec.remote).scheme:
            remote=Path(spec.remote).resolve()
            if any(remote.is_relative_to(p.resolve()) or p.resolve().is_relative_to(remote) for p in self.protected):raise SourceError("source remote overlaps application code or runtime storage")
        if not isinstance(spec.name,str) or not spec.name.strip() or len(spec.name)>100:raise SourceError("source name required")
        if spec.ref_kind not in {"branch","tag"} or not isinstance(spec.ref_name,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}",spec.ref_name):raise SourceError("invalid source branch or tag")
        ref="refs/"+("heads/" if spec.ref_kind=="branch" else "tags/")+spec.ref_name
        self._git(self.root,"check-ref-format",ref)
        for value in (spec.subdirectory,spec.manifest):
            parts=_relative(value).parts
            if any(p.lower()==".git" for p in parts):raise SourceError("content cannot select Git metadata")
        if spec.adapter=="legacy":
            try: LegacyAdapter(spec.mapping)
            except (ValueError,TypeError): raise SourceError("invalid legacy source mapping") from None
            if spec.mapping["source_id"]!=spec.source_id:raise SourceError("legacy source namespace mismatch")
        elif spec.adapter!="canonical_json" or spec.mapping is not None:raise SourceError("invalid source adapter or mapping")

    def register(self,spec):
        with self._locked():
            self._validate(spec)
            _write(self.configs/(spec.source_id+".json"),{"schema_version":1,"spec":asdict(spec)})
            return self._refresh(spec)

    def refresh(self,source_id):
        with self._locked():
            try:
                value=_read(self.configs/(_id(source_id)+".json"))
                if not isinstance(value,dict) or set(value)!={"schema_version","spec"} or type(value["schema_version"]) is not int or value["schema_version"]!=1:raise ValueError()
                spec=GitSourceSpec(**value["spec"])
                if spec.source_id!=source_id:raise ValueError()
            except (OSError,TypeError,ValueError):raise SourceError("managed source is not configured correctly") from None
            self._validate(spec);return self._refresh(spec)

    def _refresh(self,spec):
        try:
            source_root=self.repositories/spec.source_id;_private(source_root)
            container=source_root/_digest(asdict(spec));_private(container)
            checkout=container/"checkout";marker=container/"managed.json"
            if checkout.is_symlink() or marker.is_symlink():raise SourceError("managed repository symlinks are refused")
            if marker.exists():
                if not checkout.is_dir() or (checkout/".git").is_symlink() or not (checkout/".git").is_dir():raise SourceError("managed Git repository changed")
                prior=_read(marker)
                config=self._git(checkout,"config","--local","--null","--list")
                if prior!={"spec":_digest(asdict(spec)),"config":hashlib.sha256(config).hexdigest()}:raise SourceError("managed Git configuration changed")
            else:
                if checkout.exists() and any(checkout.iterdir()):raise SourceError("refusing an unmanaged checkout")
                _private(checkout)
                self._git(checkout,"init","--template=","-q")
                self._git(checkout,"config","core.hooksPath","/dev/null")
                self._git(checkout,"config","core.fsmonitor","false")
                self._git(checkout,"config","core.autocrlf","false")
                self._git(checkout,"config","gc.auto","0")
                self._git(checkout,"remote","add","origin",spec.remote)
                config=self._git(checkout,"config","--local","--null","--list")
                _write(marker,{"spec":_digest(asdict(spec)),"config":hashlib.sha256(config).hexdigest()})
            if self._git(checkout,"status","--porcelain=v1","--untracked-files=all","--ignored").strip():raise SourceError("managed checkout has local changes; operator inspection required")
            ref="refs/"+("heads/" if spec.ref_kind=="branch" else "tags/")+spec.ref_name
            self._git(checkout,"fetch","--quiet","--no-tags","--no-recurse-submodules","--depth=1","origin",ref)
            commit=self._git(checkout,"rev-parse","--verify","FETCH_HEAD^{commit}").decode().strip()
            if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}",commit):raise SourceError("invalid fetched revision")
            self._git(checkout,"checkout","--quiet","--detach","--no-overwrite-ignore",commit)
            self.registry.register(SourceSpec(spec.source_id,spec.name,str(checkout),spec.subdirectory,spec.adapter,spec.manifest,spec.mapping,False))
            return self.registry.refresh(spec.source_id)
        except Exception:
            with self.store._transaction() as c:c.execute("UPDATE sources SET last_error=? WHERE source_id=?",(FAILED,spec.source_id))
            raise SourceError(FAILED) from None
