"""Exercise transport framing and simultaneous bulk traffic without an iPad."""
import os
import select
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from usbmux_proxy import read_exact, request


class USBTransportTests(unittest.TestCase):
    def test_remote_half_close_reaches_ssh_before_stdin_closes(self):
        a, b = socket.socketpair()
        with a, b:
            code = ('import socket,sys; from usbmux_proxy import relay; '
                    'relay(socket.socket(fileno=int(sys.argv[1])))')
            child = subprocess.Popen([sys.executable, '-c', code, str(a.fileno())],
                                     cwd=SCRIPTS, pass_fds=[a.fileno()],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            a.close()
            try:
                b.shutdown(socket.SHUT_WR)
                readable, _, _ = select.select([child.stdout], [], [], 3)
                self.assertTrue(readable, 'SSH must see remote EOF while its input remains open')
                self.assertEqual(child.stdout.read(1), b'')
                child.stdin.write(b'final bytes')
                child.stdin.close()
                self.assertEqual(read_exact(b, 11), b'final bytes')
                self.assertEqual(child.wait(timeout=3), 0)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
                child.stdout.close()
                child.stderr.close()

    def test_truncated_read_is_an_error(self):
        a, b = socket.socketpair()
        with a, b:
            b.sendall(b'ab')
            b.shutdown(socket.SHUT_WR)
            with self.assertRaises(ConnectionError):
                read_exact(a, 3)

    def test_invalid_response_length_rejected(self):
        a, b = socket.socketpair()
        with a, b:
            b.sendall(struct.pack('<IIII', 2**31, 1, 8, 1))
            with self.assertRaises(ValueError):
                request(a, {'MessageType': 'ListDevices'})

    def test_bidirectional_bulk_relay_preserves_every_byte(self):
        upload, download = os.urandom(2 * 1024 * 1024), os.urandom(2 * 1024 * 1024)
        a, b = socket.socketpair()
        received = bytearray()
        with a, b:
            a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            b.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            code = ('import socket,sys; from usbmux_proxy import relay; '
                    'relay(socket.socket(fileno=int(sys.argv[1])))')
            child = subprocess.Popen([sys.executable, '-c', code, str(a.fileno())],
                                     cwd=SCRIPTS, pass_fds=[a.fileno()],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            a.close()
            def send():
                b.sendall(download)
                b.shutdown(socket.SHUT_WR)
            def receive():
                while chunk := b.recv(4096):
                    received.extend(chunk)
            sender = threading.Thread(target=send, daemon=True)
            receiver = threading.Thread(target=receive, daemon=True)
            sender.start()
            receiver.start()
            try:
                output, errors = child.communicate(upload, timeout=15)
                sender.join(5)
                receiver.join(5)
                self.assertEqual(child.returncode, 0, errors.decode())
                self.assertEqual(output, download)
                self.assertEqual(received, upload)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()


if __name__ == '__main__':
    unittest.main()
