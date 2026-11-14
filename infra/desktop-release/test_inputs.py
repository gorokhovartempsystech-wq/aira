import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import common


class TransferredInputTests(unittest.TestCase):
    def test_verified_transferred_input_needs_no_network(self):
        data = b"synthetic immutable runtime archive"
        pin = ("runtime.zip", hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / pin[0]
            target.write_bytes(data)
            with (
                patch.dict(common.PINS, {"fixture": pin}),
                patch.object(common, "urlopen") as network,
            ):
                self.assertEqual(common.download_pin("fixture", directory), target)
                network.assert_not_called()

    def test_tampered_transferred_archive_cannot_be_used(self):
        pin = ("runtime.zip", hashlib.sha256(b"expected archive").hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / pin[0]
            target.write_bytes(b"tampered archive")
            with (
                patch.dict(common.PINS, {"fixture": pin}),
                patch.object(common, "urlopen") as network,
                self.assertRaisesRegex(ValueError, "checksum mismatch"),
            ):
                common.download_pin("fixture", directory)
            network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
