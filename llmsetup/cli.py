"""Interactive terminal checklist, dry-run plan, per-component execution and reports."""
from __future__ import annotations
import argparse
import datetime
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import traceback
from .core import CONF_DIR, STATE_DIR, Runner, SetupError, detect_target, is_root
from .components import ALL, DESCRIPTIONS, INSTALLERS
from .install_stages import STAGES, SETUP_NOTES, ordered_selection, selected_from_stages, manual_prerequisites
from .component_safety import restore_config_snapshot
from . import health, inventory
from .component_bookmarks_auto import auto_sync_bookmarks

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT = PROJECT_DIR / 'config.json'


class UI:
    def __init__(self, accept=False):
        self.accept = accept

    def confirm(self, message):
        if self.accept:
            # Model pulls always require opt-in; storage UUID still requires typed approval.
            return True
        if shutil.which('whiptail') and sys.stdin.isatty():
            p = subprocess.run(['whiptail', '--title', 'LLM Server Setup', '--yesno', message,
                                '11', '76'], check=False)
            return p.returncode == 0
        return input(f'{message} [y/N]: ').strip().lower() in ('yes', 'y')

    def ask(self, message):
        if shutil.which('whiptail') and sys.stdin.isatty():
            p = subprocess.run(['whiptail', '--inputbox', message, '11', '80'],
                                stderr=subprocess.PIPE, text=True, check=False)
            return p.stderr.strip() if p.returncode == 0 else ''
        return input(message)

    def checklist(self, selected, states=None):
        """Five sequential category screens; Cancel aborts the entire wizard.

        Unchecked entries stay unchecked; categorization never auto-selects.
        """
        selected = set(selected)
        states = states or {}
        interactive = bool(shutil.which('whiptail') and sys.stdin.isatty())
        for stage in STAGES:
            print(f'\n=== STEP {stage.number}/{len(STAGES)}: {stage.name} ===')
            print(stage.objective)
            if interactive:
                args = [
                    'whiptail', '--title',
                    f'Debian 13 Setup | Step {stage.number}/{len(STAGES)}',
                    '--checklist', stage.name + ': SPACE toggles; ENTER continues',
                    '23', '105', str(min(13, len(stage.components)))
                ]
                for name in stage.components:
                    code = states[name].short if name in states else 'UNKNOWN'
                    label = f'[{code}] {DESCRIPTIONS[name]}'
                    args += [name, label[:88],
                             'ON' if name in selected else 'OFF']
                p = subprocess.run(args, stderr=subprocess.PIPE, text=True, check=False)
                if p.returncode:
                    return None
                try:
                    chosen = set(shlex.split(p.stderr))
                except ValueError as exc:
                    raise SetupError('Invalid checklist response') from exc
                if not chosen.issubset(stage.components):
                    raise SetupError('Unexpected checklist component selection')
                selected.difference_update(stage.components)
                selected.update(chosen)
            else:
                for idx, name in enumerate(stage.components, 1):
                    mark = 'x' if name in selected else ' '
                    code = states[name].short if name in states else 'UNKNOWN'
                    print(f' [{mark}] {idx:2d}. {name:20} [{code:11}] {DESCRIPTIONS[name]}')
                print('Toggle by numbers separated by commas; ENTER keeps, q cancels.')
                value = input(f'Step {stage.number} selection: ').strip()
                if value.lower() == 'q':
                    return None
                if value:
                    for item in value.split(','):
                        item = item.strip()
                        if not item.isdigit() or not 1 <= int(item) <= len(stage.components):
                            raise SetupError('Invalid module number for this step: ' + item)
                        name = stage.components[int(item) - 1]
                        if name in selected:
                            selected.remove(name)
                        else:
                            selected.add(name)
        return ordered_selection(selected)


def load_config(path):
    data = json.loads(Path(path).read_text())
    if data.get('target_os') != 'debian-13' or data.get('host') != 'bare-metal':
        raise SetupError('Configuration must specify Debian 13 bare-metal')
    invalid = set(data.get('components', [])) - set(ALL)
    if invalid:
        raise SetupError('Unknown component(s): ' + ','.join(sorted(invalid)))
    if not isinstance(data.get('components'), list):
        raise SetupError('components must be an array')
    # Preserve the authorized storage decision across single-module reruns.
    persisted = CONF_DIR / 'storage.json'
    if persisted.is_file() and not persisted.is_symlink():
        saved_root = json.loads(persisted.read_text()).get('model_storage')
        if saved_root in ('/srv/llm-data/models', '/var/lib/llm-stack/models'):
            data['model_storage'] = saved_root
        else:
            raise SetupError('Persisted storage location is not one of the installer-managed model roots')
    return data


