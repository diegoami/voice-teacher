"""Exercise transfer/publication boundaries without network or credentials."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('artifacts',Path(__file__).resolve().parents[2]/'tools/artifacts.py')
artifacts=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifacts)


class ArtifactBoundaries(unittest.TestCase):
    def test_download_rejects_traversal_remote_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'private').mkdir();(root/'outside').mkdir()
            (root/'private/escape').symlink_to(root/'outside',target_is_directory=True)
            with patch.object(artifacts,'ROOT',root):
                for value in ('../secret','/etc/passwd','other:secret','escape/file','a/../file','a\\file'):
                    with self.subTest(value=value), self.assertRaises(ValueError):
                        artifacts.private_path(value,{'localDir':'private'})
                self.assertEqual(artifacts.private_path('batch/input.json',{'localDir':'private'}),root/'private/batch/input.json')

    def test_oauth_uses_environment_and_pinned_folder_not_local_remote(self):
        cfg={'drive':{'folderId':'project-only'}}
        token=json.dumps({'refresh_token':'synthetic-not-a-credential'})
        with patch.dict(os.environ,{'VOICE_TEACHER_RCLONE_TOKEN':token,
                                    'RCLONE_CONFIG_VOICETEACHERDRIVE_ROOT_FOLDER_ID':'wrong-folder'},clear=True):
            env=artifacts.drive_env(cfg)
        self.assertEqual(env['RCLONE_CONFIG'],os.devnull)
        self.assertEqual(env['RCLONE_CONFIG_VOICETEACHERDRIVE_ROOT_FOLDER_ID'],'project-only')
        self.assertEqual(env['RCLONE_CONFIG_VOICETEACHERDRIVE_TOKEN'],token)
        with patch.dict(os.environ,{'VOICE_TEACHER_RCLONE_TOKEN':'{"access_token":"incomplete"}'},clear=True):
            with self.assertRaises(ValueError):artifacts.drive_env(cfg)

    def test_release_refuses_private_files_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'artifacts/private').mkdir(parents=True)
            file=root/'artifacts/private/report.txt';file.write_text('private fixture')
            with patch.object(artifacts,'ROOT',root), patch.object(artifacts.subprocess,'check_output') as api:
                with self.assertRaises(ValueError):artifacts.release('candidate',[str(file)])
                api.assert_not_called()

    def test_release_refuses_existing_asset_and_never_creates_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'artifacts/public').mkdir(parents=True)
            file=root/'artifacts/public/report.md';file.write_text('synthetic review')
            data={'id':42,'assets':[{'name':'report.md'}],'html_url':'https://example.invalid/release'}
            with patch.object(artifacts,'ROOT',root),patch.object(artifacts.subprocess,'check_output',return_value=json.dumps(data)) as get,patch.object(artifacts.subprocess,'run') as post:
                with self.assertRaises(ValueError):artifacts.release('candidate',[str(file)])
                self.assertIn('/releases/tags/candidate',get.call_args.args[0][-1])
                post.assert_not_called()

    def test_release_uses_exact_upload_url_and_rest_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'artifacts/public').mkdir(parents=True)
            file=root/'artifacts/public/review one.md';file.write_text('synthetic review')
            data={'id':42,'assets':[],'html_url':'https://example.invalid/release'}
            with patch.object(artifacts,'ROOT',root),patch.object(artifacts.subprocess,'check_output',return_value=json.dumps(data)),patch.object(artifacts.subprocess,'run') as post:
                artifacts.release('candidate',[str(file)])
            command=post.call_args.args[0]
            self.assertEqual(command[:4],['gh','api','--method','POST'])
            self.assertEqual(command[4],'https://uploads.github.com/repos/diegoami/voice-teacher/releases/42/assets?name=review%20one.md')
            self.assertNotIn('--hostname',command)
            self.assertEqual(command[-2:],['--input',str(file)])

    def test_private_pull_is_immutable_and_checks_hash(self):
        import sys
        previous=os.umask(0o022)
        self.addCleanup(os.umask,previous)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            cfg={'localDir':'.cache/private','drive':{'folderId':'project'},'files':{'sample.txt':{'sha256':'0'*64}}}
            (root/'artifacts.json').write_text(json.dumps(cfg))
            calls=[]
            def copy(command,**kwargs):
                calls.append(command)
                Path(command[-1]).write_text('mismatched synthetic sample')
            with patch.object(artifacts,'ROOT',root),patch.object(sys,'argv',['artifacts.py','pull','sample.txt']),patch.object(artifacts.shutil,'which',return_value='/rclone'),patch.object(artifacts,'drive_env',return_value={}),patch.object(artifacts.subprocess,'run',side_effect=copy):
                with self.assertRaises(ValueError):artifacts.main()
            actual=os.umask(0o022)
            self.assertEqual(actual,0o022, 'Failed transfers must restore the caller umask')
            self.assertEqual(calls[0][0:3],['rclone','copyto','--immutable'])
            self.assertEqual(calls[0][3],'voiceteacherdrive:sample.txt')


if __name__=='__main__':unittest.main()
