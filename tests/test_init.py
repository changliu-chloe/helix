"""helix init symlink unit tests."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helix import init


class TestLinkSkills(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # build the skills source dir: two valid skills + one dir without SKILL.md (should be ignored)
        for name in ("search", "daily"):
            d = self.root / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("---\nname: %s\n---\n" % name, encoding="utf-8")
        (self.root / "skills" / "notaskill").mkdir(parents=True)

        self._p1 = mock.patch.object(init, "PROJECT_ROOT", self.root)
        self._p2 = mock.patch.object(init, "SKILLS_SRC", self.root / "skills")
        self._p1.start()
        self._p2.start()

    def tearDown(self):
        self._p1.stop()
        self._p2.stop()
        self.tmp.cleanup()

    def test_creates_symlinks_in_both_dirs(self):
        logs = init.link_skills(scope="project")
        # linked into BOTH .claude/skills and .agents/skills
        for family in (".claude", ".agents"):
            dest = self.root / family / "skills"
            self.assertTrue((dest / "search").is_symlink(), family)
            self.assertTrue((dest / "daily").is_symlink(), family)
            self.assertFalse((dest / "notaskill").exists())  # no SKILL.md, ignored
        # 2 skills x 2 dirs = 4 links
        self.assertEqual(sum(1 for x in logs if x.startswith("已链接")), 4)

    def test_idempotent(self):
        init.link_skills(scope="project")
        logs = init.link_skills(scope="project")
        self.assertTrue(all("跳过" in x for x in logs if "search" in x or "daily" in x))
        self.assertEqual(sum(1 for x in logs if x.startswith("已链接")), 0)

    def test_does_not_overwrite_real_dir(self):
        dest = self.root / ".claude" / "skills"
        dest.mkdir(parents=True)
        (dest / "search").mkdir()  # real directory placeholder
        logs = init.link_skills(scope="project")
        self.assertFalse((dest / "search").is_symlink())  # not overwritten
        self.assertTrue(any("非软链" in x for x in logs))


class TestPruneStaleLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in ("search", "daily"):
            d = self.root / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("---\nname: %s\n---\n" % name, encoding="utf-8")
        self._p1 = mock.patch.object(init, "PROJECT_ROOT", self.root)
        self._p2 = mock.patch.object(init, "SKILLS_SRC", self.root / "skills")
        self._p1.start()
        self._p2.start()

    def tearDown(self):
        self._p1.stop()
        self._p2.stop()
        self.tmp.cleanup()

    def test_prunes_link_to_deleted_skill(self):
        init.link_skills(scope="project")
        # simulate upstream deleting the "daily" skill
        (self.root / "skills" / "daily" / "SKILL.md").unlink()
        (self.root / "skills" / "daily").rmdir()
        logs = init.prune_stale_skill_links(scope="project")
        # pruned from BOTH families, valid link kept in both
        for family in (".claude", ".agents"):
            dest = self.root / family / "skills"
            self.assertFalse((dest / "daily").exists(), family)     # dangling link removed
            self.assertTrue((dest / "search").is_symlink(), family)  # valid link kept
        self.assertTrue(any("daily" in x for x in logs))

    def test_leaves_foreign_links_untouched(self):
        # a symlink the user added pointing OUTSIDE our skills/ dir must not be pruned
        dest = self.root / ".claude" / "skills"
        dest.mkdir(parents=True)
        external = self.root / "external_skill"
        external.mkdir()
        foreign = dest / "mine"
        foreign.symlink_to(external, target_is_directory=True)
        external.rmdir()  # now dangling, but it's not ours
        logs = init.prune_stale_skill_links(scope="project")
        self.assertTrue(foreign.is_symlink())              # left alone
        self.assertEqual(logs, [])

    def test_idempotent_when_nothing_stale(self):
        init.link_skills(scope="project")
        self.assertEqual(init.prune_stale_skill_links(scope="project"), [])


class TestLinkAgentsMd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "CLAUDE.md").write_text("# conventions\n", encoding="utf-8")
        self._p1 = mock.patch.object(init, "PROJECT_ROOT", self.root)
        self._p2 = mock.patch.object(init, "CONVENTIONS_SRC", self.root / "CLAUDE.md")
        self._p3 = mock.patch.object(init, "AGENTS_MD", self.root / "AGENTS.md")
        self._p1.start()
        self._p2.start()
        self._p3.start()

    def tearDown(self):
        self._p1.stop()
        self._p2.stop()
        self._p3.stop()
        self.tmp.cleanup()

    def test_symlinks_agents_md_to_claude_md(self):
        logs = init.link_agents_md()
        link = self.root / "AGENTS.md"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (self.root / "CLAUDE.md").resolve())
        # content read through the link matches CLAUDE.md — single source of truth
        self.assertEqual(link.read_text(encoding="utf-8"), "# conventions\n")
        self.assertEqual(sum(1 for x in logs if x.startswith("已链接")), 1)

    def test_idempotent(self):
        init.link_agents_md()
        logs = init.link_agents_md()
        self.assertEqual(sum(1 for x in logs if x.startswith("已链接")), 0)
        self.assertTrue(any("跳过" in x for x in logs))

    def test_does_not_overwrite_real_agents_md(self):
        (self.root / "AGENTS.md").write_text("hand-written\n", encoding="utf-8")
        logs = init.link_agents_md()
        self.assertFalse((self.root / "AGENTS.md").is_symlink())  # left alone
        self.assertEqual((self.root / "AGENTS.md").read_text(encoding="utf-8"), "hand-written\n")
        self.assertTrue(any("非软链" in x for x in logs))

    def test_skips_when_no_claude_md(self):
        (self.root / "CLAUDE.md").unlink()
        logs = init.link_agents_md()
        self.assertFalse((self.root / "AGENTS.md").exists())
        self.assertTrue(any("未找到规约源" in x for x in logs))


if __name__ == "__main__":
    unittest.main()
