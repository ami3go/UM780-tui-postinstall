"""Pure and mocked regression tests for optional first-party Cockpit extensions."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from llmsetup.component_cockpit_plugins import (
    BOOKMARKS_REPOSITORY, GHSYNC_REPOSITORY, GHSYNC_SHA,
    _ghsync_stage_files, _read_state, _state_text, cockpit_bookmarks,
    select_bookmarks_asset,
)
from llmsetup.components import ALL, INSTALLERS
from llmsetup.core import SetupError
from llmsetup.cli import load_config


def release(*, digest=None, url=None, prerelease=False, tag='v0.7.1', name='cockpit-bookmarks_0.7.1-1_all.deb'):
    digest = digest if digest is not None else 'sha256:' + 'a' * 64
    url = url if url is not None else f'https://github.com/ami3go/bookmarks/releases/download/{tag}/{name}'
    return {'tag_name': tag, 'prerelease': prerelease, 'draft': False,
            'assets': [{'name': name, 'digest': digest, 'browser_download_url': url}]}


class PluginConfigurationTests(unittest.TestCase):
    def test_registered(self):
        self.assertIn('cockpit_ghsync', ALL)
        self.assertIn('cockpit_bookmarks', ALL)
        self.assertTrue(callable(INSTALLERS['cockpit_ghsync']))
        self.assertTrue(callable(INSTALLERS['cockpit_bookmarks']))
        self.assertLess(ALL.index('cockpit'), ALL.index('cockpit_ghsync'))
        self.assertLess(ALL.index('cockpit_ghsync'), ALL.index('cockpit_bookmarks'))

    def test_both_selected_by_default(self):
        cfg = json.loads((Path(__file__).resolve().parents[1] / 'config.json').read_text())
        self.assertIn('cockpit_ghsync', cfg['components'])
        self.assertIn('cockpit_bookmarks', cfg['components'])

    def test_ghsync_source_is_immutable_commit(self):
        self.assertEqual(GHSYNC_REPOSITORY, 'https://github.com/ami3go/ghsync.git')
        self.assertRegex(GHSYNC_SHA, r'^[0-9a-f]{40}$')
        self.assertEqual(BOOKMARKS_REPOSITORY, 'ami3go/bookmarks')


class BookmarksReleaseTests(unittest.TestCase):
    def test_valid_verified_asset(self):
        name, url, digest, tag = select_bookmarks_asset(release())
        self.assertEqual(tag, 'v0.7.1')
        self.assertEqual(digest, 'a' * 64)
        self.assertIn('/ami3go/bookmarks/releases/download/', url)
        self.assertTrue(name.endswith('_all.deb'))

    def test_digest_required(self):
        with self.assertRaises(SetupError):
            select_bookmarks_asset(release(digest=''))

    def test_digest_malformed(self):
        with self.assertRaises(SetupError):
            select_bookmarks_asset(release(digest='sha256:not-a-digest'))

    def test_prerelease_disallowed(self):
        with self.assertRaises(SetupError):
            select_bookmarks_asset(release(prerelease=True))

    def test_duplicate_package_fails(self):
        r = release()
        r['assets'].append(r['assets'][0])
        with self.assertRaises(SetupError):
            select_bookmarks_asset(r)

    def test_foreign_download_host_rejected(self):
        with self.assertRaises(SetupError):
            select_bookmarks_asset(release(url='https://attacker.invalid/payload.deb'))

    def test_no_package_fail_closed(self):
        with self.assertRaises(SetupError):
            select_bookmarks_asset(release(name='cockpit-bookmarks.tar.gz'))

    def test_existing_package_does_not_download(self):
        class R:
            def run(self, args, **kwargs):
                return mock.Mock(returncode=0, stdout='install ok installed')
            def get_json(self, *_):
                raise AssertionError('No request for already installed package')
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'manifest.json').write_text('{}')
            with mock.patch('llmsetup.component_cockpit_plugins._check_cockpit'):
                with mock.patch('llmsetup.component_cockpit_plugins.BOOKMARKS_DIR', base):
                    cockpit_bookmarks(R(), {}, None)


class GitHubSyncStagingTests(unittest.TestCase):
    def prepare(self, root):
        rels = [
            'usr/local/bin/ghsync', 'usr/local/bin/ghsync-thirdparty',
            'usr/local/bin/ghsync-maintenance',
            'usr/share/cockpit/ghsync/manifest.json',
            'usr/share/metainfo/io.github.ami3go.ghsync.metainfo.xml',
        ]
        for rel in rels:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('dummy')
        return rels

    def test_requires_complete_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rels = self.prepare(root)
            self.assertEqual(set(_ghsync_stage_files(root)), set(rels))
            (root / rels[0]).unlink()
            with self.assertRaises(SetupError):
                _ghsync_stage_files(root)

    def test_rejects_unexpected_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            (root / 'usr/local/bin/unsafe').write_text('bad')
            with self.assertRaises(SetupError):
                _ghsync_stage_files(root)

    def test_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            link = root / 'usr/share/cockpit/ghsync/link'
            link.symlink_to('/etc/passwd')
            with self.assertRaises(SetupError):
                _ghsync_stage_files(root)

    def test_state_marker_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'state'
            p.write_text('{"status":"installed"}')
            with self.assertRaises(SetupError):
                _read_state(p)

    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'state'
            s = {'status':'installed', 'source_sha': GHSYNC_SHA, 'files': {'x': 'hash'}}
            p.write_text(_state_text(s))
            self.assertEqual(_read_state(p), s)

    def test_state_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'target').write_text(_state_text({'status': 'installed'}))
            (root / 'link').symlink_to(root / 'target')
            with self.assertRaises(SetupError):
                _read_state(root / 'link')


if __name__ == '__main__':
    unittest.main()
