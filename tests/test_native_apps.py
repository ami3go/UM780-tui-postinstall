"""Optional native application install and security boundaries."""
import json
from pathlib import Path
from unittest import mock
import unittest

from llmsetup.components import ALL, INSTALLERS
from llmsetup import component_native_apps as apps
from llmsetup.core import SetupError
from llmsetup.component_bookmarks_auto import desired_entries


class NativeAppsTests(unittest.TestCase):
    def test_all_five_registered_but_unselected(self):
        selected=json.loads((Path(__file__).parents[1]/'config.json').read_text())['components']
        for name in ('opencode','llama_swap','uptime_kuma','secure_ingress','ups_wol'):
            self.assertIn(name, ALL)
            self.assertIn(name, INSTALLERS)
            self.assertNotIn(name, selected)

    def test_uptime_requires_node_20_4(self):
        for v in ('', 'v18.0.1','20.3.9','abc'):
            with self.assertRaises(SetupError):
                apps.validate_kuma_node(v)
        for v in ('v20.4.0','v22.12.1'):
            apps.validate_kuma_node(v)

    def test_kuma_release_pinned_workaround(self):
        self.assertEqual(apps.KUMA_TAG,'2.5.0')
        self.assertEqual(apps.KUMA_REPO,'https://github.com/louislam/uptime-kuma.git')

    def test_no_tailscale_fails_without_enrollment(self):
        with mock.patch.object(apps.shutil,'which',return_value=None):
            with self.assertRaises(SetupError): apps.secure_ingress(mock.Mock(),{},None)

    def test_nonrunning_tailscale_fails_closed(self):
        r=mock.Mock()
        r.run.return_value=mock.Mock(returncode=0,stdout='{"BackendState":"NeedsLogin"}')
        with mock.patch.object(apps.shutil,'which',return_value='/usr/bin/tailscale'):
            with self.assertRaises(SetupError): apps.secure_ingress(r,{},None)
        self.assertEqual(r.run.call_count,1)

    def test_connected_tailscale_never_publishes(self):
        r=mock.Mock()
        r.run.return_value=mock.Mock(returncode=0,stdout='{"BackendState":"Running"}')
        with mock.patch.object(apps.shutil,'which',return_value='/usr/bin/tailscale'):
            apps.secure_ingress(r,{},None)
        self.assertEqual(r.run.call_count,1)
        self.assertEqual(r.run.call_args.args[0],['tailscale','status','--json'])

    def test_opencode_no_root_daemon(self):
        r=mock.Mock()
        with mock.patch.object(apps,'_verified_tar_command',return_value=Path('/opt/llm-stack/bin/opencode')) as ver, \
             mock.patch.object(apps,'_symlink_cli') as sym:
            apps.opencode(r,{},None)
        self.assertTrue(ver.called)
        self.assertEqual(sym.call_args.args[1],'opencode')
        r.service.assert_not_called()

    def test_llama_swap_not_started_automatically(self):
        r=mock.Mock()
        with mock.patch.object(apps,'_verified_tar_command',return_value=Path('/opt/llm-stack/bin/llama-swap')), \
             mock.patch.object(apps,'_symlink_cli'):
            apps.llama_swap(r,{},None)
        r.service.assert_not_called()

    def test_ups_repo_preparation_not_auto_install(self):
        self.assertIn('cockpit-ups-wol',apps.UPS_REPO)
        self.assertIn('dry-run',apps.ups_wol.__doc__ or '')

    def test_bookmarks_for_kuma_and_opencode(self):
        entries=desired_entries(
            exists=lambda p:p.endswith('llm-uptime-kuma.service') or p.endswith('/bin/ttyd'),
            command_exists=lambda c:c=='opencode')
        self.assertEqual({entry['name'] for entry in entries},{'Uptime Kuma','OpenCode'})
        web=next(e for e in entries if e['name']=='Uptime Kuma')
        self.assertEqual(web['url'],'http://127.0.0.1:3001/')
        shell=next(e for e in entries if e['name']=='OpenCode')
        self.assertEqual(shell['gottyLauncher']['address'],'127.0.0.1')


if __name__=='__main__':
    unittest.main()
