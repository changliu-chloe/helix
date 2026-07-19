"""Remote execution layer: ssh/tmux argv shape, credential injection via env/stdin (never argv), probe parsing.

Real ssh is never invoked — we patch helix.ssh._exec and assert on the argv/env/stdin it would receive,
so the security-critical property (no password in argv, ever) is verified deterministically.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helix import ssh
from helix.config import Config, Remote
from helix.secrets import RemoteSecret, Secrets


def _fake_proc(stdout="", stderr="", rc=0):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


class TestSshBase(unittest.TestCase):
    def test_keyauth_no_sshpass_no_env(self):
        remote = Remote("m", host="myhost")
        argv, env = ssh._ssh_base(remote, RemoteSecret())
        self.assertEqual(argv[0], "ssh")
        self.assertIn("myhost", argv)
        self.assertIsNone(env)

    def test_ssh_key_adds_identity(self):
        remote = Remote("m", host="myhost", ssh_key="/home/me/.ssh/id_ed25519")
        argv, _ = ssh._ssh_base(remote, RemoteSecret())
        self.assertIn("-i", argv)
        self.assertIn("/home/me/.ssh/id_ed25519", argv)

    def test_user_host_target(self):
        remote = Remote("m", host="myhost", user="alice")
        argv, _ = ssh._ssh_base(remote, RemoteSecret())
        self.assertIn("alice@myhost", argv)

    def test_password_goes_to_env_not_argv(self):
        remote = Remote("m", host="myhost")
        with mock.patch.object(ssh.shutil, "which", return_value="/usr/bin/sshpass"):
            argv, env = ssh._ssh_base(remote, RemoteSecret(ssh_password="topsecret"))
        # password must NOT appear anywhere in argv
        self.assertNotIn("topsecret", " ".join(argv))
        self.assertEqual(argv[0], "sshpass")
        self.assertIn("-e", argv)                      # sshpass reads SSHPASS from env
        self.assertEqual(env, {"SSHPASS": "topsecret"})

    def test_password_without_sshpass_raises(self):
        remote = Remote("m", host="myhost")
        with mock.patch.object(ssh.shutil, "which", return_value=None):
            with self.assertRaises(FileNotFoundError):
                ssh._ssh_base(remote, RemoteSecret(ssh_password="pw"))


class TestRunInTmux(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(_path=Path("/tmp/config.yaml"))
        self.remote = Remote("gpu", host="gpu", remote_repro_root="/data/exp")
        self.secrets = Secrets({})
        self.remote_path = "/data/exp/domX/paperY"  # resolved by CLI, passed into ssh layer

    def _run_capture(self, **kwargs):
        with mock.patch.object(ssh, "_exec", return_value=_fake_proc()) as ex:
            ssh.run_in_tmux(self.cfg, self.secrets, self.remote, self.remote_path, "python train.py",
                            session="train", **kwargs)
        return ex.call_args

    def test_persistent_session_no_kill(self):
        args = self._run_capture(oneshot=False)
        remote_script = args[0][0][-1]
        self.assertIn("new-session", remote_script)
        self.assertIn("send-keys", remote_script)
        self.assertNotIn("kill-session", remote_script)
        self.assertIn("/data/exp/domX/paperY", remote_script)  # cd into remote workspace

    def test_oneshot_appends_kill(self):
        args = self._run_capture(oneshot=True)
        remote_script = args[0][0][-1]
        self.assertIn("kill-session", remote_script)

    def test_sudo_password_via_stdin_not_argv(self):
        secrets = Secrets({"gpu": RemoteSecret(sudo_password="rootpw")})
        with mock.patch.object(ssh, "_exec", return_value=_fake_proc()) as ex:
            ssh.run_in_tmux(self.cfg, secrets, self.remote, self.remote_path, "apt install x",
                            session="s", use_sudo=True)
        call = ex.call_args
        argv, env, stdin_data = call[0][0], call[0][1], call[0][2]
        self.assertNotIn("rootpw", " ".join(argv))        # never in argv
        self.assertEqual(stdin_data, "rootpw\n")           # delivered on stdin


class TestProbeParse(unittest.TestCase):
    def test_parse_disk_and_gpus(self):
        out = (
            "###DISK\n"
            "/dev/sda1  1.8T  1.2T  600G  67% /data\n"
            "###GPU\n"
            "0, 1024, 40960, 15\n"
            "1, 0, 40960, 0\n"
        )
        parsed = ssh._parse_probe(out)
        self.assertEqual(parsed["disk"]["avail"], "600G")
        self.assertTrue(parsed["has_gpu"])
        self.assertEqual(len(parsed["gpus"]), 2)
        self.assertEqual(parsed["gpus"][0]["mem_used_mb"], 1024)
        self.assertEqual(parsed["gpus"][1]["util_pct"], 0)

    def test_no_gpu(self):
        out = "###DISK\n/dev/sda1 100G 50G 50G 50% /\n###GPU\nNO_GPU\n"
        parsed = ssh._parse_probe(out)
        self.assertFalse(parsed["has_gpu"])
        self.assertEqual(parsed["gpus"], [])


class TestRequireRemote(unittest.TestCase):
    def test_unknown_remote_raises(self):
        cfg = Config(_path=Path("/tmp/c.yaml"), remotes=[Remote("a", host="a")])
        with self.assertRaises(ValueError):
            ssh.require_remote(cfg, "nope")

    def test_missing_host_raises(self):
        cfg = Config(_path=Path("/tmp/c.yaml"), remotes=[Remote("a", host="")])
        with self.assertRaises(ValueError):
            ssh.require_remote(cfg, "a")


if __name__ == "__main__":
    unittest.main()
