"""Supplemental agy provider egress; the existing MiniMax policy is unchanged."""
import os
import sys
import threading
import time
import egress

# Observed installed CLI endpoint; OAuth refresh, account userinfo and the eligibility profile image are required.
egress.ALLOWED = {'daily-cloudcode-pa.googleapis.com:443', 'oauth2.googleapis.com:443', 'www.googleapis.com:443', 'lh3.googleusercontent.com:443'}

if __name__ == '__main__':
    os.umask(0o077)
    parent = os.getppid()

    def parent_watch():
        while os.getppid() == parent:
            time.sleep(1)
        os._exit(0)  # parent disappeared; do not leave an orphan network broker

    threading.Thread(target=parent_watch, daemon=True).start()
    with egress.Server(sys.argv[1], egress.Tunnel) as server:
        print('agy provider broker ready', flush=True)
        server.serve_forever()
