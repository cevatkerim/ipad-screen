#!/usr/bin/env python3
"""Relay OpenSSH stdio over usbmux, preserving partial writes under load."""
import argparse
import os
import plistlib
import socket
import struct
import sys
import threading


def read_exact(sock, length):
    data = bytearray()
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError('usbmux socket closed')
        data.extend(chunk)
    return bytes(data)


def request(sock, message):
    payload = plistlib.dumps({'ClientVersionString': 'ipad-screen/0.1',
                             'ProgName': 'ipad-screen', 'kLibUSBMuxVersion': 3, **message})
    sock.sendall(struct.pack('<IIII', len(payload) + 16, 1, 8, 1) + payload)
    length, version, kind, tag = struct.unpack('<IIII', read_exact(sock, 16))
    if not 16 <= length <= 1024 * 1024 or (version, kind, tag) != (1, 8, 1):
        raise ValueError('Invalid usbmux response header')
    return plistlib.loads(read_exact(sock, length - 16))


def mux_socket():
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(8)
    sock.connect('/var/run/usbmuxd')
    return sock


def connect(udid, port):
    with mux_socket() as control:
        devices = request(control, {'MessageType': 'ListDevices'}).get('DeviceList', [])
    device = next((d for d in devices if d.get('Properties', {}).get('SerialNumber') == udid
                   and d['Properties'].get('ConnectionType') == 'USB'), None)
    if device is None:
        raise ConnectionError('Selected USB iPad is not connected')
    sock = mux_socket()
    try:
        reply = request(sock, {'MessageType': 'Connect', 'DeviceID': device['DeviceID'],
                               'PortNumber': socket.htons(port)})
        if reply.get('Number') != 0:
            raise ConnectionError(f'Device port unavailable: {reply.get("Number")}')
        sock.settimeout(None)
        return sock
    except Exception:
        sock.close()
        raise


def relay(sock):
    def upload():
        try:
            while chunk := os.read(0, 65536):
                sock.sendall(chunk)
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    sender = threading.Thread(target=upload, daemon=True)
    sender.start()
    while chunk := sock.recv(65536):
        pending = memoryview(chunk)
        while pending:
            written = os.write(1, pending)
            if written <= 0:
                raise ConnectionError('SSH closed its input')
            pending = pending[written:]
    # A peer may finish sending while it is still receiving our queued bytes.
    # Signal that half-close to SSH before waiting for its remaining input.
    os.close(1)
    sender.join()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--udid', required=True)
    parser.add_argument('--port', type=int, default=22)
    args = parser.parse_args()
    try:
        with connect(args.udid, args.port) as device_socket:
            relay(device_socket)
    except (OSError, ValueError) as exc:
        print(f'USB relay: {exc}', file=sys.stderr)
        sys.exit(1)
