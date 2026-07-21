"""Git guardrails: clean-tree detection + round commit, on a real throwaway repo."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from helix import vcs


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


class TestVcs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        _git(self.repo, "init")
        _git(self.repo, "config", "user.email", "t@t.t")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "a.txt").write_text("hello", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-m", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_tree(self):
        self.assertTrue(vcs.is_clean(self.repo))

    def test_dirty_tree(self):
        (self.repo / "a.txt").write_text("changed", encoding="utf-8")
        self.assertFalse(vcs.is_clean(self.repo))

    def test_commit_round_makes_clean(self):
        (self.repo / "b.txt").write_text("new", encoding="utf-8")
        self.assertFalse(vcs.is_clean(self.repo))
        commit = vcs.commit_round(self.repo, "实验轮次：加了 b")
        self.assertTrue(commit)                    # got a hash
        self.assertTrue(vcs.is_clean(self.repo))   # tree clean after commit

    def test_current_commit_nonempty(self):
        self.assertTrue(vcs.current_commit(self.repo))

    def test_commit_round_on_clean_raises(self):
        # nothing to commit -> git commit exits non-zero -> RuntimeError
        with self.assertRaises(RuntimeError):
            vcs.commit_round(self.repo, "empty")


class TestWorkspaceRepoInit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ensure_repo_initializes_once(self):
        self.assertFalse(vcs.is_git_repo(self.ws))
        self.assertTrue(vcs.ensure_repo(self.ws))
        self.assertTrue(vcs.is_git_repo(self.ws))
        self.assertFalse(vcs.ensure_repo(self.ws))

    def test_set_identity_is_repo_local(self):
        vcs.ensure_repo(self.ws)
        vcs.set_identity(self.ws, "exp bot", "exp@example.com")
        name = subprocess.run(
            ["git", "-C", str(self.ws), "config", "--local", "--get", "user.name"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        email = subprocess.run(
            ["git", "-C", str(self.ws), "config", "--local", "--get", "user.email"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(name, "exp bot")
        self.assertEqual(email, "exp@example.com")

    def test_new_workspace_can_commit_first_round(self):
        (self.ws / "plan.md").write_text("plan", encoding="utf-8")
        vcs.ensure_repo(self.ws)
        vcs.set_identity(self.ws, "exp bot", "exp@example.com")
        self.assertFalse(vcs.is_clean(self.ws))
        commit = vcs.commit_round(self.ws, "feat: first round")
        self.assertTrue(commit)
        self.assertTrue(vcs.is_clean(self.ws))


if __name__ == "__main__":
    unittest.main()
