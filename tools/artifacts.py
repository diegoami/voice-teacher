#!/usr/bin/env python3
"""Private files: where, pull NAME..., push FILE...; synthetic release assets:
release TAG FILE... (existing release only, files in artifacts/public/).
Requires rclone only for Drive operations; never stores OAuth tokens in files/argv.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def relative_name(value):
    name = PurePosixPath(value)
    if not value or value.startswith('/') or '\\' in value or any(p in {'..', '.'} for p in value.split('/')) or ':' in value:
        raise ValueError('Use a relative artifact name without traversal or a remote prefix')
    return str(name)


def private_path(name, cfg):
    base = (ROOT / cfg['localDir']).resolve()
    dest = base / relative_name(name)
    if not dest.resolve().is_relative_to(base):
        raise ValueError('Artifact path escapes private storage through a symlink')
    return dest


def drive_env(cfg):
    # A private empty config prevents accidentally adopting a machine's remote.
    # Environment remote credentials do not appear in process arguments or logs.
    env = dict(os.environ)
    env['RCLONE_CONFIG'] = os.devnull
    prefix = 'RCLONE_CONFIG_VOICETEACHERDRIVE_'
    for key in list(env):
        if key.startswith(prefix): del env[key]
    token = env.get('VOICE_TEACHER_RCLONE_TOKEN', '')
    try:
        if not json.loads(token).get('refresh_token'): raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Set VOICE_TEACHER_RCLONE_TOKEN to the complete OAuth token JSON with refresh_token') from None
    env[prefix+'TYPE'] = 'drive'
    env[prefix+'TOKEN'] = token
    env[prefix+'ROOT_FOLDER_ID'] = cfg['drive']['folderId']
    for key in ('CLIENT_ID', 'CLIENT_SECRET'):
        if env.get('RCLONE_DRIVE_'+key): env[prefix+key] = env['RCLONE_DRIVE_'+key]
    return env


def release(tag, names):
    # Never create/publish a release as a side effect of uploading evidence.
    files=[]
    base=(ROOT/'artifacts/public').resolve()
    for name in names:
        file=Path(name).resolve()
        if not file.is_relative_to(base) or not file.is_file():
            raise ValueError('Release uploads must be existing files under artifacts/public/')
        if file.suffix.lower() in {'.db','.sqlite','.wav','.mp3','.m4a','.webm','.env','.key'}:
            raise ValueError('Private audio, databases and credentials cannot be release assets')
        files.append(file)
    if len({f.name for f in files}) != len(files):
        raise ValueError('Release asset names must be unique')
    data=json.loads(subprocess.check_output(['gh','api',f'repos/diegoami/voice-teacher/releases/tags/{quote(tag,safe="")}'],text=True))
    existing={a['name'] for a in data['assets']}
    if any(f.name in existing for f in files):
        raise ValueError('An asset already exists; preserve it and use a new name')
    for file in files:
        subprocess.run(['gh','api','--hostname','uploads.github.com','--method','POST',
                        f'/repos/diegoami/voice-teacher/releases/{data["id"]}/assets?name={quote(file.name,safe="")}',
                        '-H','Content-Type: application/octet-stream','--input',str(file)],check=True,stdout=subprocess.DEVNULL)
    print(f'Uploaded {len(files)} assets to {data["html_url"]}')


@contextmanager
def private_umask():
    previous=os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['where','pull','push','release'])
    parser.add_argument('names',nargs='*')
    args=parser.parse_args()
    cfg=json.loads((ROOT/'artifacts.json').read_text())
    if args.command=='where':
        print(cfg['drive']['folderUrl']);print('Local private downloads:',cfg['localDir']);return
    if not args.names: raise ValueError('Specify at least one file (release needs TAG FILE...)')
    if args.command=='release':
        if len(args.names)<2: raise ValueError('release needs TAG FILE...')
        release(args.names[0],args.names[1:]);return
    if not shutil.which('rclone'): raise ValueError('Install rclone for Drive transfers, or use the Drive connector/UI')
    env=drive_env(cfg)
    remote='voiceteacherdrive:'
    with private_umask():
        for name in args.names:
            if args.command=='pull':
                name=relative_name(name);dest=private_path(name,cfg);dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                subprocess.run(['rclone','copyto','--immutable',remote+name,str(dest)],env=env,check=True)
                expected=cfg.get('files',{}).get(name,{}).get('sha256')
                if expected:
                    with dest.open('rb') as stream:
                        actual=hashlib.file_digest(stream,'sha256').hexdigest()
                    if actual!=expected:
                        raise ValueError('Downloaded artifact hash mismatch; do not use this file')
            else:
                src=Path(name).resolve()
                allowed=[(ROOT/p).resolve() for p in (cfg['localDir'],'artifacts/private')]
                if not src.is_file() or not any(src.is_relative_to(base) for base in allowed):
                    raise ValueError('Drive uploads must be files under .cache/private/ or artifacts/private/')
                subprocess.run(['rclone','copyto','--immutable',str(src),remote+src.name],env=env,check=True)
    print('Transfer completed; originals were preserved.')


if __name__=='__main__':
    try: main()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except subprocess.CalledProcessError:
        # Do not dump process arguments or credentials on remote-operation failure.
        raise SystemExit('Artifact operation failed. Check network/access and docs/artifacts.md.') from None
