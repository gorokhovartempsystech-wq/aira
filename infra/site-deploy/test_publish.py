import unittest
from unittest.mock import patch

import publish


class ValidationModeTests(unittest.TestCase):
    def test_check_mode_on_main_push_never_requests_a_token_or_publishes(self):
        environment = {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main"}
        with (
            patch.dict(publish.os.environ, environment, clear=True),
            patch.object(
                publish, "payload", return_value={"sha": "a" * 40, "files": {}}
            ),
            patch.object(publish, "urlopen") as network,
        ):
            publish.main(["--check"])
        network.assert_not_called()

    def test_pull_request_never_publishes_without_check_flag(self):
        with (
            patch.dict(
                publish.os.environ, {"GITHUB_EVENT_NAME": "pull_request"}, clear=True
            ),
            patch.object(
                publish, "payload", return_value={"sha": "a" * 40, "files": {}}
            ),
            patch.object(publish, "urlopen") as network,
        ):
            publish.main([])
        network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
