#!/usr/bin/env python3
"""Stream continuous H.264 over USB to the native iPad Screen companion."""
import argparse
import fcntl
import json
import os
import re
import signal
import struct
import subprocess
import time

from ipad import RUNTIME, ssh_args
from screen import hypr
from usbmux_proxy import connect, read_exact

START_CODE = re.compile(b'\x00\x00(?:\x00)?\x01')
MAX_FRAME = 8 * 1024 * 1024


def nal_units(stream):
    pending = bytearray()
    while chunk := stream.read(65536):
        pending.extend(chunk)
        matches = list(START_CODE.finditer(pending))
        for left, right in zip(matches, matches[1:]):
            yield bytes(pending[left.end():right.start()])
        if matches:
            del pending[:matches[-1].start()]
        if len(pending) > MAX_FRAME:
            raise ValueError('Encoded NAL exceeds protocol limit')
    match = START_CODE.match(pending)
    if match and len(pending) > match.end():
        yield bytes(pending[match.end():])


def access_units(stream):
    parts = []
    size = 0
    has_picture = False
    for nal in nal_units(stream):
        if not nal:
            continue
        kind = nal[0] & 31
        if kind == 9 and has_picture:
            yield b''.join(parts)
            parts, size, has_picture = [], 0, False
        size += len(nal) + 4
        if size > MAX_FRAME:
            raise ValueError('Access unit exceeds protocol limit; encoder must emit AUD NALs')
        parts.extend([struct.pack('>I', len(nal)), nal])
        has_picture |= kind in (1, 5)
    if has_picture:
        yield b''.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['extend', 'mirror', 'test'], default='extend')
    parser.add_argument('--model', choices=['pro105', 'ipad9'], default='pro105')
    parser.add_argument('--output', help='Existing output to mirror')
    parser.add_argument('--fps', type=int, choices=[30, 60], default=30)
    parser.add_argument('--seconds', type=int, default=0)
    parser.add_argument('--encoder', choices=['software', 'vaapi'], default='software')
    parser.add_argument('--gpu', default='/dev/dri/renderD128')
    parser.add_argument('--test-size', default=None, help='Override synthetic test dimensions, e.g. 1280x720')
    args = parser.parse_args()
    if args.seconds < 0:
        parser.error('--seconds must be nonnegative')
    config = json.loads((RUNTIME / 'device.json').read_text())
    token = (RUNTIME / 'receiver-token').read_text().strip()
    if not re.fullmatch('[0-9a-f]{64}', token):
        raise ValueError('Invalid receiver token; run install-app.py')
    lock = (RUNTIME / 'screen.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    width, height = (2224, 1668) if args.model == 'pro105' else (2160, 1620)
    if args.test_size:
        if args.mode != 'test' or not re.fullmatch(r'[1-9][0-9]{1,3}x[1-9][0-9]{1,3}', args.test_size):
            parser.error('--test-size requires test mode and dimensions such as 1280x720')
        width, height = map(int, args.test_size.split('x'))
    name = 'ipad-screen'
    created, recorder, device, video = False, None, None, None
    pipe_read = pipe_write = None
    last_ack, frames, sent = [0, 0, 0, 0], 0, 0
    started = time.monotonic()
    def stop(*unused):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGALRM, stop)
    log = (RUNTIME / 'encoder.log').open('w')
    try:
        if args.mode != 'test':
            monitors = json.loads(hypr('monitors', '-j'))
            if args.mode == 'extend':
                if any(m['name'] == name for m in monitors):
                    raise RuntimeError('ipad-screen output already exists; inspect before starting')
                right = max(m['x'] + round(m['width'] / m['scale']) for m in monitors)
                hypr('output', 'create', 'headless', name)
                created = True
                hypr('eval', f'hl.monitor({{output="{name}",mode="{width}x{height}@{args.fps}",position="{right}x0",scale=2}})')
                actual = next(m for m in json.loads(hypr('monitors', '-j')) if m['name'] == name)
                if (actual['width'], actual['height']) != (width, height):
                    raise RuntimeError('Virtual monitor resolution was not applied')
            else:
                selected = next((m for m in monitors if m['name'] == args.output), None) if args.output else next((m for m in monitors if m.get('focused')), monitors[0])
                if selected is None:
                    raise ValueError('Requested output is not active')
                name = selected['name']
                width, height = selected['width'], selected['height']
        subprocess.run(ssh_args(config) + ['mobile@ipad-usb', '/var/jb/usr/bin/uiopen --bundleid me.kerim.ipad-screen'], check=True, timeout=15)
        for attempt in range(20):
            try:
                device = connect(config['udid'], 27184)
                break
            except ConnectionError:
                if attempt == 19:
                    raise
                time.sleep(0.25)
        device.settimeout(10)
        device.sendall(b'IPDS0001' + token.encode())
        if read_exact(device, 8) != b'READY001':
            raise ValueError('Receiver rejected protocol handshake')
        pipe_read, pipe_write = os.pipe()
        path = f'/proc/self/fd/{pipe_write}'
        if args.mode == 'test':
            command = ['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-re', '-f', 'lavfi',
                '-i', f'testsrc2=size={width}x{height}:rate={args.fps}', '-an', '-c:v', 'libx264',
                '-preset', 'ultrafast', '-tune', 'zerolatency', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-x264-params', f'aud=1:repeat-headers=1:keyint={args.fps}:min-keyint={args.fps}:scenecut=0',
                '-f', 'h264', '-y', path]
        else:
            command = ['wf-recorder', '-o', name, '-D', '-r', str(args.fps), '-b', '0', '-m', 'h264', '-y', '-f', path]
            if args.encoder == 'software':
                command += ['-c', 'libx264', '-x', 'yuv420p', '-p', 'preset=ultrafast', '-p', 'tune=zerolatency',
                    '-p', 'crf=18', '-p', f'x264-params=aud=1:repeat-headers=1:keyint={args.fps}:min-keyint={args.fps}:scenecut=0']
            else:
                command += ['-c', 'h264_vaapi', '-d', args.gpu, '-p', 'aud=1', '-p', f'g={args.fps}', '-p', 'qp=18']
        print(f'Native {args.mode}: {width}×{height} at requested {args.fps} fps. Ctrl+C stops.', flush=True)
        recorder = subprocess.Popen(command, pass_fds=[pipe_write], stdout=log, stderr=log, stdin=subprocess.DEVNULL)
        os.close(pipe_write)
        pipe_write = None
        video = os.fdopen(pipe_read, 'rb', buffering=0)
        pipe_read = None
        if args.seconds:
            signal.setitimer(signal.ITIMER_REAL, args.seconds)
        for frame in access_units(video):
            device.sendall(struct.pack('>I', len(frame)) + frame)
            last_ack = list(struct.unpack('>IIII', read_exact(device, 16)))
            frames += 1
            sent += len(frame)
            if frames == 1 or frames % (args.fps * 5) == 0:
                print(f'Frames sent/decoded/queued: {frames}/{last_ack[1]}/{last_ack[2]}; errors={last_ack[3]}', flush=True)
            if last_ack[3] > 10:
                raise RuntimeError('Repeated iPad decoder errors; inspect its status')
        raise RuntimeError('Encoder stream ended; inspect .runtime/encoder.log')
    except KeyboardInterrupt:
        pass
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        if recorder is not None:
            recorder.send_signal(signal.SIGINT)
        if device is not None:
            device.close()
        if video is not None:
            video.close()
        for fd in (pipe_read, pipe_write):
            if fd is not None:
                os.close(fd)
        if recorder is not None:
            try:
                recorder.wait(timeout=5)
            except subprocess.TimeoutExpired:
                recorder.kill()
                recorder.wait()
        if created:
            hypr('output', 'remove', 'ipad-screen')
        log.close()
        result = dict(mode=args.mode, encoder='software' if args.mode == 'test' else args.encoder,
            requested_fps=args.fps, frames_sent=frames, last_ack=last_ack, bytes_sent=sent,
            duration_seconds=round(time.monotonic()-started, 2))
        (RUNTIME / 'native-session.json').write_text(json.dumps(result, indent=2) + '\n')
        print('Stopped: ' + json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
