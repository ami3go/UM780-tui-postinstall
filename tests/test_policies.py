import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
from llmsetup.core import (Runner, SetupError, github_asset, safe_model, sha256, stable_secret, OWNER_MARK)
from llmsetup.components import ALL, DESCRIPTIONS, managed
from llmsetup.storage import partition_options, fstab_entry
from llmsetup.cli import load_config, UI, plan


class TestCli(unittest.TestCase):
    def test_load_config_rejects_unknown(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t)/'c.json'
            path.write_text(json.dumps({'target_os':'debian-13','host':'bare-metal','components':['fake']}))
            with self.assertRaises(SetupError): load_config(path)

    def test_load_config_rejects_other_distro(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t)/'c.json'
            path.write_text(json.dumps({'target_os':'ubuntu','host':'bare-metal','components':[]}))
            with self.assertRaises(SetupError): load_config(path)

    def test_default_components_have_descriptions(self):
        self.assertEqual(set(ALL), set(DESCRIPTIONS))

    def test_plan_does_not_invoke_commands(self):
        with mock.patch('subprocess.run', side_effect=AssertionError('unexpected command')):
            with mock.patch('sys.stdout', new_callable=io.StringIO) as stdout:
                plan({'model_storage':'/tmp'}, ['base', 'ollama'])
                self.assertIn('NO repartition', stdout.getvalue())

if __name__ == '__main__':
    unittest.main()

class TestSecurity(unittest.TestCase):
    def test_public_bind_detection(self):
        from llmsetup.health import public_bindings
        ss = '''LISTEN 0 4096 0.0.0.0:11434 0.0.0.0:*\nLISTEN 0 128 127.0.0.1:3000 0.0.0.0:*\nLISTEN 0 128 [::]:8443 [::]:*\nLISTEN 0 10 0.0.0.0:2222 0.0.0.0:*'''
        self.assertEqual({x[0] for x in public_bindings(ss)}, {11434, 8443})

    def test_all_localhost_listeners_pass(self):
        from llmsetup.health import public_bindings
        self.assertEqual(public_bindings('LISTEN 0 2048 127.0.0.1:11434 0.0.0.0:*'), [])

    def test_model_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)/'models'; root.mkdir()
            outside = Path(t)/'escape.gguf'; outside.write_bytes(b'abc')
            link = root/'link.gguf'; link.symlink_to(outside)
            self.assertFalse(safe_model(str(link), root))

    def test_log_is_root_private_even_with_permissive_umask(self):
        with tempfile.TemporaryDirectory() as t:
            old = os.umask(0)
            try:
                r = Runner(Path(t)/'log')
            finally:
                os.umask(old)
            self.assertEqual(r.log_path.stat().st_mode & 0o777, 0o600)

class TestDiskSafety(unittest.TestCase):
    def test_download_rejects_missing_disk_capacity(self):
        with tempfile.TemporaryDirectory() as t:
            r = Runner(Path(t) / 'log')
            with mock.patch('llmsetup.core.shutil.disk_usage', return_value=mock.Mock(free=0)):
                with self.assertRaisesRegex(SetupError, 'Insufficient free space'):
                    r.download('https://example.invalid/data', 'a' * 64, Path(t) / 'file')

    def test_runner_applies_file_mode_on_idempotent_write(self):
        with tempfile.TemporaryDirectory() as t:
            r = Runner(Path(t)/'log')
            file = Path(t)/'config'
            r.write(file, managed('secret'), mode=0o644)
            self.assertFalse(r.write(file, managed('secret'), mode=0o600))
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)

class TestPersistentStorage(unittest.TestCase):
    def test_persisted_second_ssd_survives_single_component_rerun(self):
        with tempfile.TemporaryDirectory() as t:
            config = Path(t)/'config.json'
            config.write_text(json.dumps({'target_os':'debian-13','host':'bare-metal',
                'components':['ollama'],'model_storage':'/var/lib/llm-stack/models'}))
            etc = Path(t)/'etc'; etc.mkdir()
            (etc/'storage.json').write_text(json.dumps({'model_storage':'/srv/llm-data/models'}))
            with mock.patch('llmsetup.cli.CONF_DIR', etc):
                self.assertEqual(load_config(config)['model_storage'], '/srv/llm-data/models')

    def test_persisted_storage_rejects_unmanaged_path(self):
        with tempfile.TemporaryDirectory() as t:
            config = Path(t)/'config.json'
            config.write_text(json.dumps({'target_os':'debian-13','host':'bare-metal','components':['ollama']}))
            etc = Path(t)/'etc'; etc.mkdir()
            (etc/'storage.json').write_text(json.dumps({'model_storage':'/home/user'}))
            with mock.patch('llmsetup.cli.CONF_DIR', etc):
                with self.assertRaises(SetupError): load_config(config)
