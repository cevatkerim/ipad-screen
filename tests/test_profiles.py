import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ipad


class DeviceProfileTests(unittest.TestCase):
    def test_switch_preserves_original_pairing_and_token_location(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(ipad, 'RUNTIME', Path(directory)):
            original = {'udid': 'first', 'key': '/example/key'}
            second = {'udid': 'second', 'key': '/example/key', 'model': 'pro97', 'token_file': 'receiver-token-second'}
            (ipad.RUNTIME / 'device.json').write_text(json.dumps(original))
            ipad.save_device(second)
            profiles = json.loads((ipad.RUNTIME / 'devices.json').read_text())
            self.assertEqual(profiles['first'], original)
            self.assertNotEqual(ipad.receiver_token(original), ipad.receiver_token(second))
            ipad.save_device(profiles['first'])
            self.assertEqual(json.loads((ipad.RUNTIME / 'device.json').read_text()), original)
            self.assertEqual(json.loads((ipad.RUNTIME / 'devices.json').read_text())['second'], second)
            self.assertEqual((ipad.RUNTIME / 'devices.json').stat().st_mode & 0o777, 0o600)
