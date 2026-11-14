import unittest

from macos_minimum import minimum


class MinimumVersionTests(unittest.TestCase):
    def test_load_command_deployment_version_is_distinct_from_library_version(self):
        text = """Load command 0
          cmd LC_ID_DYLIB
          current version 9000.0.0
        Load command 1
          cmd LC_BUILD_VERSION
          platform MACOS
          minos 14.0
          sdk 26.0
        """
        self.assertEqual(minimum(text), (14, 0, 0))

    def test_old_load_command_and_fat_binary_use_highest_required_version(self):
        text = """Load command 0
          cmd LC_VERSION_MIN_MACOSX
          version 12.0
        Load command 1
          cmd LC_BUILD_VERSION
          platform 1
          minos 15.2
        """
        self.assertEqual(minimum(text), (15, 2, 0))


if __name__ == "__main__":
    unittest.main()
