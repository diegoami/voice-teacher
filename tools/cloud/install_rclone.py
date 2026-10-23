#!/usr/bin/env python3
"""Install pinned rclone in a checkout-owned tools directory; no root or login."""
import hashlib
import os
from pathlib import Path
import platform
import shutil
import tempfile
import urllib.request
import zipfile

VERSION='v1.75.2'
ROOT=Path(__file__).resolve().parents[2]


def install(destination):
    target=destination/'rclone'
    if target.is_file():
        return target
    arch={'x86_64':'amd64','aarch64':'arm64'}.get(platform.machine())
    if platform.system()!='Linux' or arch is None:
        raise SystemExit('Automatic rclone install supports Linux amd64/arm64; install rclone manually elsewhere.')
    name=f'rclone-{VERSION}-linux-{arch}'
    base=f'https://github.com/rclone/rclone/releases/download/{VERSION}/'
    destination.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rclone-install-') as directory:
        archive=Path(directory)/(name+'.zip')
        with urllib.request.urlopen(base+archive.name,timeout=60) as response, archive.open('wb') as stream:
            shutil.copyfileobj(response,stream)
        with urllib.request.urlopen(base+'SHA256SUMS',timeout=60) as response:
            lines=response.read(1024*1024).decode().splitlines()
        matches=[line.split()[0] for line in lines if line.split() and line.split()[-1].lstrip('*')==archive.name]
        with archive.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if len(matches)!=1 or actual!=matches[0]:
            raise SystemExit('rclone archive checksum verification failed')
        # Read exactly the executable; never extract arbitrary ZIP paths.
        with zipfile.ZipFile(archive) as bundle:
            binary=bundle.read(name+'/rclone')
        fd,staged=tempfile.mkstemp(prefix='.rclone-',dir=destination)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(binary)
            os.chmod(staged,0o700)
            os.replace(staged,target)
        finally:
            if Path(staged).exists():Path(staged).unlink()
    return target


if __name__=='__main__':
    existing=shutil.which('rclone')
    if existing:print('rclone already installed:',existing)
    else:print('rclone installed:',install(ROOT/'.cache/tools/bin'))
