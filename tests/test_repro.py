"""Reproduction planning: VRAM estimation + hardware grading + skeleton generation + config parsing unit tests."""

import tempfile
import unittest
from pathlib import Path

from helix import repro
from helix.config import Config, HardwareProfile, load_config


class TestEstimateVram(unittest.TestCase):
    def test_7b_fp16_weights(self):
        # 7B fp16 weights ≈ 7e9 × 2 / 1024^3 ≈ 13.04 GB
        est = repro.estimate_vram(7, "fp16", ctx=1, batch=1)
        self.assertAlmostEqual(est.weights_gb, 7e9 * 2 / (1024 ** 3), places=2)
        self.assertGreater(est.total_gb, est.weights_gb)  # includes KV + overhead

    def test_dtype_halves(self):
        fp16 = repro.estimate_vram(7, "fp16", ctx=1)
        int8 = repro.estimate_vram(7, "int8", ctx=1)
        self.assertAlmostEqual(int8.weights_gb, fp16.weights_gb / 2, places=2)

    def test_kv_scales_with_ctx_and_batch(self):
        small = repro.estimate_vram(7, "fp16", ctx=1024, batch=1)
        big = repro.estimate_vram(7, "fp16", ctx=1024, batch=8)
        self.assertAlmostEqual(big.kv_cache_gb, small.kv_cache_gb * 8, places=1)

    def test_explicit_arch_not_approximate(self):
        est = repro.estimate_vram(7, "fp16", num_layers=32, hidden=4096)
        self.assertFalse(est.approximate)

    def test_inferred_arch_approximate(self):
        est = repro.estimate_vram(7, "fp16")
        self.assertTrue(est.approximate)

    def test_bad_dtype_raises(self):
        with self.assertRaises(ValueError):
            repro.estimate_vram(7, "fp13")

    def test_nonpositive_params_raises(self):
        with self.assertRaises(ValueError):
            repro.estimate_vram(0)


class TestFitCheck(unittest.TestCase):
    def setUp(self):
        self.a100 = HardwareProfile("a100-40g", "A100-40GB", 40, 1)
        self.h20 = HardwareProfile("h20-96g", "H20", 96, 1)
        self.a100x4 = HardwareProfile("a100x4", "A100-40GB", 40, 4, "NVLink")

    def test_7b_fits_single_a100(self):
        est = repro.estimate_vram(7, "fp16", ctx=2048, batch=1)
        fit = repro.fit_check(est, self.a100)
        self.assertEqual(fit.verdict, "fits_single")

    def test_70b_fp16_needs_quant_on_h20(self):
        est = repro.estimate_vram(70, "fp16", ctx=2048, batch=1)
        fit = repro.fit_check(est, self.h20)
        self.assertIn(fit.verdict, ("needs_quant", "needs_offload"))
        self.assertTrue(fit.suggestions)  # has a downgrade ladder

    def test_multi_gpu_tp(self):
        # 70B fp16 ≈ 130GB; won't fit on a single 40G card but 4×40G=160G is enough → TP
        est = repro.estimate_vram(70, "fp16", ctx=1, batch=1)
        fit = repro.fit_check(est, self.a100x4)
        self.assertEqual(fit.verdict, "fits_multi_tp")
        self.assertGreater(fit.tp_gpus, 1)

    def test_fit_check_all_covers_all_profiles(self):
        cfg = Config(hardware_profiles=[self.a100, self.h20])
        est = repro.estimate_vram(7, "fp16")
        fits = repro.fit_check_all(est, cfg)
        self.assertEqual({f.profile for f in fits}, {"a100-40g", "h20-96g"})


class TestShortName(unittest.TestCase):
    def test_colon_head(self):
        self.assertEqual(repro.short_name("Pythia: Exploiting Workflow"), "Pythia")

    def test_no_colon_first_words(self):
        name = repro.short_name("Response Length Perception and Sequence Scheduling")
        self.assertTrue(name.startswith("Response_Length"))

    def test_empty(self):
        self.assertEqual(repro.short_name(""), "untitled")


