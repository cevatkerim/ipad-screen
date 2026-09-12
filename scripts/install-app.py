#!/usr/bin/env python3
"""Install the built jailbreak companion for the currently paired USB iPad."""
import io
import json
import secrets
import subprocess
import tarfile

from ipad import ROOT, RUNTIME, ssh_args

config = json.loads((RUNTIME / 'device.json').read_text())
app = ROOT / 'build/iPadScreen.app'
if not (app / 'iPadScreen').is_file():
    raise SystemExit('Run ./scripts/build-app first')
token_path = RUNTIME / 'receiver-token'
if not token_path.exists():
    token_path.write_text(secrets.token_hex(32) + '\n')
    token_path.chmod(0o600)
subprocess.run(ssh_args(config) + ['mobile@ipad-usb',
    'umask 077; cat > /var/mobile/Library/Preferences/ipad-screen-token'],
    input=token_path.read_bytes(), check=True)
payload = io.BytesIO()
with tarfile.open(fileobj=payload, mode='w') as archive:
    archive.add(app, arcname='iPadScreen.app')
subprocess.run(ssh_args(config) + ['mobile@ipad-usb',
    'set -eu; killall iPadScreen 2>/dev/null || true; mkdir -p /var/mobile/Applications; '
    'tar -xf - -C /var/mobile/Applications; '
    'chmod 755 /var/mobile/Applications/iPadScreen.app/iPadScreen; '
    '/var/jb/usr/bin/uicache -p /var/mobile/Applications/iPadScreen.app; '
    '/var/jb/usr/bin/uicache -i me.kerim.ipad-screen; '
    '/var/jb/usr/bin/uiopen --bundleid me.kerim.ipad-screen'],
    input=payload.getvalue(), check=True, timeout=60)
print('Installed and requested launch of iPad Screen. Verify its status before streaming.')
