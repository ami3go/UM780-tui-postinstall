"""Tests for strict opt-in preflight, checksum snapshots and Cockpit status."""
import json
from pathlib import Path
import os
import tempfile
import unittest
from unittest import mock

from llmsetup import component_safety as safety
from llmsetup.components import ALL, INSTALLERS, DESCRIPTIONS
from llmsetup.core import SetupError


class SafetyTests(unittest.TestCase):
    def test_unselected_and_ordered_before_mutation(self):
        config=json.loads((Path(__file__).parents[1]/'config.json').read_text())
        for name in ('preflight','config_snapshot','cockpit_status'):
            self.assertIn(name,ALL)
            self.assertIn(name,INSTALLERS)
            self.assertIn(name,DESCRIPTIONS)
            self.assertNotIn(name,config['components'])
        self.assertLess(ALL.index('preflight'), ALL.index('storage'))
        self.assertLess(ALL.index('config_snapshot'), ALL.index('storage'))

    def test_real_allowlist(self):
        self.assertTrue(safety._allowed_snapshot_path('/etc/llm-postinstall/ollama.env'))
        self.assertTrue(safety._allowed_snapshot_path('/etc/cockpit/cockpit-bookmarks.json'))
        self.assertTrue(safety._allowed_snapshot_path('/etc/systemd/system/llm-novnc.service'))
        for path in ('/etc/passwd','/home/test/.ssh/id_rsa','/etc/systemd/system/ssh.service',
                     '/etc/llm-postinstall/../shadow','/opt/llm-stack/test',
                     '/etc/systemd/system/llm-../../etc/passwd'):
            self.assertFalse(safety._allowed_snapshot_path(path))

    def test_build_and_parse_integrity(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'token'
            p.write_text('sensitive\n')
            p.chmod(0o600)
            archive=Path(root)/'file.tar.gz'
            with mock.patch.object(safety,'_allowed_snapshot_path',side_effect=lambda s: str(s)==str(p)):
                manifest=safety.build_snapshot(archive,[p])
                decoded=safety.parse_snapshot(archive)
            self.assertEqual(decoded,[(p,b'sensitive\n',0o600)])
            self.assertIn(str(p),manifest['files'])
            self.assertEqual(archive.stat().st_mode & 0o777,0o600)

    def test_no_overwrite_existing_archive(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'f';p.write_text('hello')
            dest=Path(root)/'existing.tar.gz';dest.write_text('KEEP')
            with mock.patch.object(safety,'_allowed_snapshot_path',return_value=True):
                with self.assertRaises(SetupError):safety.build_snapshot(dest,[p])
            self.assertEqual(dest.read_text(),'KEEP')

    def test_symlink_source_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'secret';p.write_text('SECRET')
            link=Path(root)/'link';link.symlink_to(p)
            with mock.patch.object(safety,'_allowed_snapshot_path',return_value=True):
                with self.assertRaises(SetupError):
                    safety.build_snapshot(Path(root)/'file.tar.gz',[link])

    def test_restoration_requires_literal_confirmation(self):
        with self.assertRaises(SetupError):
            safety.restore_config_snapshot('/var/backups/llm-postinstall/snapshots/anything.tar.gz','yes')

    def test_manual_restore_creates_before_state(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            p=root/'config';p.write_text('old');p.chmod(0o600)
            archive=root/'snap.tar.gz'
            with mock.patch.object(safety,'_allowed_snapshot_path',side_effect=lambda s:str(s)==str(p)), \
                 mock.patch.object(safety,'SNAPSHOT_ROOT',root):
                safety.build_snapshot(archive,[p])
                p.write_text('new')
                restored=safety.restore_config_snapshot(archive,'RESTORE')
            self.assertEqual(restored,1)
            self.assertEqual(p.read_text(),'old')
            self.assertEqual(len(list(root.glob('before-restore-*.tar.gz'))),1)

    def test_cockpit_status_requires_private_cockpit(self):
        with mock.patch('llmsetup.component_safety.Path.is_file',return_value=False):
            with self.assertRaises(SetupError):
                safety.cockpit_status(mock.Mock(),{},None)

    def test_status_assets_are_static_and_no_privileged_actions(self):
        base=safety.STATUS_ASSETS
        js=(base/'status.js').read_text()
        manifest=json.loads((base/'manifest.json').read_text())
        self.assertIn('tools',manifest)
        self.assertIn('superuser: null',js)
        for forbidden in ("'restart'",'"restart"',"'enable'",'"enable"', 'innerHTML'):
            self.assertNotIn(forbidden,js)


if __name__ == '__main__':
    unittest.main()
