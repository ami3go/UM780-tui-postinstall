"""Contract tests: added host maintenance modules remain opt-in and safe."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from llmsetup.components import ALL, INSTALLERS, DESCRIPTIONS
from llmsetup import component_maintenance as m
from llmsetup.core import SetupError

class FakeR:
    def __init__(self):
        self.packages=[]; self.calls=[]; self.writes=[]
    def apt(self,*items): self.packages.extend(items)
    def run(self,argv,**kwargs):
        self.calls.append(argv)
        return mock.Mock(returncode=0,stdout='OK')
    def write(self,path,content,**kw):
        self.writes.append((str(path),content,kw))
        return True


class MaintenanceTests(unittest.TestCase):
    def test_registered_but_not_enabled_by_default(self):
        names={'hardware_health','backup_restore','cockpit_storage',
               'service_watchdog','developer_tools','llm_benchmark','zram'}
        config=json.loads((Path(__file__).parents[1]/'config.json').read_text())
        self.assertTrue(names.issubset(set(ALL)))
        self.assertTrue(names.isdisjoint(set(config['components'])))
        for name in names:
            self.assertIn(name, INSTALLERS)
            self.assertIn(name, DESCRIPTIONS)

    def test_hardware_reports_without_mutating_drive(self):
        r=FakeR()
        m.hardware_health(r,{},None)
        self.assertIn('nvme-cli',r.packages)
        self.assertEqual([cmd[0] for cmd in r.calls],['nvme','smartctl','sensors'])
        self.assertNotIn('format',' '.join(map(str,r.calls)))
        self.assertEqual(r.writes[0][2]['mode'],0o600)

    def test_no_backup_target_means_cli_only(self):
        r=FakeR()
        m.backup_restore(r,{},None)
        self.assertEqual(r.packages,['restic'])
        self.assertEqual(r.writes,[])
        self.assertEqual(r.calls,[])

    def test_backup_rejects_nonexternal_and_nonexistent_paths(self):
        for path in ('', 'relative', '/etc', '/tmp/test', '/var/lib/llm-stack/models',
                     '/srv/llm-data/models'):
            with self.assertRaises(SetupError):
                m.validate_backup_repo(path)

    def test_developer_tools_does_not_edit_shell(self):
        r=FakeR()
        m.developer_tools(r,{},None)
        self.assertTrue({'ripgrep','fd-find','fzf','lazygit','zoxide'}.issubset(r.packages))
        self.assertFalse(r.writes)

    def test_watchdog_is_observation_only(self):
        r=FakeR()
        m.service_watchdog(r,{},None)
        self.assertIn('llm-service-watchdog.timer',' '.join(str(c) for c in r.calls))
        self.assertNotIn("['systemctl', 'restart'", m.WATCHDOG_CODE)
        self.assertNotIn('enable --now llm-ollama',' '.join(map(str,r.calls)))
        self.assertEqual(len(r.writes),3)

    def test_cockpit_storage_requires_existing_private_cockpit(self):
        r=FakeR()
        with mock.patch('llmsetup.component_maintenance.Path.is_file',return_value=False):
            with self.assertRaises(SetupError):
                m.cockpit_storage(r,{},None)
        self.assertEqual(r.packages,[])

    def test_llm_bench_refuses_missing_binary(self):
        with mock.patch('llmsetup.component_maintenance.Path.is_file',return_value=False):
            with self.assertRaises(SetupError):
                m.llm_benchmark(FakeR(),{},None)

if __name__ == '__main__':
    unittest.main()
