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


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tree = {'blockdevices': [
            {'path':'/dev/nvme0n1','type':'disk','children':[
                {'path':'/dev/nvme0n1p1','type':'part','fstype':'ext4','uuid':'root-id','mountpoint':'/'}]},
            {'path':'/dev/nvme1n1','type':'disk','children':[
                {'path':'/dev/nvme1n1p1','type':'part','fstype':'ext4','uuid':'data-id','mountpoint':None}]}
        ]}

    def test_proposes_existing_second_ssd_only(self):
        opts = partition_options(self.tree)
        self.assertEqual([x['uuid'] for x in opts], ['data-id'])

    def test_no_root_detection_returns_no_proposals(self):
        self.tree['blockdevices'][0]['children'][0]['mountpoint'] = None
        self.assertEqual(partition_options(self.tree), [])

    def test_mounted_secondary_partition_skipped(self):
        self.tree['blockdevices'][1]['children'][0]['mountpoint'] = '/mnt/data'
        self.assertEqual(partition_options(self.tree), [])

    def test_only_known_filesystems(self):
        self.tree['blockdevices'][1]['children'][0]['fstype'] = 'crypto_LUKS'
        self.assertEqual(partition_options(self.tree), [])

    def test_disallows_second_partition_on_root_disk(self):
        self.tree['blockdevices'][0]['children'].append({'path':'/dev/nvme0n1p2','type':'part','fstype':'ext4','uuid':'other'})
        self.assertEqual(len(partition_options(self.tree)), 1)

    def test_missing_uuid_rejected(self):
        self.tree['blockdevices'][1]['children'][0]['uuid'] = ''
        self.assertEqual(partition_options(self.tree), [])

    def test_fstab_entry_never_formats(self):
        line = fstab_entry({'uuid':'abc-def','fs':'ext4'})
        self.assertIn('UUID=abc-def', line)
        self.assertIn('nofail', line)
        self.assertNotIn('mkfs', line)

    def test_invalid_uuid_rejected(self):
        with self.assertRaises(SetupError):
            fstab_entry({'uuid':'abc\nfoo','fs':'ext4'})


class TestCore(unittest.TestCase):
    def test_command_shell_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            r = Runner(Path(t)/'log')
            with self.assertRaises(ValueError):
                r.run('rm -rf /')

    def test_write_requires_marker_for_managed_files(self):
        with tempfile.TemporaryDirectory() as t:
            r = Runner(Path(t)/'log')
            with self.assertRaises(SetupError):
                r.write(Path(t)/'test', 'unmanaged content')

    def test_write_is_idempotent(self):
        with tempfile.TemporaryDirectory() as t:
            r = Runner(Path(t)/'log')
            p = Path(t)/'test'
            self.assertTrue(r.write(p, managed('first')))
            self.assertFalse(r.write(p, managed('first')))

    def test_cannot_replace_unmanaged_file(self):
        with tempfile.TemporaryDirectory() as t:
            r = Runner(Path(t)/'log')
            p = Path(t)/'test'; p.write_text('other owner')
            with self.assertRaises(SetupError):
                r.write(p, managed('bad'))
            self.assertEqual(p.read_text(), 'other owner')

    def test_cannot_follow_symlink(self):
        with tempfile.TemporaryDirectory() as t:
            r = Runner(Path(t)/'log')
            target = Path(t)/'target'; target.write_text('dont touch')
            link = Path(t)/'link'; link.symlink_to(target)
            with self.assertRaises(SetupError):
                r.write(link, managed('bad'))
            self.assertEqual(target.read_text(), 'dont touch')

    def test_secret_keeps_value_across_reruns(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)/'key'
            self.assertEqual(stable_secret(p), stable_secret(p))
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_secret_fails_for_symlink(self):
        with tempfile.TemporaryDirectory() as t:
            a = Path(t)/'a'; a.write_text('hello')
            b = Path(t)/'b'; b.symlink_to(a)
            with self.assertRaises(SetupError):
                stable_secret(b)

    def test_digest_missing_does_not_download(self):
        with tempfile.TemporaryDirectory() as t:
            r = Runner(Path(t)/'log')
            with self.assertRaises(SetupError):
                r.download('https://example.invalid/file', None, Path(t)/'file')

    def test_github_asset_requires_checksum(self):
        with tempfile.TemporaryDirectory() as t:
            r = Runner(Path(t)/'log')
            r.get_json = lambda url: {'tag_name':'v1','assets':[{'name':'a','browser_download_url':'https://example.invalid/a'}]}
            with self.assertRaises(SetupError):
                github_asset(r, 'some/repo', 'a')

    def test_github_asset_with_digest(self):
        with tempfile.TemporaryDirectory() as t:
            r = Runner(Path(t)/'log')
            r.get_json = lambda url: {'tag_name':'v1','assets':[{'name':'a','digest':'sha256:'+'a'*64,'browser_download_url':'https://github.com/some/repo/releases/download/v1/a'}]}
            self.assertEqual(github_asset(r, 'some/repo', 'a')[2], 'a'*64)

    def test_safe_gguf_requires_existing_inside_root(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)/'gguf'; root.mkdir()
            inside = root/'qwen.gguf'; inside.write_bytes(b'abc')
            outside = Path(t)/'oops.gguf'; outside.write_bytes(b'abc')
            self.assertTrue(safe_model(str(inside), root))
            self.assertFalse(safe_model(str(outside), root))
            self.assertFalse(safe_model(str(root/'missing.gguf'), root))

    def test_runner_redacts_secret_command_logs(self):
        with tempfile.TemporaryDirectory() as t:
            log = Path(t)/'log'; r = Runner(log)
            r.run(['echo', 'FAKE_PASSWORD_123'], secret=True)
            self.assertNotIn('FAKE_PASSWORD_123', log.read_text())