def show_stages(cfg):
    """Read-only catalog with effective default selection flags."""
    selected = set(cfg['components'])
    print('=== UM780 INSTALLATION STAGES (1 = essential, 5 = advanced) ===')
    for stage in STAGES:
        print(f'\nStep {stage.number}: {stage.name}')
        print('  ' + stage.objective)
        for name in stage.components:
            flag = 'default' if name in selected else 'optional'
            print(f'    {name:22} [{flag}] {DESCRIPTIONS[name]}')
    print('\nUse --plan --stage N or --apply --stage N for defaults of one stage.')
    print('Use --component NAME or the guided TUI to explicitly select optional tools.')


def plan(cfg, chosen, states=None):
    states = states or {}
    print('=== UM780 DEBIAN 13 STAGED CHANGE PLAN ===')
    print('Target: Debian 13 x86_64 bare metal. Native systemd; no Docker.')
    print('Execution follows stage priority and defined within-stage order.')
    counter = 0
    for stage in STAGES:
        names = [name for name in stage.components if name in chosen]
        if not names:
            continue
        print(f'\nSTEP {stage.number}/{len(STAGES)} — {stage.name}')
        print('  ' + stage.objective)
        for name in names:
            counter += 1
            print(f'  {counter:2d}. {name:20} {DESCRIPTIONS[name]}')
            if name in states:
                state = states[name]
                run = 'running' if state.running else ('stopped' if state.running is False else 'n/a')
                print(f'      Current: {state.status}; runtime: {run}')
            missing = manual_prerequisites(name, chosen)
            if missing:
                print('      Verify previously installed prerequisites: ' + ', '.join(missing))
            if name in SETUP_NOTES:
                print('      Setup: ' + SETUP_NOTES[name])
    print(f'\nSelected modules: {counter} of {len(ALL)}.')
    print('Safety: NO repartition, format, mkfs or implicit disk formatting.')
    print('Existing SSD mount may require exact typed UUID; preserve backups.')
    print('Prerequisites are advisory; they are NOT auto-installed or verified.')
    print('Inventory reads local evidence only; it does not validate logins, version drift or disk safety.')
    print('Browser links to localhost require forwarding; no public ports added.')
    print('First-login and security activation steps remain separate from installation.')
    print('Run --health after setup; physical GPU/login/restore acceptance remains required.')
    print()


