"""GPU Lab regression tests: rootless design, opt-in behavior, safe argv and reports."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from llmsetup.core import SetupError
from llmsetup import gpu_lab, inventory
from llmsetup.components import ALL, DESCRIPTIONS, INSTALLERS
from llmsetup.install_stages import STAGE_BY_COMPONENT


class FakeRunner:
    def __init__(self):
        self.pkgs, self.commands, self.files = [], [], []
    def apt(self, *pkgs):
        self.pkgs.extend(pkgs)
    def run(self, command, **kwargs):
        self.commands.append(command)
    def write(self, path, content, **kwargs):
        self.files.append((str(path), content, kwargs))


class GpuLabTests(unittest.TestCase):
    def test_optional_stage_and_registry(self):
        self.assertIn("gpu_lab", ALL)
        self.assertEqual(STAGE_BY_COMPONENT["gpu_lab"], 2)
        self.assertIn("Distrobox", DESCRIPTIONS["gpu_lab"])
        self.assertIs(INSTALLERS["gpu_lab"], gpu_lab.gpu_lab)
        cfg = json.loads((Path(__file__).parent.parent / "config.json").read_text())
        self.assertNotIn("gpu_lab", cfg["components"])

    def test_install_adds_packages_and_account_without_container_side_effects(self):
        r = FakeRunner()
        user = SimpleNamespace(pw_uid=1002, pw_dir=str(gpu_lab.LAB_HOME))
        with mock.patch.object(gpu_lab.pwd, "getpwnam", side_effect=[KeyError, user]), \
             mock.patch.object(gpu_lab.grp, "getgrnam", return_value=object()), \
             mock.patch.object(Path, "exists", return_value=False), \
             mock.patch.object(Path, "is_symlink", return_value=False), \
             mock.patch.object(Path, "is_dir", return_value=True):
            gpu_lab.gpu_lab(r, {}, None)
        self.assertIn("distrobox", r.pkgs)
        self.assertIn("podman", r.pkgs)
        self.assertIn("crun", r.pkgs)
        self.assertTrue(any(cmd[0] == "useradd" for cmd in r.commands))
        self.assertTrue(any(cmd[0] == "usermod" for cmd in r.commands))
        self.assertTrue(any(path.endswith("gpu-lab.conf") for path, _, _ in r.files))
        self.assertFalse(any("distrobox" in cmd or "podman" in cmd for cmd in r.commands))
        self.assertFalse(any(cmd[0] == "systemctl" for cmd in r.commands))

    def test_rejects_unexpected_preexisting_account(self):
        r = FakeRunner()
        with mock.patch.object(gpu_lab.pwd, "getpwnam",
                               return_value=SimpleNamespace(pw_uid=0, pw_dir="/root")):
            with self.assertRaises(SetupError):
                gpu_lab.gpu_lab(r, {}, None)
        self.assertEqual(r.files, [])

    def test_profile_args_never_rootful_or_privileged(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            cpu = gpu_lab.create_args("llm-cpu", home)
            gpu = gpu_lab.create_args("llm-vulkan", home)
        self.assertIn("--home", cpu)
        self.assertEqual(cpu[cpu.index("--image") + 1], gpu_lab.IMAGE)
        self.assertNotIn("--additional-flags", cpu)
        self.assertIn("--device=/dev/dri", gpu[-1])
        self.assertIn("--group-add=keep-groups", gpu[-1])
        self.assertIn("--runtime=crun", gpu[-1])
        for args in (cpu, gpu):
            self.assertNotIn("--root", args)
            self.assertNotIn("--privileged", " ".join(args))
        with self.assertRaises(SetupError):
            gpu_lab.create_args("unsafe", home)

    def test_preexisting_box_is_not_overwritten(self):
        with mock.patch.object(gpu_lab.shutil, "which", return_value="/usr/bin/tool"), \
             mock.patch.object(gpu_lab.subprocess, "run",
                               return_value=SimpleNamespace(returncode=0)), \
             mock.patch.object(gpu_lab, "_run") as runner:
            gpu_lab._create("llm-cpu")
            runner.assert_not_called()

    def test_benchmark_cpu_and_gpu_profiles_have_distinct_layer_counts(self):
        model = Path("/example/test.gguf")
        self.assertEqual(gpu_lab.benchmark_args(model, 0)[-3:], ["0", "-o", "json"])
        self.assertEqual(gpu_lab.benchmark_args(model, 99)[-3:], ["99", "-o", "json"])
        with self.assertRaises(SetupError):
            gpu_lab.benchmark_args(model, -1)

    def test_benchmark_writes_separate_private_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "model.gguf"
            model.write_bytes(b"dummy")
            bench = Path(directory) / "llama-bench"
            bench.write_text("binary placeholder")
            ui = SimpleNamespace(ask=lambda _: str(model))
            with mock.patch.object(gpu_lab, "LLAMA_BENCH", bench), \
                 mock.patch.object(gpu_lab.Path, "home", return_value=Path(directory)), \
                 mock.patch.object(gpu_lab, "_run", return_value='{"test":true}') as run:
                gpu_lab._benchmark(ui)
            output = sorted((Path(directory) / "gpu-lab-results").glob("*.json"))
            self.assertEqual(len(output), 2)
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in output))
            self.assertEqual([c.args[0][-3] for c in run.call_args_list], ["0", "99"])

    def test_root_is_refused(self):
        with mock.patch.object(gpu_lab.os, "geteuid", return_value=0):
            with self.assertRaises(SetupError):
                gpu_lab.gpu_lab_menu(None)

    def test_inventory_does_not_claim_gpu_offload(self):
        self.assertIn("gpu_lab", inventory.INSTALL)
        self.assertNotIn("gpu_lab", inventory.RUNTIME_UNITS)


if __name__ == "__main__":
    unittest.main()
