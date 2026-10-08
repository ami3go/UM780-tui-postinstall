"""Cockpit Bookmarks automatic app discovery/merge safety contract."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from llmsetup.component_bookmarks_auto import (
    WEB_APPS, BOOKMARKS_CONFIG, _read_config, _used_ports,
    _atomic_save, config_template, desired_entries, merge_bookmarks,
    sync_bookmarks, auto_sync_bookmarks,
)
from llmsetup import component_bookmarks_auto as bm
from llmsetup.components import ALL, INSTALLERS
from llmsetup.core import SetupError


class RegistryTests(unittest.TestCase):
    def test_component_available(self):
        self.assertIn('bookmark_sync', ALL)
        self.assertIs(INSTALLERS['bookmark_sync'], bm.bookmark_sync)

    def test_automatic_enabled_by_default(self):
        data = json.loads((Path(__file__).resolve().parents[1] / 'config.json').read_text())
        self.assertIs(data['auto_bookmarks'], True)

    def test_no_unwanted_wan_urls(self):
        for item in WEB_APPS:
            self.assertTrue(item[3].startswith('http://127.0.0.1:'))


class DiscoveryTests(unittest.TestCase):
    def test_novnc_bookmark_shows_secret_location_but_not_secret(self):
        from llmsetup.component_bookmarks_auto import desired_entries
        entries=desired_entries(exists=lambda p: p.endswith('llm-novnc.service'),
                                command_exists=lambda _:False)
        self.assertEqual([e['name'] for e in entries], ['noVNC Desktop'])
        card=entries[0]
        self.assertEqual(card['url'],'http://127.0.0.1:6080/vnc.html')
        self.assertIn('/etc/llm-postinstall/novnc-vnc-password', card['description'])
        self.assertNotIn('password=',card['url'])
        self.assertEqual(card['group'],'UM780 Web Apps')

    def test_web_apps_only_when_installed(self):
        entries = desired_entries(
            exists=lambda path: path.endswith('llm-webui.service'), command_exists=lambda _: False)
        self.assertEqual([e['name'] for e in entries], ['Open WebUI'])
        self.assertIn('SSH -L', entries[0]['description'])
        self.assertIs(entries[0]['statusCheck'], False)

    def test_clis_become_real_on_demand_bookmarks(self):
        entries = desired_entries(
            exists=lambda path: path == str(bm.TTDY_BINARY),
            command_exists=lambda cmd: cmd in ('fish', 'mc', 'aoe'))
        self.assertEqual({e['name'] for e in entries},
                         {'Fish Shell', 'Midnight Commander', 'Agent of Empires'})
        for entry in entries:
            self.assertEqual(entry['type'], 'gotty-launcher')
            self.assertEqual(entry['integration'], 'ttyd')
            self.assertEqual(entry['group'], 'Applications')
            self.assertEqual(entry['gottyLauncher']['provider'], 'ttyd')
            self.assertEqual(entry['gottyLauncher']['address'], '127.0.0.1')
            self.assertEqual(entry['gottyLauncher']['autoStopMinutes'], 30)
            self.assertIn('/cb-gotty-', entry['url'])
            self.assertTrue(entry['url'].startswith('http://127.0.0.1:'))
        self.assertEqual(len({e['gottyLauncher']['port'] for e in entries}), 3)

    def test_no_ttyd_means_no_terminal_launchers(self):
        entries = desired_entries(exists=lambda _: False,
                                  command_exists=lambda _: True)
        self.assertEqual(entries, [])

    def test_existing_port_is_not_reused(self):
        old = {'type':'gotty-launcher', 'name':'Custom','gottyLauncher': {'port':47200}}
        entries=desired_entries(exists=lambda path: path == str(bm.TTDY_BINARY),
                                command_exists=lambda c: c == 'fish',
                                services=[old])
        self.assertEqual(entries[0]['gottyLauncher']['port'],47201)


class MergeTests(unittest.TestCase):
    def test_preserves_existing_all_settings_history_and_custom_bookmarks(self):
        current = {**config_template(),
                   'schemaVersion': 2, 'title': 'My Mini PC',
                   'customFeature': {'value':'keep'},
                   'history':[{'id':'original','config':{'other':'data'}}],
                   'groupOrder':['Custom'],
                   'services':[{'id':'manual', 'name':'Custom UI',
                                'url':'http://example.test', 'group':'Custom'}]}
        proposed=[{'id':'um780-webui','name':'Open WebUI','url':'http://127.0.0.1:3000/',
                   'group':'UM780 Web Apps'}]
        updated, added=merge_bookmarks(current, proposed)
        self.assertEqual(added,['Open WebUI'])
        self.assertEqual(updated['title'],'My Mini PC')
        self.assertEqual(updated['history'],current['history'])
        self.assertEqual(updated['customFeature'],current['customFeature'])
        self.assertEqual(updated['services'][0],current['services'][0])
        self.assertEqual(updated['groupOrder'],['Custom','UM780 Web Apps'])
        self.assertEqual(len(current['services']),1)

    def test_second_run_is_idempotent(self):
        current=config_template()
        entry={'id':'um780-fish','name':'Fish Shell',
               'url':'http://127.0.0.1:47200/cb-gotty-um780-fish/','group':'Applications'}
        updated,_=merge_bookmarks(current,[entry])
        again,added=merge_bookmarks(updated,[entry])
        self.assertEqual(added,[])
        self.assertIs(again,updated)

    def test_user_modified_managed_card_is_preserved(self):
        old={'id':'um780-webui','name':'My Edited Open WebUI','url':'https://custom.test',
             'group':'Private', 'favorite':True}
        config={**config_template(),'services':[old]}
        new={'id':'um780-webui','name':'Open WebUI','url':'http://127.0.0.1:3000/',
             'group':'UM780 Web Apps'}
        output,added=merge_bookmarks(config,[new])
        self.assertEqual(added,[])
        self.assertEqual(output['services'],[old])

    def test_existing_manual_entry_prevents_duplicate_url(self):
        old={'id':'foo','name':'Internal Notebook','url':'http://127.0.0.1:8888/lab'}
        config={**config_template(),'services':[old]}
        new={'id':'um780-jupyterlab','name':'JupyterLab',
             'url':'http://127.0.0.1:8888/lab','group':'UM780 Web Apps'}
        _,added=merge_bookmarks(config,[new])
        self.assertEqual(added,[])


class ConfigSafetyTests(unittest.TestCase):
    def test_invalid_json_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'bookmarks.json'
            file.write_text('not-json')
            with self.assertRaises(SetupError): _read_config(file)
            self.assertEqual(file.read_text(),'not-json')

    def test_future_schema_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'bookmarks.json'
            file.write_text('{"schemaVersion":999,"services":[]}')
            with self.assertRaises(SetupError): _read_config(file)

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            dest=root/'real';dest.write_text('{"services":[]}')
            (root/'link').symlink_to(dest)
            with self.assertRaises(SetupError): _read_config(root/'link')

    def test_auto_sync_skip_if_not_installed(self):
        with mock.patch.object(bm, 'BOOKMARKS_PACKAGE', Path('/missing/bookmarks/manifest.json')):
            self.assertEqual(auto_sync_bookmarks(None,{},[]),[])

    def test_auto_sync_disabled_by_config(self):
        with mock.patch.object(bm,'BOOKMARKS_PACKAGE',Path('/missing/manifest.json')):
            self.assertEqual(auto_sync_bookmarks(None,{'auto_bookmarks':False},[]),[])

    def test_atomic_write_refuses_concurrent_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'config.json'
            file.write_text('{"schemaVersion":2,"services":[]}')
            before=file.read_bytes()
            file.write_text('{"schemaVersion":2,"services":[{"id":"another"}]}')
            with self.assertRaises(SetupError):
                _atomic_save(file, config_template(), before, file.stat(),
                             backup_dir=Path(tmp)/'backup')

    def test_end_to_end_merge_creates_backup_and_is_noop_on_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            file=root/'config.json'
            package=root/'manifest.json'
            package.write_text('{}')
            file.write_text(json.dumps({**config_template(),'title':'Retain Me',
                                        'services':[{'id':'personal','name':'My app','url':'https://example.org'}]}))
            originals=file.read_bytes()
            exists=lambda path: path.endswith('llm-webui.service')
            with mock.patch.object(bm,'LOCK_PATH',root/'lock'):
                changes=sync_bookmarks(config_path=file, package_path=package,
                                       exists=exists,command_exists=lambda _:False,
                                       backup_dir=root/'backups')
                self.assertEqual(changes,['Open WebUI'])
                result=json.loads(file.read_text())
                self.assertEqual(result['title'],'Retain Me')
                self.assertEqual(len(result['services']),2)
                backups=list((root/'backups').iterdir())
                self.assertEqual(len(backups),1)
                self.assertEqual(backups[0].read_bytes(),originals)
                updated=file.read_bytes()
                changes=sync_bookmarks(config_path=file, package_path=package,
                                       exists=exists,command_exists=lambda _:False,
                                       backup_dir=root/'backups')
                self.assertEqual(changes,[])
                self.assertEqual(file.read_bytes(),updated)
                self.assertEqual(len(list((root/'backups').iterdir())),1)

if __name__ == '__main__':
    unittest.main()
