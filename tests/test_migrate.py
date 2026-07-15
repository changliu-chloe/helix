"""helix migrate unit tests: skill re-link/prune, config drift, dependency drift, state persistence."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helix import init, migrate
from helix.config import Config


class TestMigrate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # project layout: skills/ + config.example.yaml + uv.lock
        for name in ("search", "daily"):
            d = self.root / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("---\nname: %s\n---\n" % name, encoding="utf-8")
        self.example = self.root / "config.example.yaml"
        self.example.write_text(
            "language: zh\nnotes_dir: notes\nrepro_dir: repro\nnew_field: 1\n", encoding="utf-8"
        )
        self.lock = self.root / "uv.lock"
        self.lock.write_text("v1", encoding="utf-8")
        self.claude_md = self.root / "CLAUDE.md"
        self.claude_md.write_text("# conventions\n", encoding="utf-8")

        # user config: has language/notes_dir but NOT repro_dir or new_field
        self.user_cfg_path = self.root / "config.yaml"
        self.user_cfg_path.write_text("language: zh\nnotes_dir: notes\n", encoding="utf-8")
        self.cfg = Config(notes_dir=str(self.root / "notes"), _path=self.user_cfg_path)

        # redirect module-level paths into the temp project
        self._patches = [
            mock.patch.object(init, "PROJECT_ROOT", self.root),
            mock.patch.object(init, "SKILLS_SRC", self.root / "skills"),
            mock.patch.object(init, "CONVENTIONS_SRC", self.claude_md),
            mock.patch.object(init, "AGENTS_MD", self.root / "AGENTS.md"),
            mock.patch.object(migrate, "PROJECT_ROOT", self.root),
            mock.patch.object(migrate, "EXAMPLE_CONFIG", self.example),
            mock.patch.object(migrate, "LOCK_FILE", self.lock),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def test_links_skills_and_reports_new_config_keys(self):
        report, _ = migrate.run_migrate(self.cfg, scope="project")
        self.assertTrue((self.root / ".claude" / "skills" / "search").is_symlink())
        self.assertTrue((self.root / ".agents" / "skills" / "search").is_symlink())
        self.assertTrue((self.root / "AGENTS.md").is_symlink())
        # 2 skills x 2 dirs + AGENTS.md = 5 new links
        self.assertEqual(len(report.linked), 5)
        # repro_dir + new_field are in example but not in user config
        self.assertIn("repro_dir", report.new_config_keys)
        self.assertIn("new_field", report.new_config_keys)
        self.assertNotIn("language", report.new_config_keys)

    def test_prunes_stale_link(self):
        migrate.run_migrate(self.cfg, scope="project")
        # upstream removes the daily skill
        (self.root / "skills" / "daily" / "SKILL.md").unlink()
        (self.root / "skills" / "daily").rmdir()
        report, _ = migrate.run_migrate(self.cfg, scope="project")
        dest = self.root / ".claude" / "skills"
        self.assertFalse((dest / "daily").exists())
        self.assertTrue(len(report.pruned) >= 1)

    def test_deps_change_detected_only_after_baseline(self):
        # first run records the baseline hash -> not flagged as changed
        report1, _ = migrate.run_migrate(self.cfg, scope="project")
        self.assertFalse(report1.deps_changed)
        # lock unchanged -> still not flagged
        report2, _ = migrate.run_migrate(self.cfg, scope="project")
        self.assertFalse(report2.deps_changed)
        # lock changes -> flagged
        self.lock.write_text("v2", encoding="utf-8")
        report3, _ = migrate.run_migrate(self.cfg, scope="project")
        self.assertTrue(report3.deps_changed)

    def test_idempotent_links(self):
        migrate.run_migrate(self.cfg, scope="project")
        report, _ = migrate.run_migrate(self.cfg, scope="project")
        self.assertEqual(len(report.linked), 0)  # already linked, nothing new

    def test_state_file_written(self):
        migrate.run_migrate(self.cfg, scope="project")
        state = self.root / ".helix" / "state.json"
        self.assertTrue(state.exists())


if __name__ == "__main__":
    unittest.main()
