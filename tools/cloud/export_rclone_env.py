#!/usr/bin/env python3
"""Export a selected local Drive login for Claude, without printing credentials.
Run this in your own terminal after local login succeeds. Output is a private
.env input for Claude environment settings, NOT a shell script or Drive upload.
"""
import argparse
import configparser
import json
import os
from pathlib import Path
import subprocess
import tempfile


def selected_values(text,remote):
    config=configparser.ConfigParser(interpolation=None)
    config.read_string(text)
    if remote not in config or config[remote].get('type')!='drive':
        raise ValueError('Select a configured Google Drive remote')
    settings=config[remote]
    try:
        token=json.loads(settings.get('token',''))
        if not token.get('refresh_token'):raise ValueError()
    except (ValueError,AttributeError):
        raise ValueError('Complete the browser login first; this remote has no refresh token') from None
    values={'VOICE_TEACHER_RCLONE_TOKEN':json.dumps(token,separators=(',',':'))}
    for key in ['client_id','client_secret']:
        if settings.get(key):values['RCLONE_DRIVE_'+key.upper()]=settings[key]
    if not all(key in values for key in ('RCLONE_DRIVE_CLIENT_ID','RCLONE_DRIVE_CLIENT_SECRET')):
        raise ValueError('Configure your own OAuth client ID and secret before exporting')
    return values


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remote',default='voiceteacherdrive')
    args=parser.parse_args()
    try:
        text=subprocess.check_output(['rclone','config','show',args.remote],text=True,stderr=subprocess.DEVNULL)
        values=selected_values(text,args.remote)
        # Only this local export contains secrets; no stdout, repo or argv values.
        fd,name=tempfile.mkstemp(prefix='voice-teacher-claude-',suffix='.env')
        with os.fdopen(fd,'w') as stream:
            for key,value in values.items():
                # dotenv quoted strings preserve the inner OAuth JSON quotation.
                stream.write(key+'='+json.dumps(value)+'\n')
        print('Private Claude environment values saved to:',name)
        print('Paste these values into Claude environment settings locally, then delete this temporary file. Do not upload it or paste it into chat.')
    except (ValueError,subprocess.CalledProcessError) as error:
        raise SystemExit(str(error) if isinstance(error,ValueError) else 'Could not read the selected rclone remote') from None