def save_status(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    path.write_text(json.dumps(data, indent=2) + '\n')
    os.chmod(path, 0o600)


def execute(cfg, chosen, ui):
    if not is_root():
        raise SetupError('Apply requires root. Re-run with: sudo python3 install.py')
    problems = detect_target()
    if problems:
        raise SetupError('Preflight failed: ' + '; '.join(problems))
    runner = Runner()
    print('Installation log:', runner.log_path)
    status_path = STATE_DIR / 'last-run.json'
    status = {'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'results': {}, 'components': chosen, 'verification': {}}
    failures = 0
    previous_stage = None
    for name in chosen:
        current_stage = next(stage for stage in STAGES if name in stage.components)
        if previous_stage != current_stage.number:
            print(f'\n' + '='*64)
            print(f'STEP {current_stage.number}/{len(STAGES)}: {current_stage.name}')
            print(current_stage.objective)
            runner.logger.info('BEGIN STAGE %s: %s', current_stage.number, current_stage.name)
            previous_stage = current_stage.number
        print('\n' + '='*64 + f'\n[MODULE] {name}: {DESCRIPTIONS[name]}')
        runner.logger.info('START COMPONENT %s', name)
        try:
            INSTALLERS[name](runner, cfg, ui)
            status['results'][name] = 'OK'
            observed = inventory.inspect(name, cfg)
            status['verification'][name] = observed.as_dict()
            print('POST-INSTALL VERIFICATION:', observed.status,
                  '| active=' + str(observed.running))
            runner.logger.info('PASS COMPONENT %s; inventory=%s', name, observed.status)
        except Exception as exc:
            status['results'][name] = 'FAILED: ' + str(exc)
            failures += 1
            runner.logger.exception('FAILED COMPONENT %s', name)
            print(f'ERROR: {exc}\nReview log: {runner.log_path}')
            # avoid cascading later operations (e.g. model download without running service).
            if ui.accept or not ui.confirm(f'{name} failed. Continue with remaining independent modules?'):
                save_status(status_path, status)
                return 1
        save_status(status_path, status)
    if cfg.get('auto_bookmarks', True) and 'bookmark_sync' not in chosen:
        # Non-fatal: an invalid/custom Cockpit Bookmarks JSON must never block
        # successful installation of unrelated host components.
        try:
            auto_sync_bookmarks(runner, cfg, chosen)
            status['results']['_bookmarks_autosync'] = 'OK or plugin not installed'
        except Exception as exc:
            runner.logger.exception('Automatic Cockpit Bookmarks merge failed')
            status['results']['_bookmarks_autosync'] = 'WARNING: ' + str(exc)
            print('WARNING: Bookmarks automatic update skipped: ' + str(exc))
        save_status(status_path, status)
    print('\nModule results:', json.dumps(status['results'], indent=2))
    print('\nHealth check:')
    health.render(chosen)
    return 1 if failures else 0


def main(argv=None):
    p = argparse.ArgumentParser(description='Modular Debian 13 headless LLM post-install TUI')
    p.add_argument('--config', default=str(DEFAULT), help='JSON configuration')
    p.add_argument('--plan', action='store_true', help='Read-only change plan')
    p.add_argument('--health', action='store_true', help='Read-only local health checks')
    p.add_argument('--apply', action='store_true', help='Execute selected modules')
    p.add_argument('--component', action='append', choices=ALL, help='Explicit module selection; repeatable')
    p.add_argument('--stage', action='append', type=int, choices=[s.number for s in STAGES], help='Install default-selected modules in priority stage N (1..5); repeatable')
    p.add_argument('--list-stages', action='store_true', help='Read-only catalog of priorities, setup and optional modules')
    p.add_argument('--inventory', action='store_true', help='Read-only scan: installed/configured/running for all modules (or --stage/--component)')
    p.add_argument('--json', action='store_true', help='JSON inventory output; only with --inventory')
    p.add_argument('--yes', action='store_true', help='Accept ordinary prompts; never bypass typed storage UUID')
    p.add_argument('--restore-config', metavar='SNAPSHOT', help='Explicit config-only restore (requires typed RESTORE)')
    p.add_argument('--gguf', metavar='PATH', help='Use local GGUF inside selected model root and enable llama-server')
    args = p.parse_args(argv)
    try:
        if args.restore_config:
            if not is_root():
                raise SetupError('Configuration restore requires root')
            if not sys.stdin.isatty():
                raise SetupError('Configuration restore requires an interactive terminal')
            print('WARNING: config-only restore may overwrite live configuration; packages/disks are NOT rolled back.')
            confirmation = input('Type RESTORE to continue: ').strip()
            count = restore_config_snapshot(args.restore_config, confirmation)
            print(f'Restored {count} configuration files. Review and restart affected services manually.')
            return 0
        cfg = load_config(args.config)
        if args.gguf:
            cfg['llama_model_path'] = args.gguf
        if args.stage and args.component:
            raise SetupError('--stage and --component cannot be combined; use the TUI for custom selections')
        if args.json and not args.inventory:
            raise SetupError('--json is only supported with --inventory')
        if args.list_stages:
            show_stages(cfg)
            return 0
        if args.inventory:
            if args.stage:
                chosen = ordered_selection(n for stage in STAGES if stage.number in args.stage
                                           for n in stage.components)
            else:
                chosen = ordered_selection(args.component or ALL)
            inventory.render(inventory.scan(chosen, cfg), selected=cfg['components'],
                             json_mode=args.json)
            return 0
        if args.stage:
            chosen = selected_from_stages(args.stage, cfg['components'])
        else:
            chosen = ordered_selection(args.component or cfg['components'])
        if args.plan:
            plan(cfg, chosen, inventory.scan(chosen, cfg))
            problems = detect_target()
            if problems: print('Preflight notes: ' + '; '.join(problems))
            return 0
        if args.health:
            return health.render(chosen)
        ui = UI(args.yes)
        states = inventory.scan(ALL if not args.apply else chosen, cfg)
        if not args.apply:
            selected = ui.checklist(chosen, states=states)
            if selected is None: return 0
            chosen = selected
        plan(cfg, chosen, states)
        if not chosen:
            print('No components selected.'); return 0
        if not args.yes and not ui.confirm('Apply the selected installation modules now?'):
            print('Cancelled: no installation changes made.')
            return 0
        return execute(cfg, chosen, ui)
    except (SetupError, OSError, ValueError, KeyboardInterrupt) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
