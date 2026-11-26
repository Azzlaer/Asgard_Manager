import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import local_auth


class LocalAuthTests(unittest.TestCase):
    def test_token_persists_and_rejects_wrong_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(local_auth, "TOKEN_FILE", Path(tmp) / "token"):
                token = local_auth.load_token()
                self.assertEqual(token, local_auth.load_token())
                self.assertTrue(local_auth.authorized(token))
                self.assertFalse(local_auth.authorized(""))
                self.assertFalse(local_auth.authorized("wrong"))

    def test_only_game_ingest_is_exempt_from_local_token(self):
        self.assertTrue(local_auth.is_bridge_ingest("POST", "/asgard-suite/1/audit"))
        self.assertTrue(local_auth.is_bridge_ingest("POST", "/asgard-suite/1/punishments"))
        for method, path in [("GET", "/asgard-suite/1/settings"), ("PUT", "/asgard-suite/1/settings"), ("POST", "/shutdown"), ("POST", "/asgard-suite/1/audit/extra")]:
            self.assertFalse(local_auth.is_bridge_ingest(method, path))


if __name__ == "__main__":
    unittest.main()
