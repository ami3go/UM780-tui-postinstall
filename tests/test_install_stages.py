"""Five-step installer workflow contract and selection regression tests."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest import mock

from llmsetup import cli
from llmsetup.components import ALL, DESCRIPTIONS, INSTALLERS
from llmsetup.install_stages import (
    STAGES, ORDER, STAGE_BY_COMPONENT, SETUP_NOTES, PREREQUISITES,
    get_stage, ordered_selection, selected_from_stages, manual_prerequisites,
)


class StageRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg=json.loads((Path(__file__).parents[1]/'config.json').read_text())

    def test_every_component_in_exactly_one_priority_stage(self):
        self.assertEqual(len(STAGES), 5)
        self.assertEqual([s.number for s in STAGES], [1, 2, 3, 4, 5])
        self.assertEqual(len(ORDER), len(set(ORDER)))
        self.assertEqual(len(ORDER), 39)
        self.assertEqual(list(ORDER), ALL)
        self.assertEqual(set(ORDER), set(DESCRIPTIONS))
        self.assertEqual(set(ORDER), set(INSTALLERS))
        self.assertEqual(set(ORDER), set(STAGE_BY_COMPONENT))

    def test_recommended_prerequisites_appear_before_dependent(self):
        for component, dependencies in PREREQUISITES.items():
            for predecessor in dependencies:
                self.assertIn(predecessor, ORDER)
                self.assertLess(ORDER.index(predecessor),ORDER.index(component),
                                f'{component} before {predecessor}')

    def test_critical_order_for_models_cockpit_and_bookmarks(self):
        for before,after in [('base','storage'),('storage','ollama'),
                             ('vulkan','llama'),('ollama','models'),
                             ('ollama','webui'),('cockpit','cockpit_bookmarks'),
                             ('cockpit','cockpit_ghsync'),
                             ('tailscale','secure_ingress'),
                             ('uptime_kuma','bookmark_sync'),
                             ('novnc','bookmark_sync')]:
            self.assertLess(ALL.index(before), ALL.index(after))

    def test_default_unmodified_and_optional_not_auto_installed(self):
        self.assertEqual(len(self.cfg['components']), 18)
        self.assertEqual(set(self.cfg['components']) & {'novnc','vnc','ttyd','preflight',
                         'config_snapshot','backup_restore','ups_wol','secure_ingress'}, set())
        selections=[]
        for stage in STAGES:
            selected=selected_from_stages([stage.number], self.cfg['components'])
            self.assertEqual(selected, [n for n in stage.components if n in self.cfg['components']])
            selections+=selected
        self.assertEqual(set(selections), set(self.cfg['components']))

    def test_stage_selection_preserves_priority_order_and_deduplicates(self):
        actual=selected_from_stages([5, 3, 1, 3], self.cfg['components'])
        selected=set(get_stage(1).components+get_stage(3).components+get_stage(5).components)
        self.assertEqual(actual,[n for n in ORDER if n in selected and n in self.cfg['components']])
        self.assertEqual(len(actual),len(set(actual)))
        self.assertNotIn('backup_restore',actual)

    def test_individual_modules_are_sorted_without_added_prerequisites(self):
        self.assertEqual(ordered_selection(['models','ollama','models']),['ollama','models'])
        self.assertEqual(ordered_selection(['cockpit_bookmarks']),['cockpit_bookmarks'])
        self.assertEqual(manual_prerequisites('models',['models']),('ollama',))
        self.assertEqual(manual_prerequisites('models',['ollama','models']),())

    def test_invalid_stage_refused(self):
        for value in (0, 6, '1', None, True):
            with self.assertRaises(ValueError):
                get_stage(value)

    def test_setup_notes_cover_critical_manual_actions(self):
        for component in ['storage','models','cockpit_ghsync','tailscale',
                          'novnc','backup_restore','ups_wol','uptime_kuma']:
            self.assertIn(component, SETUP_NOTES)


class StagedCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg=json.loads((Path(__file__).parents[1]/'config.json').read_text())

    def _main(self,args):
        stream=io.StringIO()
        with redirect_stdout(stream),mock.patch.object(cli,'detect_target',return_value=[]):
            rc=cli.main(args)
        return rc,stream.getvalue()

    def test_list_stages_read_only(self):
        rc,text=self._main(['--list-stages'])
        self.assertEqual(rc,0)
        self.assertIn('Step 1:',text)
        self.assertIn('Step 5:',text)
        self.assertIn('[optional]',text)
        self.assertIn('[default]',text)

    def test_plan_stage_does_not_install_other_modules(self):
        rc,output=self._main(['--plan','--stage','2'])
        self.assertEqual(rc,0)
        self.assertIn('STEP 2/5',output)
        self.assertIn('ollama',output)
        self.assertNotIn('STEP 1/5',output)
        self.assertNotIn('STEP 3/5',output)
        self.assertNotIn('llama_swap',output)

    def test_multi_stage_combines_in_canonical_order(self):
        rc,out=self._main(['--plan','--stage','3','--stage','1'])
        self.assertEqual(rc,0)
        self.assertLess(out.index('STEP 1/5'),out.index('STEP 3/5'))

    def test_stage_and_component_together_rejected(self):
        rc,out=self._main(['--plan','--stage','2','--component','models'])
        self.assertEqual(rc,1)

    def test_no_nondefault_install_on_stage_apply(self):
        chosen=selected_from_stages([4],self.cfg['components'])
        self.assertEqual(chosen,['tailscale'])


class StagedTUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg=json.loads((Path(__file__).parents[1]/'config.json').read_text())

    def test_plain_terminal_guides_through_all_five_categories(self):
        out=io.StringIO()
        with mock.patch.object(cli.shutil,'which',return_value=None), \\
             mock.patch('builtins.input',side_effect=['1','','','','']), \\
             redirect_stdout(out):
            selected=cli.UI().checklist(list(self.cfg['components']))
        self.assertIn('preflight',selected)
        self.assertEqual(len(selected),19)
        self.assertEqual(out.getvalue().count('=== STEP'),5)

    def test_cancel_aborts_selection_without_apply(self):
        with mock.patch.object(cli.shutil,'which',return_value=None), \\
             mock.patch('builtins.input',side_effect=['','q']):
            chosen=cli.UI().checklist(list(self.cfg['components']))
        self.assertIsNone(chosen)

    def test_invalid_stage_index_is_not_accepted(self):
        with mock.patch.object(cli.shutil,'which',return_value=None), \\
             mock.patch('builtins.input',return_value='99'):
            with self.assertRaisesRegex(Exception,'Invalid module number'):
                cli.UI().checklist(list(self.cfg['components']))


if __name__=='__main__':
    unittest.main()