class TestWorkspaceSkeleton(unittest.TestCase):
    def test_repro_creates_full_skeleton(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Config(notes_dir="notes", experiments_dir="experiments", _path=Path(d) / "config.yaml")
            ws, created = repro.build_experiment_workspace(
                "Test Paper", "papers/X/Test", "X", "test", cfg, kind="repro", draft=False,
            )
            self.assertEqual(
                set(created),
                {"setup.md", "plan.md", "results/index.md", "RESULTS_LAYOUT.md", "sync.yaml"},
            )
            self.assertTrue((ws / "setup.md").exists())
            self.assertTrue((ws / "results" / "index.md").exists())
            self.assertTrue((ws / "RESULTS_LAYOUT.md").exists())
            self.assertIn("experiments", str(ws))
            # results/index.md carries type:repro in frontmatter
            from helix import frontmatter
            fm = frontmatter.meta((ws / "results" / "index.md").read_text(encoding="utf-8"))
            self.assertEqual(fm.get("type"), "repro")

    def test_mine_has_no_setup(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Config(experiments_dir="experiments", _path=Path(d) / "config.yaml")
            ws, created = repro.build_experiment_workspace(
                "我的对比实验", "papers/X/Base", "X", "my-exp", cfg, kind="mine",
            )
            self.assertNotIn("setup.md", created)
            self.assertFalse((ws / "setup.md").exists())
            self.assertIn("plan.md", created)
            from helix import frontmatter
            fm = frontmatter.meta((ws / "results" / "index.md").read_text(encoding="utf-8"))
            self.assertEqual(fm.get("type"), "mine")

    def test_bad_kind_raises(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Config(_path=Path(d) / "config.yaml")
            with self.assertRaises(ValueError):
                repro.build_experiment_workspace("T", "n", "X", "t", cfg, kind="bogus")

    def test_sync_yaml_always_includes_results_layout(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Config(_path=Path(d) / "config.yaml")
            ws, _ = repro.build_experiment_workspace("T", "n", "X", "t", cfg, kind="repro")
            import yaml as _yaml
            spec = _yaml.safe_load((ws / "sync.yaml").read_text(encoding="utf-8"))
            self.assertIn("RESULTS_LAYOUT.md", spec["push"])
            self.assertTrue(all(p.startswith("results/") for p in spec["pull"]))

    def test_draft_goes_to_draft_notes(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Config(_path=Path(d) / "config.yaml")
            ws, _ = repro.build_experiment_workspace(
                "T", "papers/X/T", "X", "t", cfg, kind="repro", draft=True,
            )
            self.assertIn("draft_notes", str(ws))

    def test_skip_existing_without_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Config(_path=Path(d) / "config.yaml")
            repro.build_experiment_workspace("T", "n", "X", "t", cfg, kind="repro")
            _, created = repro.build_experiment_workspace("T", "n", "X", "t", cfg, kind="repro")
            self.assertEqual(created, [])  # already exists, skipped


class TestConfigHardwareProfiles(unittest.TestCase):
    def test_parse_profiles(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.yaml"
            cfg_path.write_text(
                "experiments_dir: experiments\n"
                "hardware_profiles:\n"
                "  a100-40g:\n"
                "    gpu_model: A100-40GB\n"
                "    vram_gb: 40\n"
                "    num_gpus: 1\n"
                "    interconnect: PCIe\n",
                encoding="utf-8",
            )
            cfg = load_config(str(cfg_path))
            self.assertEqual(cfg.experiments_dir, "experiments")
            self.assertEqual(len(cfg.hardware_profiles), 1)
            p = cfg.find_profile("a100-40g")
            self.assertIsNotNone(p)
            self.assertEqual(p.vram_gb, 40)
            self.assertEqual(p.total_vram_gb, 40)

    def test_missing_profiles_ok(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.yaml"
            cfg_path.write_text("language: zh\n", encoding="utf-8")
            cfg = load_config(str(cfg_path))
            self.assertEqual(cfg.hardware_profiles, [])
            self.assertEqual(cfg.experiments_dir, "experiments")  # default value

    def test_legacy_repro_dir_still_read(self):
        # backward compat: an old config.yaml with repro_dir maps onto experiments_dir
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.yaml"
            cfg_path.write_text("repro_dir: repro\n", encoding="utf-8")
            cfg = load_config(str(cfg_path))
            self.assertEqual(cfg.experiments_dir, "repro")

    def test_parse_remotes(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.yaml"
            cfg_path.write_text(
                "remotes:\n"
                "  gpu-a100:\n"
                "    host: gpu-a100\n"
                "    remote_repro_root: /data/helix-experiments\n"
                "    hardware_profile: a100-8x40g\n",
                encoding="utf-8",
            )
            cfg = load_config(str(cfg_path))
            r = cfg.find_remote("gpu-a100")
            self.assertIsNotNone(r)
            self.assertEqual(r.remote_repro_root, "/data/helix-experiments")
            self.assertIsNone(cfg.find_remote("nope"))


if __name__ == "__main__":
    unittest.main()
