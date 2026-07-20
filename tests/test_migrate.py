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
            "language: zh\n"
            "notes_dir: notes\n"
            "# 实验工作区根目录（与 notes 平级）\n"
            "experiments_dir: experiments\n"
            "# 一个带注释的标量新字段\n"
            "new_field: ''\n"
            "# 远程 GPU 机器册（嵌套块）\n"
            "remotes:\n"
            "  gpu-a100:\n"
            "    host: gpu-a100\n"
            "    remote_repro_root: /data/exp\n",
            encoding="utf-8",
        )
        self.lock = self.root / "uv.lock"
        self.lock.write_text("v1", encoding="utf-8")
        self.claude_md = self.root / "CLAUDE.md"
        self.claude_md.write_text("# conventions\n", encoding="utf-8")

        # user config: has language/notes_dir (+ a custom comment) but NOT the newer fields
        self.user_cfg_path = self.root / "config.yaml"
        self.user_cfg_path.write_text(
            "# 我自己加的注释，别动\nlanguage: zh\nnotes_dir: notes\n", encoding="utf-8"
        )
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

    def test_links_skills_and_writes_new_config_keys(self):
        report, _ = migrate.run_migrate(self.cfg, scope="project")
        self.assertTrue((self.root / ".claude" / "skills" / "search").is_symlink())
        self.assertTrue((self.root / ".agents" / "skills" / "search").is_symlink())
        self.assertTrue((self.root / "AGENTS.md").is_symlink())
        # 2 skills x 2 dirs + AGENTS.md = 5 new links
        self.assertEqual(len(report.linked), 5)
        # experiments_dir + new_field + remotes are in example but not in user config -> appended
        for k in ("experiments_dir", "new_field", "remotes"):
            self.assertIn(k, report.config_fields_written)
        self.assertNotIn("language", report.config_fields_written)

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
        state = self.root / ".helix" / "state.json"  # runtime data stays at base_dir, not workspace/
        self.assertTrue(state.exists())

    def test_config_fields_appended_with_comments_and_placeholder(self):
        migrate.run_migrate(self.cfg, scope="project")
        text = self.user_cfg_path.read_text(encoding="utf-8")
        # field names present
        self.assertIn("experiments_dir: experiments", text)
        self.assertIn("new_field:", text)
        # template comments copied verbatim
        self.assertIn("# 实验工作区根目录（与 notes 平级）", text)
        self.assertIn("# 一个带注释的标量新字段", text)
        # nested block copied whole
        self.assertIn("remotes:", text)
        self.assertIn("    host: gpu-a100", text)
        # marker header present
        self.assertIn("helix migrate 按模板补充", text)

    def test_user_content_preserved(self):
        original = self.user_cfg_path.read_text(encoding="utf-8")
        migrate.run_migrate(self.cfg, scope="project")
        after = self.user_cfg_path.read_text(encoding="utf-8")
        # append-only: the original text is an exact prefix of the result (comment + lines untouched)
        self.assertTrue(after.startswith(original))
        self.assertIn("# 我自己加的注释，别动", after)

    def test_backup_created_equals_original(self):
        original = self.user_cfg_path.read_text(encoding="utf-8")
        migrate.run_migrate(self.cfg, scope="project")
        bak = self.root / "config.yaml.bak"
        self.assertTrue(bak.exists())
        self.assertEqual(bak.read_text(encoding="utf-8"), original)

    def test_append_is_idempotent(self):
        migrate.run_migrate(self.cfg, scope="project")
        after_first = self.user_cfg_path.read_text(encoding="utf-8")
        # second run: user now has the fields, nothing more to append
        report, _ = migrate.run_migrate(self.cfg, scope="project")
        self.assertEqual(report.config_fields_written, [])
        self.assertEqual(self.user_cfg_path.read_text(encoding="utf-8"), after_first)

    def test_no_missing_no_write_no_backup(self):
        # user config already has everything the example does
        self.user_cfg_path.write_text(
            "language: zh\nnotes_dir: notes\nexperiments_dir: x\nnew_field: y\nremotes: {}\n",
            encoding="utf-8",
        )
        before = self.user_cfg_path.read_text(encoding="utf-8")
        report, _ = migrate.run_migrate(self.cfg, scope="project")
        self.assertEqual(report.config_fields_written, [])
        self.assertFalse((self.root / "config.yaml.bak").exists())
        self.assertEqual(self.user_cfg_path.read_text(encoding="utf-8"), before)

    def test_extract_field_block_scalar_and_nested(self):
        ex = self.example.read_text(encoding="utf-8")
        scalar = migrate._extract_field_block(ex, "experiments_dir")
        self.assertIn("# 实验工作区根目录（与 notes 平级）", scalar)
        self.assertIn("experiments_dir: experiments", scalar)
        nested = migrate._extract_field_block(ex, "remotes")
        self.assertIn("remotes:", nested)
        self.assertIn("    remote_repro_root: /data/exp", nested)
        self.assertEqual(migrate._extract_field_block(ex, "nonexistent"), "")

    def test_repro_move_pending_without_yes(self):
        # legacy repro/ present; without --yes it's only reported, never moved
        legacy = self.root / "repro" / "domX" / "paperY"
        legacy.mkdir(parents=True)
        (legacy / "plan.md").write_text("plan", encoding="utf-8")
        report, _ = migrate.run_migrate(self.cfg, scope="project", do_move=False)
        self.assertTrue(report.repro_rename_pending)
        self.assertFalse(report.repro_renamed)
        self.assertTrue((self.root / "repro").exists())          # untouched
        self.assertFalse((self.root / "experiments").exists())

    def test_repro_move_with_yes_preserves_all_files(self):
        legacy = self.root / "repro" / "domX" / "paperY"
        legacy.mkdir(parents=True)
        (legacy / "plan.md").write_text("plan", encoding="utf-8")
        (legacy / "setup.md").write_text("setup", encoding="utf-8")
        report, _ = migrate.run_migrate(self.cfg, scope="project", do_move=True)
        self.assertTrue(report.repro_renamed)
        self.assertFalse((self.root / "repro").exists())         # source removed after verify
        # legacy repro/ (at base) moves to experiments_path, which now lives under workspace/
        moved = self.root / "workspace" / "experiments" / "domX" / "paperY"
        self.assertTrue((moved / "plan.md").exists())
        self.assertTrue((moved / "setup.md").exists())           # nothing lost

    def test_repro_move_skips_when_target_exists(self):
        (self.root / "repro" / "d").mkdir(parents=True)
        (self.root / "repro" / "d" / "plan.md").write_text("x", encoding="utf-8")
        (self.root / "workspace" / "experiments").mkdir(parents=True)  # target already there
        report, _ = migrate.run_migrate(self.cfg, scope="project", do_move=True)
        self.assertFalse(report.repro_renamed)                   # refuses to merge/overwrite
        self.assertTrue((self.root / "repro").exists())          # source preserved

    def test_results_md_upgraded_to_index(self):
        ws = self.root / "workspace" / "experiments" / "d" / "p"  # experiments live under workspace/
        ws.mkdir(parents=True)
        (ws / "results.md").write_text("old results", encoding="utf-8")
        report, _ = migrate.run_migrate(self.cfg, scope="project")
        self.assertFalse((ws / "results.md").exists())
        self.assertEqual((ws / "results" / "index.md").read_text(encoding="utf-8"), "old results")
        self.assertTrue(report.results_upgraded)

    def test_workspace_migrate_pending_without_yes(self):
        # old layout: notes/ + experiments/ at base_dir, not under workspace/
        (self.root / "notes" / "papers").mkdir(parents=True)
        (self.root / "notes" / "papers" / "a.md").write_text("note", encoding="utf-8")
        (self.root / "experiments" / "d").mkdir(parents=True)
        report, _ = migrate.run_migrate(self.cfg, scope="project", do_move=False)
        self.assertTrue(report.workspace_migrate_pending)
        self.assertFalse(report.workspace_migrated)
        self.assertTrue((self.root / "notes").exists())          # untouched without --yes
        self.assertFalse((self.root / "workspace" / "notes").exists())

    def test_workspace_migrate_moves_and_preserves(self):
        self.cfg.notes_dir = "notes"   # relative -> should be moved under workspace/ (setUp uses absolute)
        (self.root / "notes" / "papers").mkdir(parents=True)
        (self.root / "notes" / "papers" / "a.md").write_text("note", encoding="utf-8")
        (self.root / "experiments" / "d").mkdir(parents=True)
        (self.root / "experiments" / "d" / "plan.md").write_text("plan", encoding="utf-8")
        report, _ = migrate.run_migrate(self.cfg, scope="project", do_move=True)
        self.assertIn("notes", report.workspace_migrated)
        self.assertIn("experiments", report.workspace_migrated)
        # sources gone, data preserved under workspace/
        self.assertFalse((self.root / "notes").exists())
        self.assertFalse((self.root / "experiments").exists())
        self.assertTrue((self.root / "workspace" / "notes" / "papers" / "a.md").exists())
        self.assertTrue((self.root / "workspace" / "experiments" / "d" / "plan.md").exists())

    def test_workspace_migrate_idempotent(self):
        (self.root / "experiments" / "d").mkdir(parents=True)
        (self.root / "experiments" / "d" / "plan.md").write_text("plan", encoding="utf-8")
        migrate.run_migrate(self.cfg, scope="project", do_move=True)
        report, _ = migrate.run_migrate(self.cfg, scope="project", do_move=True)
        self.assertEqual(report.workspace_migrated, [])          # nothing left to move
        self.assertFalse(report.workspace_migrate_pending)

    def test_helix_stays_at_base_not_moved(self):
        # .helix (index/cache — runtime data) stays at base_dir, never moved into workspace/
        (self.root / ".helix").mkdir()
        (self.root / ".helix" / "index.db").write_text("INDEX", encoding="utf-8")
        (self.root / "experiments" / "d").mkdir(parents=True)
        report, _ = migrate.run_migrate(self.cfg, scope="project", do_move=True)
        self.assertNotIn(".helix", report.workspace_migrated)
        self.assertTrue((self.root / ".helix" / "index.db").exists())          # stays put
        self.assertFalse((self.root / "workspace" / ".helix" / "index.db").exists())

    def test_absolute_notes_dir_not_moved(self):
        # notes_dir points at an external absolute path -> notes stays external, only experiments moves
        ext = self.root / "external_vault"
        (ext / "papers").mkdir(parents=True)
        (ext / "papers" / "a.md").write_text("note", encoding="utf-8")
        self.cfg.notes_dir = str(ext)
        (self.root / "experiments" / "d").mkdir(parents=True)
        report, _ = migrate.run_migrate(self.cfg, scope="project", do_move=True)
        self.assertNotIn("notes", report.workspace_migrated)     # external vault untouched
        self.assertTrue((ext / "papers" / "a.md").exists())


if __name__ == "__main__":
    unittest.main()
