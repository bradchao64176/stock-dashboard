import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from services.line_bot_service import ENV_PATH, load_line_credentials, send_text


class LineCredentialsTests(unittest.TestCase):
    def test_project_path_is_independent_of_working_directory(self):
        self.assertEqual(ENV_PATH, Path(__file__).resolve().parents[1] / ".env")

    def test_dotenv_credentials_and_reload_without_environment_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text('LINE_CHANNEL_ACCESS_TOKEN="test-token"\nLINE_USER_ID=test-user\n', encoding="utf-8")
            with patch("services.line_bot_service.ENV_PATH", path), patch.dict(os.environ, {}, clear=True), \
                 patch("services.line_bot_service.requests.post", return_value=Mock(status_code=200)) as post:
                self.assertEqual(load_line_credentials(), ("test-token", "test-user"))
                self.assertNotIn("LINE_USER_ID", os.environ)
                self.assertTrue(send_text("test", "test-retry")["ok"])
                self.assertEqual(post.call_args.kwargs["json"]["to"], "test-user")
                self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-token")
                path.write_text('LINE_CHANNEL_ACCESS_TOKEN=new-token\nLINE_USER_ID=new-user\n', encoding="utf-8")
                self.assertEqual(load_line_credentials(), ("new-token", "new-user"))

    def test_explicit_environment_override_and_missing_credentials(self):
        with patch("services.line_bot_service.dotenv_values", return_value={"LINE_USER_ID": "file-user", "LINE_CHANNEL_ACCESS_TOKEN": "file-token"}), \
             patch.dict(os.environ, {"LINE_USER_ID": "env-user", "LINE_CHANNEL_ACCESS_TOKEN": "env-token"}):
            self.assertEqual(load_line_credentials(), ("env-token", "env-user"))
        with patch("services.line_bot_service.dotenv_values", return_value={}), patch.dict(os.environ, {}, clear=True), \
             patch("services.line_bot_service.requests.post") as post:
            self.assertFalse(send_text("test", "test-retry")["ok"])
            post.assert_not_called()
