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
from . import health

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

    def checklist(self, selected):
        if shutil.which('whiptail') and sys.stdin.isatty():
            args = ['whiptail', '--title', 'Debian 13 LLM Server Setup',
                    '--checklist', 'Choose modules (SPACE toggles)', '23', '100', '13']
            for component in ALL:
                args += [component, DESCRIPTIONS[component], 'ON' if component in selected else 'OFF']
            p = subprocess.run(args, stderr=subprocess.PIPE, text=True)
            if p.returncode:
                return None
            names = shlex.split(p.stderr)
            return [x for x in ALL if x in names]
        print('\n=== Debian 13 LLM post-install setup (terminal menu) ===')
        for i, name in enumerate(ALL, 1):
            print(f' [{"x" if name in selected else " "}] {i:2d}. {name:12} {DESCRIPTIONS[name]}')
        print('Enter module numbers to toggle, separated by commas; ENTER keeps selection; q cancels')
        value = input('Selection: ').strip()
        if value.lower() == 'q': return None
        if value:
            for item in value.split(','):
                if not item.strip().isdigit() or int(item.strip()) not in range(1, len(ALL)+1):
                    raise SetupError('Invalid module number: ' + item)
                name = ALL[int(item.strip())-1]
                selected = [x for x in selected if x != name] if name in selected else selected + [name]
        return [x for x in ALL if x in selected]


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


def plan(cfg, chosen):
    print('=== LLM SERVER POST-INSTALL: CHANGE PLAN ===')
    print('Target: Debian 13 x86_64 bare metal. Python standard library; no Docker.')
    print('Requested component order:')
    for idx, name in enumerate(chosen, 1):
        print(f' {idx:2d}. {name:12} {DESCRIPTIONS[name]}')
    print('Safety: NO repartition, format, mkfs or destructive mount operations.')
    print('Existing data disk mount is skipped unless partition UUID is typed exactly.')
    print('Web UI, API, code-server, file manager and Cockpit bind to 127.0.0.1 only.')
    print('Use SSH port forwards over LAN or Tailscale; do not expose unauthenticated Ollama API.')
    print('Ollama may require >1 GB release download; WebUI has large dependencies.')
    print('Qwen model download requires separate confirmation.')
    print('Run with --health after setup. A llama-server service requires a local GGUF file.')
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
              'results': {}, 'components': chosen}
    failures = 0
    for name in chosen:
        print('\n' + '='*64 + f'\n[MODULE] {name}: {DESCRIPTIONS[name]}')
        runner.logger.info('START COMPONENT %s', name)
        try:
            INSTALLERS[name](runner, cfg, ui)
            status['results'][name] = 'OK'
            runner.logger.info('PASS COMPONENT %s', name)
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
    p.add_argument('--component', action='append', choices=ALL, help='Only selected module(s), repeatable')
    p.add_argument('--yes', action='store_true', help='Accept ordinary prompts; never bypass typed storage UUID')
    p.add_argument('--gguf', metavar='PATH', help='Use local GGUF inside selected model root and enable llama-server')
    args = p.parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.gguf:
            cfg['llama_model_path'] = args.gguf
        chosen = [x for x in ALL if x in (args.component or cfg['components'])]
        if args.plan:
            plan(cfg, chosen)
            problems = detect_target()
            if problems: print('Preflight notes: ' + '; '.join(problems))
            return 0
        if args.health:
            return health.render(chosen)
        ui = UI(args.yes)
        if not args.apply:
            selected = ui.checklist(chosen)
            if selected is None: return 0
            chosen = selected
        plan(cfg, chosen)
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
