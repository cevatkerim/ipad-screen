#!/usr/bin/env python3
"""Install and verify the native companion for the active paired USB iPad."""
import argparse
import fcntl
import io
import json
import secrets
import subprocess
import sys
import tarfile
import time

from ipad import ROOT, RUNTIME, password, receiver_token, save_device, ssh_args

MOBILE_APP = '/var/mobile/Applications/iPadScreen.app'
JAILBREAK_APP = '/var/jb/Applications/iPadScreen.app'
STATUS = '/var/mobile/Library/Caches/ipad-screen-status.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--location', choices=['auto', 'mobile', 'jailbreak'], default='auto',
                        help='Auto uses the jailbreak app directory on Dopamine')
    parser.add_argument('--env-file', default=str(ROOT.parent / '.env'),
                        help='Mobile sudo password, used only for the jailbreak app directory')
    args = parser.parse_args()
    config = json.loads((RUNTIME / 'device.json').read_text())
    app = ROOT / 'build/iPadScreen.app'
    if not (app / 'iPadScreen').is_file():
        raise ValueError('Run ./scripts/build-app first')
    with (RUNTIME / 'screen.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Stop the display session before installing the companion')

        def remote(command, **kwargs):
            return subprocess.run(ssh_args(config) + ['mobile@ipad-usb', command],
                                  timeout=60, **kwargs)

        location = args.location
        if location == 'auto':
            detection = remote('test -x /var/jb/basebin/jbctl')
            if detection.returncode not in (0, 1):
                raise RuntimeError('Could not detect the jailbreak installation layout')
            location = 'jailbreak' if detection.returncode == 0 else 'mobile'
        sudo_input = None
        if location == 'jailbreak':
            # Validate before interrupting or copying the app. The password
            # travels through SSH stdin, never argv or the remote environment.
            sudo_input = (password(args.env_file) + '\n').encode()
            remote("/var/jb/usr/bin/sudo -S -p '' -v", input=sudo_input, check=True)

        token_path = receiver_token(config)
        if not token_path.exists():
            token_path.write_text(secrets.token_hex(32) + '\n')
            token_path.chmod(0o600)
        remote('umask 077; cat > /var/mobile/Library/Preferences/ipad-screen-token',
               input=token_path.read_bytes(), check=True)
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode='w') as archive:
            archive.add(app, arcname='iPadScreen.app')
        remote('set -eu; killall iPadScreen 2>/dev/null || true; '
               f'rm -f {STATUS}; mkdir -p /var/mobile/Applications; '
               'tar -xf - -C /var/mobile/Applications; '
               f'chmod 755 {MOBILE_APP}/iPadScreen',
               input=payload.getvalue(), check=True)
        destination = MOBILE_APP
        if location == 'jailbreak':
            destination = JAILBREAK_APP
            remote("/var/jb/usr/bin/sudo -S -p '' /var/jb/bin/sh -c "
                   f"'set -eu; mkdir -p {JAILBREAK_APP}; "
                   f"cp -R {MOBILE_APP}/. {JAILBREAK_APP}/; "
                   f"chown -R root:wheel {JAILBREAK_APP}; "
                   f"chmod 755 {JAILBREAK_APP}/iPadScreen'",
                   input=sudo_input, check=True)
            registered = remote('/var/jb/usr/bin/uicache -i me.kerim.ipad-screen',
                                capture_output=True)
            paths = registered.stdout.decode(errors='replace').splitlines()
            if any(line in (f'Path: {MOBILE_APP}', f'Path: /private{MOBILE_APP}') for line in paths):
                remote(f'/var/jb/usr/bin/uicache -u {MOBILE_APP}', check=True)
        remote(f'set -eu; /var/jb/usr/bin/uicache -p {destination}; '
               '/var/jb/usr/bin/uiopen --bundleid me.kerim.ipad-screen', check=True)
        config['app_location'] = location
        save_device(config)
        for attempt in range(10):
            result = remote(f'cat {STATUS}', capture_output=True)
            if result.returncode == 0:
                status = json.loads(result.stdout)
                if status.get('state') == 'listening':
                    print(f'Installed at {destination}; companion USB listener verified.')
                    return
            time.sleep(0.5)
        raise RuntimeError('App did not reach its listening state. Unlock it and open '
                           'iPad Screen; see docs/another-ipad.md for launch diagnostics.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'ipad-screen: {exc}', file=sys.stderr)
        sys.exit(1)
