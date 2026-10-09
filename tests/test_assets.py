"""Release asset helper call contract."""
from __future__ import annotations

import unittest
from unittest import mock

import llmsetup.core  # noqa: F401  (assets must load via core: circular import)
from llmsetup import assets


class InstallReleaseAssetTests(unittest.TestCase):
    def test_callers_need_only_repo_and_asset_name(self):
        r = mock.Mock()
        r.download.return_value = '/var/cache/llm-postinstall/v1-x.tar.gz'
        with mock.patch.object(assets, 'github_asset',
                               return_value=('v1', 'https://github.com/o/r/releases/download/v1/x.tar.gz', 'a' * 64)):
            tag, out = assets.install_release_asset(r, 'o/r', 'x.tar.gz')
        self.assertEqual(tag, 'v1')
        self.assertEqual(out, '/var/cache/llm-postinstall/v1-x.tar.gz')


if __name__ == '__main__':
    unittest.main()
