"""No-root unit tests for optional terminal, lab and VNC components."""
from __future__ import annotations
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from llmsetup.components import ALL, DESCRIPTIONS, INSTALLERS
from llmsetup.core import SetupError
from llmsetup import component_optional_tools as modules

class FakeRunner:
    def __init__(self):
        self.commands = []
        self.packages = []
        self.writes = []
        self.accounts = []
    def apt(self, *pkgs): self.packages.extend(pkgs)
    def run(self, cmd, **kwargs):
        self.commands.append(list(cmd))
        return mock.Mock(stdout='', returncode=0)
    def write(self, path, content, **kwargs):
        self.writes.append((str(path), content))
        return True
    def account(self, user, **kwargs):
        self.accounts.append(user)

class RegistryTests(unittest.TestCase):
    def test_all_modules_registered_and_described(self):
        required = ['fish','btop','mc','ttyd','agent_of_empires','jupyterlab','vnc','novnc']
        for name in required:
            self.assertIn(name, ALL)
            self.assertIn(name, DESCRIPTIONS)
            self.assertTrue(callable(INSTALLERS[name]))
        self.assertEqual(set(ALL), set(INSTALLERS))

    def test_safe_selected_defaults(self):
        config = json.loads((Path(__file__).resolve().parents[1] / 'config.json').read_text())
        for module in ('fish','btop','mc'):
            self.assertIn(module, config['components'])
        for module in ('ttyd','agent_of_empires','jupyterlab','vnc','novnc'):
            self.assertNotIn(module, config['components'])

    def test_unchanged_coreutils_distribution(self):
        self.assertEqual(modules.TTYD_TAG, '1.7.7')
        self.assertEqual(modules.AOE_TAG, 'v1.17.2')

class ChecksumTests(unittest.TestCase):
    def test_release_url_validation(self):
        asset={'name':'ttyd.x86_64','browser_download_url':'https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64'}
        self.assertTrue(modules._safe_release_url('tsl0922/ttyd', asset, '1.7.7'))
        self.assertFalse(modules._safe_release_url('another/repo',asset,'1.7.7'))
        self.assertFalse(modules._safe_release_url('tsl0922/ttyd',asset,'2.0'))

    def test_sumfile_line(self):
        c='a'*64
        text=c+'  ttyd.x86_64\n'+'b'*64+'  ttyd.arm\n'
        self.assertEqual(modules._checksum_line(text,'ttyd.x86_64'),c)

    def test_checksum_mismatch_name_fails(self):
        with self.assertRaises(SetupError):
            modules._checksum_line('a'*64+' ttyd.arm\n','ttyd.x86_64')

    def test_duplicate_checksums_fail(self):
        with self.assertRaises(SetupError):
            modules._checksum_line(('a'*64+' ttyd.x86_64\n')*2,'ttyd.x86_64')

    def test_bare_digest(self):
        self.assertEqual(modules._checksum_line('c'*64+'\n','archive.tar.gz'),'c'*64)

    def test_unverified_release_refused(self):
        r=mock.Mock()
        r.get_json.return_value={'draft': False,'prerelease': False,'tag_name':'1.7.7','assets':[{
          'name':'ttyd.x86_64',
          'browser_download_url':'https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64'
        }]}
        with self.assertRaises(SetupError):
            modules._release_binary(r,'tsl0922/ttyd','ttyd.x86_64','/tmp/test',tag='1.7.7')
        r.download.assert_not_called()

    def test_direct_api_digest_used(self):
        with tempfile.TemporaryDirectory() as d:
            r=mock.Mock()
            target=Path(d)/'ttyd'
            r.get_json.return_value={'draft':False,'prerelease':False,'tag_name':'1.7.7','assets':[{
              'name':'ttyd.x86_64','digest':'sha256:'+'f'*64,
              'browser_download_url':'https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64'
            }]}
            r.download.return_value=Path(d)/'cached'
            self.assertEqual(modules._release_binary(r,'tsl0922/ttyd','ttyd.x86_64',target,tag='1.7.7'),
                             r.download.return_value)
            self.assertEqual(r.download.call_args.args[1], 'f'*64)

    def test_untrusted_symlink_destination(self):
        with tempfile.TemporaryDirectory() as d:
            src=BytesIO(b'a'*11000)
            original=Path(d)/'original'
            original.write_bytes(b'keep')
            destination=Path(d)/'link'
            destination.symlink_to(original)
            with self.assertRaises(SetupError):
                modules._atomic_binary_from_stream(src,destination)
            self.assertEqual(original.read_bytes(),b'keep')

class ToolInstallTests(unittest.TestCase):
    def test_apt_utilities(self):
        for name in ('fish','btop','mc'):
            r=FakeRunner()
            getattr(modules,name)(r,{},None)
            self.assertEqual(r.packages,[name])
            self.assertFalse(r.commands)

    def test_no_service_start_for_disabled_template(self):
        with mock.patch('llmsetup.component_optional_tools.Path', wraps=Path):
            r=FakeRunner()
            modules._disabled_systemd_unit(r,'llm-demo.service','[Unit]\nDescription=Test')
            self.assertEqual([cmd[0] for cmd in r.commands],['systemd-analyze','systemctl'])
            self.assertEqual(r.commands[-1][1],'daemon-reload')
            self.assertNotIn('enable',sum(r.commands,[]))
            self.assertNotIn('start',sum(r.commands,[]))

    def test_vnc_only_installs_and_provisions(self):
        r=FakeRunner()
        with mock.patch.object(modules,'_disabled_systemd_unit') as unit:
            modules.vnc(r,{},None)
            unit.assert_called_once()
            self.assertEqual(unit.call_args.args[1], 'llm-vnc@.service')
            self.assertIn('-localhost yes', unit.call_args.args[2])
            self.assertIn('VncAuth', unit.call_args.args[2])
            self.assertIn('xfce4', r.packages)
            self.assertFalse(r.commands)

    def test_novnc_requires_manual_activation(self):
        r=FakeRunner()
        with mock.patch.object(modules,'_disabled_systemd_unit') as unit:
            modules.novnc(r,{},None)
            unit.assert_called_once()
            self.assertIn('127.0.0.1:6080', unit.call_args.args[2])
            self.assertIn('127.0.0.1:5901', unit.call_args.args[2])
            self.assertEqual(r.packages,['novnc','websockify'])
            self.assertFalse(r.commands)

    def test_jupyter_dedicated_user_and_token(self):
        r=FakeRunner()
        with mock.patch.object(modules,'ensure_dir'), \
             mock.patch('llmsetup.component_base.unit') as unit:
            modules.jupyterlab(r,{},None)
        self.assertIn('llmjupyter',r.accounts)
        self.assertIn('jupyterlab',r.packages)
        self.assertIn('127.0.0.1',unit.call_args.args[2])
        self.assertNotIn('token=',unit.call_args.args[2])
        self.assertNotIn('allow_root',unit.call_args.args[2])

if __name__=='__main__':
    unittest.main()
