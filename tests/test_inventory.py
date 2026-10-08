"""Regression tests for software inventory: read-only, no false configured claims."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from unittest import mock
import unittest

from llmsetup import cli, inventory
from llmsetup.components import ALL
from llmsetup.install_stages import STAGES


class FakeProbe:
    def __init__(self):
        self.binaries = set()
        self.files = set()
        self.dirs = set()
        self.packages = set()
        self.matches = set()
        self.units = set()
        self.enabled_units = set()
        self.active_units = set()
        self.contents = {}
        self.commands = {}
        self.models = None
        self.events = []

    def binary(self, name):
        self.events.append(('binary', name))
        return name in self.binaries

    def file(self, name):
        self.events.append(('file', str(name)))
        return str(name) in self.files

    def directory(self, name):
        self.events.append(('directory', str(name)))
        return str(name) in self.dirs

    def package(self, name):
        self.events.append(('package', name))
        return name in self.packages

    def match(self, glob):
        self.events.append(('match', glob))
        return glob in self.matches

    def text(self, name):
        self.events.append(('text', str(name)))
        return self.contents.get(str(name))

    def unit(self, name):
        self.events.append(('unit', name))
        return name in self.units

    def enabled(self, name):
        self.events.append(('enabled', name))
        return name in self.enabled_units

    def active(self, name):
        self.events.append(('active', name))
        return name in self.active_units

    def command(self, args, timeout=3):
        self.events.append(('command', tuple(args)))
        return self.commands.get(tuple(args), (False, ''))

    def model_names(self):
        self.events.append(('models',))
        return self.models


class StatusTests(unittest.TestCase):
    def test_all_39_modules_have_detection_rules(self):
        self.assertEqual(set(inventory.INSTALL), set(ALL))
        self.assertEqual(len(inventory.INSTALL),39)
        states=inventory.scan(ALL,{},FakeProbe())
        self.assertEqual(set(states),set(ALL))
        self.assertTrue(all(isinstance(state, inventory.ComponentState)
                            for state in states.values()))

    def test_not_installed_is_not_configured(self):
        state=inventory.inspect('ollama',{},FakeProbe())
        self.assertEqual(state.status,'NOT INSTALLED')
        self.assertFalse(state.installed)
        self.assertFalse(state.configured)
        self.assertIsNone(state.running)

    def test_configured_only_when_binary_removed_but_unit_remains(self):
        p=FakeProbe()
        p.units.add('llm-ollama.service')
        p.contents['/etc/systemd/system/llm-ollama.service'] = '# Managed by debian-llm-postinstall'
        p.contents['/etc/llm-postinstall/ollama.env'] = 'OLLAMA_HOST=127.0.0.1:11434'
        state=inventory.inspect('ollama',{},p)
        self.assertEqual(state.status,'CONFIGURED ONLY')
        self.assertEqual(state.short,'CONFIG ONLY')
        self.assertFalse(state.installed)
        self.assertTrue(state.configured)

    def test_installed_only_when_unit_and_local_env_missing(self):
        p=FakeProbe()
        p.files.add('/opt/llm-stack/ollama/current/bin/ollama')
        state=inventory.inspect('ollama',{},p)
        self.assertEqual(state.status,'INSTALLED ONLY')
        self.assertFalse(state.configured)
        self.assertFalse(state.running)

    def test_installed_and_configured_when_managed_unit_and_env_present(self):
        p=FakeProbe()
        p.files.add('/opt/llm-stack/ollama/current/bin/ollama')
        p.units.add('llm-ollama.service')
        p.contents['/etc/systemd/system/llm-ollama.service'] = '# Managed by debian-llm-postinstall\n...'
        p.contents['/etc/llm-postinstall/ollama.env'] = (
            '# Managed by debian-llm-postinstall\nOLLAMA_HOST=127.0.0.1:11434')
        p.active_units.add('llm-ollama.service')
        state=inventory.inspect('ollama',{},p)
        self.assertEqual(state.status,'INSTALLED + CONFIGURED')
        self.assertTrue(state.running)
        self.assertEqual(state.short,'CONFIGURED')

    def test_configured_not_necessarily_running(self):
        p=FakeProbe()
        p.files.add('/opt/llm-stack/bin/ttyd')
        p.units.add('llm-ttyd.service')
        p.contents['/etc/systemd/system/llm-ttyd.service']='# Managed by debian-llm-postinstall'
        state=inventory.inspect('ttyd',{},p)
        self.assertEqual(state.status,'INSTALLED + CONFIGURED')
        self.assertIsNone(state.running) # intentionally disabled ttyd has no runtime unit probe

    def test_per_user_configuration_is_not_guessed(self):
        p=FakeProbe();p.files.add('/opt/llm-stack/bin/opencode')
        state=inventory.inspect('opencode',{},p)
        self.assertEqual(state.status,'INSTALLED / SETUP UNVERIFIED')
        self.assertIsNone(state.configured)
        self.assertIn('authentication',state.details)

    def test_tailscale_enrollment_differentiated_from_installed(self):
        p=FakeProbe()
        p.binaries.add('tailscale')
        p.packages.add('tailscale')
        p.commands[('tailscale','status','--json')] = (True,'{"BackendState":"NeedsLogin"}')
        self.assertEqual(inventory.inspect('tailscale',{},p).status,'INSTALLED ONLY')
        p.commands[('tailscale','status','--json')] = (True,'{"BackendState":"Running"}')
        self.assertEqual(inventory.inspect('tailscale',{},p).status,'INSTALLED + CONFIGURED')
        p.commands[('tailscale','status','--json')] = (False,'')
        self.assertEqual(inventory.inspect('tailscale',{},p).status,
                         'INSTALLED / SETUP UNVERIFIED')

    def test_unreachable_model_backend_is_unknown_not_missing(self):
        p=FakeProbe()
        p.files.add('/usr/local/bin/ollama')
        self.assertEqual(inventory.inspect('models',{'model':'qwen2.5-coder:7b'},p).status,
                         'UNVERIFIED')
        p.models={'qwen2.5-coder:7b'}
        st=inventory.inspect('models',{'model':'qwen2.5-coder:7b'},p)
        self.assertTrue(st.installed)
        self.assertTrue(st.configured)
        self.assertEqual(st.status,'INSTALLED + CONFIGURED')
        p.models={'tinyllama:latest'}
        self.assertEqual(inventory.inspect('models',{'model':'qwen2.5-coder:7b'},p).status,
                         'NOT INSTALLED')

    def test_action_not_conflated_with_installed_software(self):
        p=FakeProbe()
        self.assertEqual(inventory.inspect('preflight',{},p).status,'ACTION PENDING')
        p.files.add('/var/log/llm-postinstall/preflight.txt')
        self.assertEqual(inventory.inspect('preflight',{},p).status,'ACTION DONE')
        self.assertEqual(inventory.inspect('config_snapshot',{},p).status,'ACTION PENDING')
        p.matches.add('/var/backups/llm-postinstall/snapshots/um780-config-*.tar.gz')
        self.assertEqual(inventory.inspect('config_snapshot',{},p).status,'ACTION DONE')

    def test_commented_or_duplicate_ollama_environment_is_not_configured(self):
        p=FakeProbe()
        p.files.add('/opt/llm-stack/ollama/current/bin/ollama')
        p.units.add('llm-ollama.service')
        p.contents['/etc/systemd/system/llm-ollama.service']='# Managed by debian-llm-postinstall'
        env='/etc/llm-postinstall/ollama.env'
        p.contents[env]='# OLLAMA_HOST=127.0.0.1:11434\\nOLLAMA_HOST=0.0.0.0:11434'
        self.assertEqual(inventory.inspect('ollama',{},p).status,'INSTALLED ONLY')
        p.contents[env]='OLLAMA_HOST=127.0.0.1:11434\\nOLLAMA_HOST=0.0.0.0:11434'
        self.assertEqual(inventory.inspect('ollama',{},p).status,'INSTALLED ONLY')

    def test_llama_model_must_exist_inside_managed_gguf_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'models'
            gguf=root/'gguf'
            gguf.mkdir(parents=True)
            p=FakeProbe()
            p.files.add('/opt/llm-stack/llama.cpp/build/bin/llama-server')
            p.units.add('llm-llama.service')
            p.contents['/etc/systemd/system/llm-llama.service']='# Managed by debian-llm-postinstall'
            env='/etc/llm-postinstall/llama.env'
            model=gguf/'test.gguf'
            p.contents[env]='LLAMA_MODEL='+str(model)
            self.assertEqual(inventory.inspect('llama',{'model_storage':str(root)},p).status,
                             'INSTALLED ONLY')
            model.write_bytes(b'mocked GGUF header')
            self.assertEqual(inventory.inspect('llama',{'model_storage':str(root)},p).status,
                             'INSTALLED + CONFIGURED')

    def test_cockpit_plugin_page_does_not_imply_user_auth(self):
        p=FakeProbe()
        p.files.add('/usr/share/cockpit/ghsync/manifest.json')
        st=inventory.inspect('cockpit_ghsync',{},p)
        self.assertEqual(st.status,'INSTALLED ONLY')
        p.files.add('/etc/llm-postinstall/cockpit-ghsync.json')
        st=inventory.inspect('cockpit_ghsync',{},p)
        self.assertEqual(st.status,'INSTALLED + CONFIGURED')
        self.assertIn('per-user',st.details)

    def test_missing_config_cannot_be_both(self):
        p=FakeProbe()
        p.files.update(('/usr/share/cockpit/cockpit-bookmarks/manifest.json',))
        st=inventory.inspect('cockpit_bookmarks',{},p)
        self.assertEqual(st.status,'INSTALLED ONLY')
        p.contents['/etc/cockpit/cockpit-bookmarks.json']='{"services":[]}'
        st=inventory.inspect('cockpit_bookmarks',{},p)
        self.assertEqual(st.status,'INSTALLED + CONFIGURED')

    def test_model_probe_is_direct_loopback_only(self):
        fake_response=mock.Mock()
        fake_response.status=200
        fake_response.getheader.return_value=None
        fake_response.read.return_value=b'{"models":[{"name":"qwen2.5-coder:7b"}]}'
        fake_connection=mock.Mock()
        fake_connection.getresponse.return_value=fake_response
        with mock.patch.object(inventory.http.client,'HTTPConnection',return_value=fake_connection) as conn:
            result=inventory.LocalProbe().model_names()
        conn.assert_called_once_with('127.0.0.1',11434,timeout=1.2)
        fake_connection.request.assert_called_once_with('GET','/api/tags')
        fake_connection.close.assert_called_once()
        self.assertEqual(result,{'qwen2.5-coder:7b'})

    def test_model_probe_returns_unknown_on_unreachable_socket(self):
        connection=mock.Mock()
        connection.request.side_effect=ConnectionRefusedError()
        with mock.patch.object(inventory.http.client,'HTTPConnection',return_value=connection):
            self.assertIsNone(inventory.LocalProbe().model_names())
        connection.close.assert_called_once()

    def test_no_secret_is_exposed_in_json_output(self):
        p=FakeProbe()
        p.binaries.add('code-server')
        p.units.add('llm-codeserver.service')
        p.contents['/etc/systemd/system/llm-codeserver.service'] = (
            '# Managed by debian-llm-postinstall\nExecStart=code-server --bind-addr 127.0.0.1:8443')
        p.contents['/etc/llm-postinstall/codeserver.env']='PASSWORD=SUPER_SECRET'
        state=inventory.inspect('codeserver',{},p)
        output=io.StringIO()
        with redirect_stdout(output):
            inventory.render({'codeserver':state},json_mode=True)
        payload=json.loads(output.getvalue())
        self.assertNotIn('SUPER_SECRET',output.getvalue())
        self.assertTrue(payload['codeserver']['configured'])

    def test_read_only_no_mutating_commands(self):
        p=FakeProbe()
        inventory.scan(ALL,{},p)
        all_commands=[event[1] for event in p.events if event[0]=='command']
        for args in all_commands:
            self.assertNotIn(args[0],('apt-get','mount','systemctl enable','tee','curl'))
            self.assertNotIn('restart', args)
            self.assertNotIn('install', args)


class InventoryCLITests(unittest.TestCase):
    def setUp(self):
        self.conf=json.loads((Path(__file__).parents[1]/'config.json').read_text())

    def test_inventory_reports_all_categories_not_only_defaults(self):
        output=io.StringIO()
        with mock.patch.object(cli.inventory,'scan',side_effect=lambda names,cfg: {
                name:inventory.ComponentState(name,False,False,None,'test') for name in names}) as scanner, \
             redirect_stdout(output):
            result=cli.main(['--inventory'])
        self.assertEqual(result,0)
        self.assertEqual(len(scanner.call_args.args[0]),39)
        self.assertIn('novnc',output.getvalue())
        self.assertIn('MISSING',output.getvalue())

    def test_inventory_json_only_one_module(self):
        output=io.StringIO()
        with mock.patch.object(cli.inventory,'scan',return_value={
            'btop':inventory.ComponentState('btop',True,True,None,'no setup')}) as scanner, \
             redirect_stdout(output):
            result=cli.main(['--inventory','--json','--component','btop'])
        self.assertEqual(result,0)
        self.assertEqual(scanner.call_args.args[0],['btop'])
        self.assertEqual(json.loads(output.getvalue())['btop']['status'],
                         'INSTALLED + CONFIGURED')

    def test_inventory_stage_includes_unchecked_optional_tools(self):
        output=io.StringIO()
        with mock.patch.object(cli.inventory,'scan',return_value={}) as scanner, \
             redirect_stdout(output):
            result=cli.main(['--inventory','--stage','4'])
        self.assertEqual(result,0)
        self.assertEqual(scanner.call_args.args[0],list(STAGES[3].components))
        self.assertIn('novnc',scanner.call_args.args[0])

    def test_json_without_inventory_rejected(self):
        stream=io.StringIO()
        with mock.patch('sys.stderr',stream):
            result=cli.main(['--json','--plan'])
        self.assertEqual(result,1)
        self.assertIn('inventory',stream.getvalue())

if __name__ == '__main__':
    unittest.main()
