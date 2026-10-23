"""Synthetic credentials and installer downloads only; no Google login."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]


def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/f'tools/cloud/{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class RcloneSetupTest(unittest.TestCase):
    def test_export_selects_only_chosen_remote_and_requires_full_login(self):
        export=load('export_rclone_env')
        fixture='[voice]\ntype=drive\nclient_id=synthetic-id\nclient_secret=synthetic-secret\ntoken={"refresh_token":"synthetic-refresh"}\n[other]\nsecret=do-not-export\n'
        values=export.selected_values(fixture,'voice')
        self.assertEqual(set(values),{'VOICE_TEACHER_RCLONE_TOKEN','RCLONE_DRIVE_CLIENT_ID','RCLONE_DRIVE_CLIENT_SECRET'})
        self.assertNotIn('do-not-export',json.dumps(values))
        with self.assertRaises(ValueError):export.selected_values('[voice]\ntype=drive\n','voice')

    def test_export_accepts_shared_client_but_refuses_incomplete_custom_client(self):
        export=load('export_rclone_env')
        shared='[voice]\ntype=drive\ntoken={"refresh_token":"synthetic-refresh"}\n'
        self.assertEqual(set(export.selected_values(shared,'voice')),{'VOICE_TEACHER_RCLONE_TOKEN'})
        with self.assertRaises(ValueError):
            export.selected_values(shared+'client_id=synthetic-id\n','voice')

    def test_failed_checksum_never_installs_binary(self):
        installer=load('install_rclone')
        body=io.BytesIO()
        name=f'rclone-{installer.VERSION}-linux-amd64'
        with zipfile.ZipFile(body,'w') as archive:archive.writestr(name+'/rclone',b'synthetic binary')
        content=body.getvalue()
        def download(url,**kwargs):
            return io.BytesIO(content if url.endswith('.zip') else f'{"0"*64}  {name}.zip\n'.encode())
        with tempfile.TemporaryDirectory() as directory,patch.object(installer.platform,'system',return_value='Linux'),patch.object(installer.platform,'machine',return_value='x86_64'),patch.object(installer.urllib.request,'urlopen',side_effect=download):
            target=Path(directory)/'bin'
            with self.assertRaises(SystemExit):installer.install(target)
            self.assertFalse((target/'rclone').exists())


if __name__=='__main__':unittest.main()
