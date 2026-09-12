#!/usr/bin/env python3
"""USB SSH access using OpenSSH and libimobiledevice; no Python dependencies."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'


def receiver_token(config):
    """Separate tokens per iPad; retain the original pairing's legacy token."""
    return RUNTIME / config.get('token_file', 'receiver-token')


def save_device(config):
    profiles_path = RUNTIME / 'devices.json'
    profiles = json.loads(profiles_path.read_text()) if profiles_path.exists() else {}
    active = RUNTIME / 'device.json'
    if active.exists():
        previous = json.loads(active.read_text())
        profiles[previous['udid']] = previous
    profiles[config['udid']] = config
    for path, value in ((profiles_path, profiles), (active, config)):
        path.write_text(json.dumps(value, indent=2) + '\n')
        path.chmod(0o600)


def password(path):
    """Read a literal PASSWORD value without executing shell/.env content."""
    for line in Path(path).read_text().splitlines():
        key, sep, value = line.strip().partition('=')
        if sep and key.strip() in ('PASSWORD', 'export PASSWORD'):
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value:
                return value
    raise ValueError('No nonempty PASSWORD in the supplied .env file')


def ssh_args(config, batch=True):
    udid = config['udid']
    if not re.fullmatch(r'[A-Fa-f0-9-]+', udid):
        raise ValueError('Invalid device ID')
    return ['ssh', '-F', '/dev/null', '-i', config['key'],
            '-o', 'IdentitiesOnly=yes', '-o', 'ConnectTimeout=8',
            '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
            '-o', 'StrictHostKeyChecking=accept-new',
            '-o', f'UserKnownHostsFile={RUNTIME / "known_hosts"}',
            '-o', f'HostKeyAlias=ipad-{udid}',
            '-o', 'ProxyCommand=' + shlex.join([sys.executable, str(ROOT / 'scripts/usbmux_proxy.py'), '--udid', udid]),
            '-o', f'BatchMode={"yes" if batch else "no"}']


def main():
    # OpenSSH calls this executable as SSH_ASKPASS. Its stdout goes only to SSH.
    if os.environ.get('IPAD_SCREEN_ASKPASS') == '1':
        print(password(os.environ['IPAD_SCREEN_PASSWORD_FILE']))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('devices')
    pair = sub.add_parser('pair')
    pair.add_argument('--udid', required=True)
    pair.add_argument('--key', default='~/.ssh/id_ed25519')
    pair.add_argument('--env-file', default=str(ROOT.parent / '.env'))
    pair.add_argument('--model', choices=['pro105', 'pro97', 'ipad9'], required=True)
    select = sub.add_parser('select', help='Use a previously paired device')
    select.add_argument('--udid', required=True)
    ssh = sub.add_parser('ssh')
    ssh.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == 'devices':
        subprocess.run(['idevice_id', '-l'], check=True)
        return
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    config_path = RUNTIME / 'device.json'
    if args.action == 'select':
        profiles = json.loads((RUNTIME / 'devices.json').read_text())
        if args.udid not in profiles:
            raise ValueError('Device has not been paired on this host')
        save_device(profiles[args.udid])
        print('Selected saved iPad pairing.')
        return
    if args.action == 'pair':
        key = Path(args.key).expanduser().resolve()
        public_key = Path(str(key) + '.pub').read_text().strip()
        if '\n' in public_key or not public_key.startswith(('ssh-ed25519 ', 'ssh-rsa ', 'ecdsa-sha2-')):
            raise ValueError('Expected one OpenSSH public key')
        if not re.fullmatch(r'[A-Fa-f0-9-]+', args.udid):
            raise ValueError('Invalid device ID')
        profiles_path = RUNTIME / 'devices.json'
        profiles = json.loads(profiles_path.read_text()) if profiles_path.exists() else {}
        if config_path.exists():
            previous = json.loads(config_path.read_text())
            profiles[previous['udid']] = previous
        config = dict(profiles.get(args.udid, {}), udid=args.udid,
                      key=str(key), model=args.model)
        if args.udid not in profiles:
            config['token_file'] = f'receiver-token-{args.udid}'
        env = dict(os.environ, SSH_ASKPASS=str(Path(__file__).resolve()),
                   SSH_ASKPASS_REQUIRE='force', DISPLAY='ipad-screen:0',
                   IPAD_SCREEN_ASKPASS='1',
                   IPAD_SCREEN_PASSWORD_FILE=str(Path(args.env_file).resolve()))
        password(env['IPAD_SCREEN_PASSWORD_FILE'])  # Validate without printing.
        # Append only when absent, preserving all existing authorized keys.
        remote = ('set -eu; umask 077; mkdir -p "$HOME/.ssh"; '
                  'chmod 700 "$HOME/.ssh"; touch "$HOME/.ssh/authorized_keys"; '
                  'chmod 600 "$HOME/.ssh/authorized_keys"; '
                  f'key={shlex.quote(public_key)}; '
                  'grep -qxF "$key" "$HOME/.ssh/authorized_keys" || '
                  'printf "%s\\n" "$key" >> "$HOME/.ssh/authorized_keys"')
        subprocess.run(ssh_args(config, batch=False) +
                       ['-o', 'NumberOfPasswordPrompts=1', 'mobile@ipad-usb', remote],
                       env=env, stdin=subprocess.DEVNULL, check=True, timeout=30)
        subprocess.run(ssh_args(config) + ['mobile@ipad-usb', 'id -un'],
                       stdin=subprocess.DEVNULL, check=True, timeout=20)
        save_device(config)
        print('Public key installed; passwordless USB SSH verified.')
    else:
        config = json.loads(config_path.read_text())
        # OpenSSH interprets its command via the remote shell; pass one literal
        # command string for shell syntax, or separately quoted argv otherwise.
        command = args.command
        if len(command) > 1:
            command = [shlex.join(command)]
        subprocess.run(ssh_args(config) + ['mobile@ipad-usb'] + command, check=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f'ipad-screen: {exc}', file=sys.stderr)
        sys.exit(1)
