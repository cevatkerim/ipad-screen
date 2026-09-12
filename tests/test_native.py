import io
from pathlib import Path
import struct
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from native import access_units, nal_units


class FragmentedStream(io.BytesIO):
    def read(self, size=-1):
        return super().read(min(size, 2))


def unpack_avcc(au):
    offset, nals = 0, []
    while offset < len(au):
        length = struct.unpack_from('>I', au, offset)[0]
        offset += 4
        nals.append(au[offset:offset + length])
        offset += length
    return nals


class NativeProtocolTests(unittest.TestCase):
    def test_start_codes_split_across_reads(self):
        stream = b'\0\0\1\x09\xf0\0\0\0\1\x67abc\0\0\1\x65def'
        self.assertEqual(list(nal_units(FragmentedStream(stream))), [b'\x09\xf0', b'\x67abc', b'\x65def'])

    def test_multiple_slices_stay_in_the_same_access_unit(self):
        nals = [b'\x09\xf0', b'\x67sps', b'\x68pps', b'\x65slice1', b'\x65slice2', b'\x09\xf0', b'\x41next']
        stream = b''.join(b'\0\0\0\1' + nal for nal in nals)
        aus = list(access_units(FragmentedStream(stream)))
        self.assertEqual([unpack_avcc(au) for au in aus], [nals[:5], nals[5:]])

    def test_framed_stream_round_trips_through_real_decoder(self):
        encoded = subprocess.check_output(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
            'testsrc2=size=320x240:rate=30', '-frames:v', '6', '-c:v', 'libx264', '-preset', 'ultrafast',
            '-tune', 'zerolatency', '-x264-params', 'aud=1:repeat-headers=1', '-f', 'h264', 'pipe:1'])
        aus = list(access_units(FragmentedStream(encoded)))
        self.assertEqual(len(aus), 6)
        raw = b''.join(b'\0\0\0\1' + nal for au in aus for nal in unpack_avcc(au))
        decoded = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'h264', '-i', 'pipe:0',
            '-pix_fmt', 'yuv420p', '-f', 'rawvideo', 'pipe:1'], input=raw, capture_output=True, check=True)
        self.assertEqual(len(decoded.stdout), 6 * 320 * 240 * 3 // 2)


if __name__ == '__main__':
    unittest.main()
