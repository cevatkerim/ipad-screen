from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from capture import recovering_frames


def bytes_as_frames(stream):
    while frame := stream.read(1):
        yield frame


class CaptureRecoveryTests(unittest.TestCase):
    def run_capture(self, factory, layout, **kwargs):
        log = tempfile.TemporaryFile(mode='w+')
        self.addCleanup(log.close)
        reasons = []
        capture = recovering_frames(factory, layout, bytes_as_frames, log, reasons.append,
                                    poll_interval=0.01, stall_timeout=0.2, **kwargs)
        self.addCleanup(capture.close)
        return capture, reasons

    def test_layout_change_restarts_stuck_encoder_and_reaps_children(self):
        layout = [1]
        def factory(path):
            return [sys.executable, '-c',
                    'import os,sys,time; f=open(sys.argv[1],"wb",buffering=0); f.write(b"x"); time.sleep(20)', path]
        popen = subprocess.Popen
        children = []
        def spawn(*args, **kwargs):
            child = popen(*args, **kwargs)
            children.append(child)
            return child
        with patch('capture.subprocess.Popen', side_effect=spawn):
            capture, reasons = self.run_capture(factory, lambda: tuple(layout))
            self.assertEqual(next(capture), b'x')
            layout[0] = 2
            self.assertEqual(next(capture), b'x')
            self.assertEqual(reasons, ['display layout changed'])
            capture.close()
        self.assertEqual(len(children), 2)
        self.assertTrue(all(child.poll() is not None for child in children))

    def test_eof_starts_a_fresh_stream(self):
        attempts = []
        def factory(path):
            attempts.append(path)
            return [sys.executable, '-c',
                    'import sys; open(sys.argv[1],"wb").write(sys.argv[2].encode())', path, str(len(attempts))]
        capture, reasons = self.run_capture(factory, lambda: ())
        self.assertEqual(next(capture), b'1')
        self.assertEqual(next(capture), b'2')
        self.assertEqual(reasons, ['encoder stream ended'])

    def test_stall_recovers_without_waiting_for_eof(self):
        def factory(path):
            return [sys.executable, '-c',
                    'import sys,time; f=open(sys.argv[1],"wb",buffering=0); f.write(b"x"); time.sleep(20)', path]
        capture, reasons = self.run_capture(factory, lambda: ())
        self.assertEqual(next(capture), b'x')
        self.assertEqual(next(capture), b'x')
        self.assertEqual(reasons, ['encoder stopped producing frames'])

    def test_persistent_failures_are_bounded(self):
        capture, reasons = self.run_capture(lambda path: [sys.executable, '-c', 'pass'], lambda: (), max_failures=2)
        with self.assertRaisesRegex(RuntimeError, 'repeatedly failed'):
            next(capture)
        self.assertEqual(len(reasons), 2)


if __name__ == '__main__':
    unittest.main()
