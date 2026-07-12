"""arxo init 软链单元测试。"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arxo import init


class TestLinkSkills(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # 造 skills 源目录：两个合法 skill + 一个无 SKILL.md 的目录（应被忽略）
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

    def test_creates_symlinks(self):
        logs = init.link_skills(scope="project")
        dest = self.root / ".claude" / "skills"
        self.assertTrue((dest / "search").is_symlink())
        self.assertTrue((dest / "daily").is_symlink())
        self.assertFalse((dest / "notaskill").exists())  # 无 SKILL.md 被忽略
        self.assertEqual(sum(1 for x in logs if x.startswith("已链接")), 2)

    def test_idempotent(self):
        init.link_skills(scope="project")
        logs = init.link_skills(scope="project")
        self.assertTrue(all("跳过" in x for x in logs if "search" in x or "daily" in x))
        self.assertEqual(sum(1 for x in logs if x.startswith("已链接")), 0)

    def test_does_not_overwrite_real_dir(self):
        dest = self.root / ".claude" / "skills"
        dest.mkdir(parents=True)
        (dest / "search").mkdir()  # 真实目录占位
        logs = init.link_skills(scope="project")
        self.assertFalse((dest / "search").is_symlink())  # 未被覆盖
        self.assertTrue(any("非软链" in x for x in logs))


if __name__ == "__main__":
    unittest.main()
