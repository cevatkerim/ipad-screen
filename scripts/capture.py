"""Restart Wayland capture after layout changes, EOF, or a stalled encoder."""
from collections import deque
import os
import select
import signal
import subprocess
import time


class CaptureChanged(Exception):
    pass


class CaptureReader:
    def __init__(self, fd, layout, initial_layout, poll_interval=0.5, stall_timeout=3):
        self.fd, self.layout, self.initial_layout = fd, layout, initial_layout
        self.poll_interval, self.stall_timeout = poll_interval, stall_timeout
        self.last_data = time.monotonic()
        self.next_check = self.last_data + poll_interval

    def read(self, size):
        while True:
            now = time.monotonic()
            if now >= self.next_check:
                if self.layout() != self.initial_layout:
                    raise CaptureChanged('display layout changed')
                self.next_check = now + self.poll_interval
            if now - self.last_data >= self.stall_timeout:
                raise CaptureChanged('encoder stopped producing frames')
            ready, _, _ = select.select([self.fd], [], [], min(self.poll_interval, self.stall_timeout))
            if ready:
                data = os.read(self.fd, size)
                self.last_data = time.monotonic()
                return data


def recovering_frames(command_factory, layout, parse_frames, log, on_restart,
                      poll_interval=0.5, stall_timeout=3, max_failures=5):
    """Keep the output and USB session alive; each new encoder starts at an IDR.

    The consumer must close this generator when it stops, including on errors.
    Repeated unexplained failures are bounded; deliberate layout edits can recur.
    """
    failures = deque()
    while True:
        snapshot = layout()  # Also verifies that the selected output still exists.
        read_fd, write_fd = os.pipe()
        process = None
        try:
            command = command_factory(f'/proc/self/fd/{write_fd}')
            process = subprocess.Popen(command, pass_fds=[write_fd], stdout=log,
                                       stderr=log, stdin=subprocess.DEVNULL)
            os.close(write_fd)
            write_fd = None
            reader = CaptureReader(read_fd, layout, snapshot, poll_interval, stall_timeout)
            try:
                yield from parse_frames(reader)
                reason = 'display layout changed' if layout() != snapshot else 'encoder stream ended'
            except CaptureChanged as exc:
                reason = str(exc)
        finally:
            if process is not None and process.poll() is None:
                process.send_signal(signal.SIGINT)
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
            if process is not None:
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if reason != 'display layout changed':
            now = time.monotonic()
            while failures and now - failures[0] > 30:
                failures.popleft()
            failures.append(now)
            if len(failures) > max_failures:
                raise RuntimeError('Capture repeatedly failed; inspect .runtime/encoder.log')
        on_restart(reason)
        log.write('\nRestarting capture: ' + reason + '\n')
        log.flush()
        time.sleep(0.35)
