"""OpenHands opt-in, no-secrets, no-LAN-exposure integration tests."""
import json
from pathlib import Path
import unittest
from unittest import mock

from llmsetup import component_openhands as oh
from llmsetup.components import ALL, INSTALLERS
from llmsetup.core import SetupError
from llmsetup.component_bookmarks_auto import desired_entries


class OpenHandsTests(unittest.TestCase):
    def test_optional_and_registered(self):
        cfg = json.loads((Path(__file__).parents[1] / 'config.json').read_text())
        self.assertIn('openhands', ALL)
        self.assertIn('openhands', INSTALLERS)
        self.assertNotIn('openhands', cfg['components'])
        self.assertEqual(oh.options(cfg), (3002, True, 'qwen2.5-coder:7b'))

    def test_ports_and_bad_models_are_rejected(self):
        for port in (0, 3000, 3001, 11435, True, 65536, '3002'):
            with self.assertRaises(SetupError):
                oh.options({'openhands': {'port': port}})
        for model in ('bad model', '\nEVIL=1', '', '../' + 'x' * 200):
            with self.assertRaises(SetupError):
                oh.options({'openhands': {'local_model': model}})
        with self.assertRaises(SetupError):
            oh.options({'openhands': {'ollama_bridge': 'false'}})

    def test_gateway_validation(self):
        self.assertEqual(oh.docker_gateway('172.17.0.1\n'), '172.17.0.1')
        for value in ('', '127.0.0.1', '8.8.8.8', '::1', 'oops'):
            with self.assertRaises(SetupError):
                oh.docker_gateway(value)

    def test_declining_consent_never_installs_or_runs_docker(self):
        r = mock.Mock()
        ui = mock.Mock()
        ui.confirm.return_value = False
        with self.assertRaisesRegex(SetupError, 'consent declined'):
            oh._ensure_docker(r, ui)
        r.apt.assert_not_called()
        r.run.assert_not_called()

    def test_docker_absent_requires_separate_install_consent(self):
        r = mock.Mock()
        ui = mock.Mock()
        ui.confirm.side_effect = [True, False]
        with mock.patch.object(oh.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(SetupError, 'installation declined'):
                oh._ensure_docker(r, ui)
        r.apt.assert_not_called()

    def test_service_loopback_and_no_credentials(self):
        r = mock.Mock()
        ui = mock.Mock()
        with mock.patch.object(oh, '_check_port'), \
             mock.patch.object(oh, '_ensure_docker'), \
             mock.patch.object(oh, '_bridge', return_value='172.17.0.1'), \
             mock.patch.object(oh, 'ensure_dir'), \
             mock.patch.object(oh.Path, 'is_file', return_value=True), \
             mock.patch.object(oh.Path, 'is_symlink', return_value=False), \
             mock.patch.object(oh, 'unit') as unit:
            oh.openhands(r, {'openhands': {'port': 3002}}, ui)
        app_unit = next(call for call in unit.call_args_list if call.args[1] == oh.UNIT).args[2]
        self.assertIn('127.0.0.1:3002:3000', app_unit)
        self.assertIn('/var/run/docker.sock', app_unit)
        self.assertIn('--pull=never', app_unit)
        self.assertNotIn('OPENAI_API_KEY', app_unit)
        self.assertNotIn('ANTHROPIC_API_KEY', app_unit)
        self.assertNotIn('0.0.0.0:3002', app_unit)
        self.assertEqual(sum(1 for call in r.run.call_args_list if call.args[0][0:2] == ['docker','pull']), 2)

    def test_bridge_bind_gateway_not_all_addresses(self):
        r=mock.Mock()
        r.run.return_value=mock.Mock(stdout='172.17.0.1\n')
        with mock.patch.object(oh.Path, 'is_file', return_value=True), \
             mock.patch.object(oh.Path, 'is_symlink', return_value=False), \
             mock.patch.object(oh, 'unit') as unit:
            result=oh._bridge(r)
        self.assertEqual(result, '172.17.0.1')
        content=unit.call_args.args[2]
        self.assertIn('bind=172.17.0.1', content)
        self.assertNotIn('bind=0.0.0.0', content)

    def test_bookmark_uses_separate_web_port(self):
        entries=desired_entries(exists=lambda p:p.endswith('llm-openhands.service'),
                                command_exists=lambda x:False)
        app=next(e for e in entries if e['id']=='um780-openhands')
        self.assertEqual(app['url'],'http://127.0.0.1:3002/')
        self.assertIn('SSH',app['description'])

if __name__ == '__main__':
    unittest.main()
