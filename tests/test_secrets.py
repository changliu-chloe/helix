"""Secrets loading: separate git-ignored file, graceful missing-file degrade, never leaks values."""

import tempfile
import unittest
from pathlib import Path

from helix import secrets


class TestSecrets(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            s = secrets.load_secrets(Path(d))
            rs = s.for_remote("anything")
            self.assertFalse(rs.has_ssh_password)
            self.assertFalse(rs.has_sudo_password)

    def test_loads_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.secrets.yaml").write_text(
                "remotes:\n  gpu-a100:\n    ssh_password: pw1\n    sudo_password: pw2\n",
                encoding="utf-8",
            )
            s = secrets.load_secrets(Path(d))
            rs = s.for_remote("gpu-a100")
            self.assertTrue(rs.has_ssh_password)
            self.assertTrue(rs.has_sudo_password)
            self.assertEqual(rs.ssh_password, "pw1")
            self.assertEqual(rs.sudo_password, "pw2")

    def test_empty_password_means_keyauth(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.secrets.yaml").write_text(
                "remotes:\n  m:\n    ssh_password: ''\n", encoding="utf-8"
            )
            rs = secrets.load_secrets(Path(d)).for_remote("m")
            self.assertFalse(rs.has_ssh_password)

    def test_repr_does_not_leak_values(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.secrets.yaml").write_text(
                "remotes:\n  m:\n    ssh_password: topsecret\n", encoding="utf-8"
            )
            s = secrets.load_secrets(Path(d))
            self.assertNotIn("topsecret", repr(s))

    def test_malformed_file_degrades(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.secrets.yaml").write_text("just a string", encoding="utf-8")
            s = secrets.load_secrets(Path(d))
            self.assertFalse(s.for_remote("m").has_ssh_password)


if __name__ == "__main__":
    unittest.main()
