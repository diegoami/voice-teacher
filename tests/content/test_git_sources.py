"""Temporary read-only Git remotes; no private repositories or credentials."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest

from schemas.validate import canonical_json
from voice_teacher.api import create_app
from voice_teacher.content.git_sources import GitSources,GitSourcePolicy,GitSourceSpec
from voice_teacher.content.registry import SourceRegistry,SourceError
from voice_teacher.practice.coordinator import Coordinator
from voice_teacher.practice.guided import plan_guided
from voice_teacher.providers import Judgement,Verdict
from voice_teacher.storage import Store

OPERATOR="synthetic-operator-"+"x"*40
ORIGIN="http://teacher.test"


def git(root,*args):
    return subprocess.check_output(["git","-c","core.hooksPath=/dev/null","-C",str(root),*args],env={"PATH":"/usr/bin:/bin","HOME":"/nonexistent","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"/dev/null","GIT_TERMINAL_PROMPT":"0"},stderr=subprocess.PIPE,text=True).strip()


def remote(tmp_path,name="alpha",*,subdirectory="."):
    work=tmp_path/(name+"-author");work.mkdir()
    git(work,"init","--template=","-q","-b","main")
    git(work,"config","user.name","Synthetic");git(work,"config","user.email","synthetic@example.invalid")
    raw=json.loads((Path(__file__).parents[1]/"contracts/fixtures/guided.json").read_text());raw["source_id"]=name
    root=work/subdirectory;root.mkdir(parents=True,exist_ok=True)
    (root/"voice-teacher.json").write_text(canonical_json(raw))
    git(work,"add","--",".");git(work,"commit","-qm","Synthetic initial catalogue")
    upstream=tmp_path/(name+"-remote.git");upstream.mkdir()
    git(upstream,"init","--bare","--template=","-q","-b","main")
    git(work,"remote","add","origin",str(upstream));git(work,"push","-q","origin","main")
    return work,upstream,raw


def update(work,raw,*,subdirectory="."):
    (work/subdirectory/"voice-teacher.json").write_text(canonical_json(raw))
    git(work,"add","--",".");git(work,"commit","-qm","Synthetic catalogue update");git(work,"push","-q","origin","main")


def manager(tmp_path,*remotes,**options):
    store=Store(tmp_path/"runtime")
    policy=GitSourcePolicy(tuple(str(r) for r in remotes),(str(tmp_path),),**options)
    return store,GitSources(store,policy)


class Judge:
    def __call__(self,item,text):return Judgement(Verdict("accept",True,"","",0,""),0,{})


def test_two_catalogues_fetch_valid_updates_and_keep_the_original_session_pinned(tmp_path):
    author,a,raw=remote(tmp_path);_,b,_=remote(tmp_path,"beta")
    store,m=manager(tmp_path,a,b)
    old=m.register(GitSourceSpec("alpha","Alpha",str(a)))
    beta=m.register(GitSourceSpec("beta","Beta",str(b)))
    assert old.curriculum["source_id"]=="alpha" and beta.curriculum["source_id"]=="beta"
    learner="synthetic-learner";store.save_learner(learner,{"level":"A2"})
    c=Coordinator(store,Judge());plan=plan_guided(old,"basics","lesson-1")
    snapshot=dict(schema_version=1,kind="session_snapshot",learner_id=learner,session_id="pinned",revision=0,event_sequence=0,mode="guided_conversation",status="created",source=old.source_ref("basics","lesson-1"),curriculum_snapshot=old.curriculum,topic=None,language="uk",instruction_language="en",learner_profile={"level":"A2"},engine_state={"format_version":1,"data":{}})
    initial=c.create_guided(snapshot,plan)
    changed=deepcopy(raw);changed["courses"][0]["items"][0].update(item_revision=2,text={"display":"Вітаю","speech":"Віта́ю"})
    changed["courses"][0]["lessons"][0]["guided_steps"][0]["teacher"]={"display":"Updated instruction","speech":"Updated instruction"}
    update(author,changed)
    new=m.refresh("alpha")
    assert new.version_id!=old.version_id and new.provenance["commit"]==git(author,"rev-parse","HEAD")
    assert m.registry.active("beta").version_id==beta.version_id
    c.control(learner,"pinned","pause",expected_revision=0,operation="pause")
    resumed=c.control(learner,"pinned","resume",expected_revision=1,operation="resume")
    assert resumed["teacher"]==initial["teacher"]
    assert store.session(learner,"pinned")["source"]==snapshot["source"]
    assert store.session(learner,"pinned")["curriculum_snapshot"]==raw
    # Configuration and trusted checkout identity survive a new manager process.
    again=GitSources(Store(store.path.parent),m.policy)
    assert again.refresh("alpha").version_id==new.version_id


@pytest.mark.parametrize("failure",["unavailable","malformed","unsupported","same_item_revision"])
def test_failed_updates_leave_the_prior_validated_catalogue_usable(tmp_path,failure):
    author,upstream,raw=remote(tmp_path);store,m=manager(tmp_path,upstream)
    old=m.register(GitSourceSpec("alpha","Alpha",str(upstream)))
    if failure=="unavailable":upstream.rename(tmp_path/"offline.git")
    elif failure=="malformed":
        (author/"voice-teacher.json").write_text("{not json")
        git(author,"add","--",".");git(author,"commit","-qm","Invalid JSON");git(author,"push","-q","origin","main")
    else:
        raw["schema_version"]=2 if failure=="unsupported" else 1
        if failure=="same_item_revision":raw["courses"][0]["items"][0]["text"]["display"]="Changed meaning without a revision"
        update(author,raw)
    with pytest.raises(SourceError) as error:m.refresh("alpha")
    assert str(error.value)=="Git source refresh failed; the prior validated catalogue is retained"
    assert m.registry.active("alpha").version_id==old.version_id
    assert m.registry.active("alpha").curriculum==old.curriculum


def test_operator_git_configuration_endpoint_uses_the_explicit_manager(tmp_path):
    _,upstream,_=remote(tmp_path);store,m=manager(tmp_path,upstream)
    app=create_app(store,Coordinator(store,Judge()),operator_token=OPERATOR,origin=ORIGIN)
    # Trusted server composition only; no public request can set this dependency.
    app.state.git_sources=m
    client=TestClient(app,base_url=ORIGIN)
    response=client.put("/api/v1/operator/git-sources/alpha",headers={"Authorization":"Bearer "+OPERATOR},json={"name":"Alpha","remote":str(upstream)})
    assert response.status_code==200,response.text
    assert response.json()["source_id"]=="alpha" and response.json()["available"]
    assert str(tmp_path) not in response.text


def test_tags_subdirectories_and_repository_data_never_execute_hooks_or_scripts(tmp_path,monkeypatch):
    author,upstream,raw=remote(tmp_path,subdirectory="lessons")
    marker=tmp_path/"executed-marker"
    script="#!/bin/sh\ntouch '"+str(marker)+"'\n"
    (author/"bootstrap.sh").write_text(script);(author/"bootstrap.sh").chmod(0o700)
    (author/".gitattributes").write_text("* filter=untrusted\n")
    git(author,"add","--",".");git(author,"commit","-qm","Untrusted scripts are material, not commands");git(author,"push","-q","origin","main")
    git(author,"tag","v1");git(author,"push","-q","origin","refs/tags/v1")
    # Git explicitly ignores packObjectsHook in untrusted repository-local
    # configuration; protected globals are also excluded by our subprocess env.
    remote_hook=upstream/"hooks"/"untrusted-pack";remote_hook.parent.mkdir(exist_ok=True);remote_hook.write_text(script);remote_hook.chmod(0o700)
    git(upstream,"config","uploadpack.packObjectsHook",str(remote_hook))
    poisoned=tmp_path/"poisoned-home";poisoned.mkdir();global_hook=poisoned/"hook";global_hook.write_text(script);global_hook.chmod(0o700)
    (poisoned/".gitconfig").write_text('[core]\n hooksPath = '+str(poisoned)+'\n fsmonitor = '+str(global_hook)+'\n[filter "untrusted"]\n smudge = '+str(global_hook)+'\n required = true\n')
    monkeypatch.setenv("HOME",str(poisoned));monkeypatch.setenv("GIT_CONFIG_GLOBAL",str(poisoned/".gitconfig"))
    store,m=manager(tmp_path,upstream)
    spec=GitSourceSpec("alpha","Alpha",str(upstream),"tag","v1","lessons")
    first=m.register(spec)
    assert first.provenance["commit"]==git(author,"rev-parse","v1") and not marker.exists()
    checkout=Path(json.loads(m.registry._config("alpha"))["checkout"])
    hook=checkout/".git/hooks/post-checkout";hook.parent.mkdir(exist_ok=True);hook.write_text(script);hook.chmod(0o700)
    before=git(upstream,"for-each-ref","--format=%(refname) %(objectname)")
    assert m.refresh("alpha").version_id==first.version_id
    assert git(upstream,"for-each-ref","--format=%(refname) %(objectname)")==before
    assert not marker.exists()


@pytest.mark.parametrize("bad",["unlisted","relative","ssh","credentials","query","escape","git_metadata","option_ref","checkout_symlink","dirty","tampered_config"])
def test_policy_and_managed_checkout_changes_fail_without_exposing_or_overwriting_data(tmp_path,bad):
    author,upstream,raw=remote(tmp_path);store,m=manager(tmp_path,upstream)
    spec=GitSourceSpec("alpha","Alpha",str(upstream));old=m.register(spec)
    checkout=Path(json.loads(m.registry._config("alpha"))["checkout"])
    body=deepcopy(spec.__dict__)
    sentinel=None
    if bad=="unlisted":body["remote"]=str(tmp_path/"another.git")
    elif bad=="relative":body["remote"]="../relative.git"
    elif bad=="ssh":body["remote"]="git@example.invalid:source/repo.git"
    elif bad=="credentials":body["remote"]="https://user:synthetic-secret@example.invalid/repo.git"
    elif bad=="query":body["remote"]="https://example.invalid/repo.git?token=synthetic-secret"
    elif bad=="escape":body["subdirectory"]="../outside"
    elif bad=="git_metadata":body["manifest"]=".git/config"
    elif bad=="option_ref":body["ref_name"]="--upload-pack=evil"
    elif bad=="checkout_symlink":
        checkout.rename(checkout.with_name("retained"));checkout.symlink_to(checkout.with_name("retained"),target_is_directory=True)
    elif bad=="dirty":
        sentinel=checkout/"untracked-user-file";sentinel.write_text("must retain this unexpected local data")
    elif bad=="tampered_config":git(checkout,"config","core.hooksPath","/untrusted/path")
    with pytest.raises((SourceError,ValueError)):m.register(GitSourceSpec(**body))
    assert m.registry.active("alpha").version_id==old.version_id
    if sentinel is not None:assert sentinel.read_text()=="must retain this unexpected local data"


def test_operator_route_is_disabled_by_default_and_learner_cannot_clone_or_see_private_details(tmp_path):
    _,upstream,_=remote(tmp_path);store,m=manager(tmp_path,upstream)
    store.save_learner("learner",{})
    app=create_app(store,Coordinator(store,Judge()),operator_token=OPERATOR,origin=ORIGIN)
    client=TestClient(app,base_url=ORIGIN)
    body={"name":"Alpha","remote":str(upstream)};operator={"Authorization":"Bearer "+OPERATOR}
    assert client.put("/api/v1/operator/git-sources/alpha",headers=operator,json=body).status_code==503
    app.state.git_sources=m
    code=app.state.auth.issue_code("learner","synthetic")["code"]
    token=client.post("/api/v1/pair",json={"code":code}).json()["token"];learner={"Authorization":"Bearer "+token}
    assert client.put("/api/v1/operator/git-sources/alpha",json=body).status_code==401
    assert client.put("/api/v1/operator/git-sources/alpha",headers=learner,json=body).status_code==403
    assert client.put("/api/v1/operator/git-sources/alpha",headers=operator,json={**body,"credential_askpass":"/private/helper"}).status_code==422
    assert client.put("/api/v1/operator/git-sources/alpha",headers=operator,json=body).status_code==200
    upstream.rename(tmp_path/"offline.git")
    failed=client.post("/api/v1/operator/git-sources/alpha/refresh",headers=operator)
    assert failed.status_code==409 and str(tmp_path) not in failed.text and "offline.git" not in failed.text
    bad=client.put("/api/v1/operator/git-sources/alpha",headers=operator,json={**body,"remote":"https://user:synthetic-secret@example.invalid/repo.git"})
    assert bad.status_code==409 and "synthetic-secret" not in bad.text
    public=client.get("/api/v1/sources",headers=learner)
    assert public.status_code==200 and public.json()[0]["available"]
    assert not any(word in public.text for word in (str(tmp_path),"remote.git","checkout","credential","synthetic-secret"))


def test_source_policy_is_private_explicit_versioned_and_outside_repository_material(tmp_path):
    _,upstream,_=remote(tmp_path)
    path=tmp_path/"source-policy.json"
    value={"schema_version":1,"allowed_remotes":[str(upstream)],"allowed_local_roots":[str(tmp_path)]}
    path.write_text(canonical_json(value));path.chmod(0o600)
    policy=GitSourcePolicy.from_file(path);policy.validate()
    assert policy.allowed_remotes==(str(upstream),)
    path.chmod(0o644)
    with pytest.raises(SourceError):GitSourcePolicy.from_file(path)
    path.chmod(0o600)
    for bad in (0,2,True,"1"):
        path.write_text(canonical_json({**value,"schema_version":bad}))
        with pytest.raises(SourceError):GitSourcePolicy.from_file(path)
    path.write_text(canonical_json({**value,"inline_credential":"synthetic-secret"}))
    with pytest.raises(SourceError) as error:GitSourcePolicy.from_file(path)
    assert "synthetic-secret" not in str(error.value)
    path.write_text(canonical_json(value))
    with pytest.raises(SourceError):GitSourcePolicy.from_file(path,forbidden_roots=[tmp_path])


def test_credentials_cannot_be_supplied_by_a_source_and_dirty_ignored_files_remain(tmp_path):
    from dataclasses import replace
    author,upstream,raw=remote(tmp_path);store,m=manager(tmp_path,upstream)
    old=m.register(GitSourceSpec("alpha","Alpha",str(upstream)))
    evil=author/"askpass";evil.write_text("#!/bin/sh\nprintf synthetic-secret\n");evil.chmod(0o700)
    with pytest.raises(SourceError):GitSources(store,replace(m.policy,credential_askpass=str(evil)))
    checkout=Path(json.loads(m.registry._config("alpha"))["checkout"])
    helper=checkout/"askpass";helper.write_text(evil.read_text());helper.chmod(0o700)
    with pytest.raises(SourceError):GitSources(store,replace(m.policy,credential_askpass=str(helper)))
    # An ignored local file still must not be overwritten by a future checkout.
    ignore=checkout/".git/info/exclude";ignore.parent.mkdir(exist_ok=True);ignore.write_text("private-note\naskpass\n")
    note=checkout/"private-note";note.write_text("unexpected user data must remain")
    with pytest.raises(SourceError):m.refresh("alpha")
    assert note.read_text()=="unexpected user data must remain"
    assert m.registry.active("alpha").version_id==old.version_id


def test_cache_file_budget_refuses_an_oversized_update_without_losing_the_catalogue(tmp_path):
    import os
    author,upstream,raw=remote(tmp_path);store,m=manager(tmp_path,upstream,max_file_bytes=32768)
    old=m.register(GitSourceSpec("alpha","Alpha",str(upstream)))
    (author/"large-untrusted-file").write_bytes(os.urandom(65536))
    git(author,"add","--",".");git(author,"commit","-qm","Oversized source update");git(author,"push","-q","origin","main")
    with pytest.raises(SourceError):m.refresh("alpha")
    assert m.registry.active("alpha").version_id==old.version_id
    assert m.registry.active("alpha").curriculum==old.curriculum


def test_remote_symlink_manifest_is_refused_and_the_previous_snapshot_survives(tmp_path):
    author,upstream,raw=remote(tmp_path);store,m=manager(tmp_path,upstream)
    old=m.register(GitSourceSpec("alpha","Alpha",str(upstream)))
    manifest=author/"voice-teacher.json";manifest.rename(author/"other.json")
    manifest.symlink_to("other.json")
    git(author,"add","--",".");git(author,"commit","-qm","Symlink manifest");git(author,"push","-q","origin","main")
    with pytest.raises(SourceError):m.refresh("alpha")
    assert m.registry.active("alpha").version_id==old.version_id


def test_production_composition_loads_policy_without_fetching_or_calling_providers(tmp_path,monkeypatch):
    from voice_teacher.__main__ import build_app
    _,upstream,_=remote(tmp_path)
    policy=tmp_path/"policy.json"
    policy.write_text(canonical_json({"schema_version":1,"allowed_remotes":[str(upstream)],"allowed_local_roots":[str(tmp_path)]}));policy.chmod(0o600)
    def no_git(*args,**kwargs):raise AssertionError("Startup must not fetch")
    monkeypatch.setattr(GitSources,"_git",no_git)
    app=build_app(tmp_path/"runtime",operator_token=OPERATOR,speech_key="synthetic",judge_key="synthetic",judge_model="synthetic/model",origin=ORIGIN,git_source_policy=policy)
    assert isinstance(app.state.git_sources,GitSources)
    assert TestClient(app,base_url=ORIGIN).get("/healthz").json()=={"status":"ok"}
    assert app.state.git_sources.registry.list_sources()==[]
