#!/usr/bin/env python3
"""Experimental lossless USB screen viewer for Hyprland and jailbroken iPads."""
import argparse
import fcntl
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
import shlex
import signal
import subprocess
import time

from ipad import ROOT, RUNTIME, ssh_args


def hypr(*args):
    result = subprocess.run(['hyprctl', *args], capture_output=True, text=True, check=True)
    if any(word in result.stdout.lower() for word in ('error', 'invalid', 'not enough', 'no backend')):
        raise RuntimeError(result.stdout.strip())
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['extend', 'mirror'], default='extend')
    parser.add_argument('--model', choices=['pro105', 'ipad9'], default='pro105')
    parser.add_argument('--output', help='Existing monitor to mirror; defaults to the focused monitor')
    parser.add_argument('--seconds', type=int, default=0, help='Stop automatically after N seconds (0: until Ctrl+C)')
    args = parser.parse_args()
    config = json.loads((RUNTIME / 'device.json').read_text())
    lock = (RUNTIME / 'screen.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Another screen session is already running')
    monitors = json.loads(hypr('monitors', '-j'))
    name = 'ipad-screen'
    created = False
    tunnel = None
    server = None
    reports = []
    captured = 0
    sent_bytes = 0
    started = time.monotonic()
    token = '/' + secrets.token_urlsafe(24)
    page = (ROOT / 'web/viewer.html').read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *unused):
            pass

        def send(self, payload, content_type, code=200):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            nonlocal captured, sent_bytes
            try:
                if self.path in (token, token + '/'):
                    self.send(page, 'text/html; charset=utf-8')
                elif self.path == token + '/frame':
                    frame = subprocess.run(['grim', '-c', '-o', name, '-s', str(scale), '-t', 'png', '-l', '1', '-'],
                                           capture_output=True, check=True, timeout=5).stdout
                    self.send(frame, 'image/png')
                    captured += 1
                    sent_bytes += len(frame)
                else:
                    self.send(b'Not found', 'text/plain', 404)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            except subprocess.SubprocessError as exc:
                print(f'Capture failed: {exc}', flush=True)
                self.send(b'Capture failed', 'text/plain', 503)

        def do_POST(self):
            if self.path != token + '/report':
                self.send(b'Not found', 'text/plain', 404)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise ValueError('Bad report length')
                report = json.loads(self.rfile.read(length))
                if not isinstance(report, dict):
                    raise ValueError('Expected an object')
                reports.append(report)
                reports[:] = reports[-30:]
                if len(reports) == 1:
                    print('iPad confirmed decoded frame: ' + json.dumps(report), flush=True)
                self.send(b'OK', 'text/plain')
            except (ValueError, TimeoutError):
                self.send(b'Invalid report', 'text/plain', 400)

    def stop(*unused):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        if args.mode == 'extend':
            if any(m['name'] == name for m in monitors):
                raise RuntimeError('ipad-screen output already exists; inspect it before starting')
            width, height = (2224, 1668) if args.model == 'pro105' else (2160, 1620)
            scale = 2
            right = max(m['x'] + round(m['width'] / m['scale']) for m in monitors)
            hypr('output', 'create', 'headless', name)
            created = True
            hypr('eval', f'hl.monitor({{output="{name}",mode="{width}x{height}@30",position="{right}x0",scale=2}})')
            actual = next(m for m in json.loads(hypr('monitors', '-j')) if m['name'] == name)
            if (actual['width'], actual['height'], actual['scale']) != (width, height, scale):
                raise RuntimeError('Virtual monitor did not take the requested resolution')
        else:
            selected = next((m for m in monitors if m['name'] == args.output), None) if args.output else next((m for m in monitors if m.get('focused')), monitors[0])
            if selected is None:
                raise RuntimeError('Requested monitor is not active')
            name, scale = selected['name'], selected['scale']
        server = HTTPServer(('127.0.0.1', 0), Handler)
        server.timeout = 0.5
        local_port = server.server_address[1]
        remote_port = 18765
        url = f'http://127.0.0.1:{remote_port}{token}'
        # Keep stdin open so cat anchors the session and exits on disconnect.
        remote = f'/var/jb/usr/bin/uiopen --url {shlex.quote(url)}; exec cat'
        tunnel = subprocess.Popen(ssh_args(config) + ['-o', 'ExitOnForwardFailure=yes',
            '-R', f'127.0.0.1:{remote_port}:127.0.0.1:{local_port}', 'mobile@ipad-usb', remote],
            stdin=subprocess.PIPE)
        print(f'{args.mode}: {name}; opening Safari over USB. Ctrl+C stops and removes the temporary output.', flush=True)
        while not args.seconds or time.monotonic() - started < args.seconds:
            if tunnel.poll() is not None:
                raise RuntimeError(f'USB SSH tunnel exited ({tunnel.returncode})')
            server.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        if tunnel is not None:
            tunnel.stdin.close()
            tunnel.terminate()
            try:
                tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill()
                tunnel.wait()
        if server is not None:
            server.server_close()
        if created:
            hypr('output', 'remove', 'ipad-screen')
        result = dict(mode=args.mode, output=name, captured_frames=captured, sent_bytes=sent_bytes,
                      duration_seconds=round(time.monotonic()-started, 2), reports=reports)
        (RUNTIME / 'last-session.json').write_text(json.dumps(result, indent=2) + '\n')
        print(f'Stopped. Sent {captured} frames; received {len(reports)} browser reports.', flush=True)


if __name__ == '__main__':
    main()
