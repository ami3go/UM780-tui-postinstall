#!/usr/bin/env python3
"""Point UM780 Cockpit Bookmarks cards at the LAN instead of 127.0.0.1.

Companion to scripts/lan-access.sh. Rewrites installer-managed cards to use
the Bookmarks {host} placeholder (the address the browser used to reach
Cockpit), drops their SSH-tunnel notes, and adds Cockpit and Ollama API
cards. The installer's bookmark auto-sync never edits existing cards, so the
result survives installer reruns.

    python3 scripts/cockpit-bookmarks-lan.py                 # preview only
    sudo python3 scripts/cockpit-bookmarks-lan.py --apply    # write (with backup)
    sudo python3 scripts/cockpit-bookmarks-lan.py --apply --remove-samples
    sudo python3 scripts/cockpit-bookmarks-lan.py --apply --host 192.168.31.55

--host writes a fixed address instead of {host}; re-running with a different
--host (or none) rewrites the installer-managed cards again.

--remove-samples also drops the plugin's sample cards (Grafana, Example
Service, Discovered Example); the sample "Grafana" points at :3000, which is
Open WebUI on this server.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

CONFIG = Path('/etc/cockpit/cockpit-bookmarks.json')
GROUP = 'UM780 Web Apps'
MANAGED_BY = 'um780-postinstall'
SAMPLES = ('Grafana', 'Example Service', 'Discovered Example')

DESCRIPTIONS = {
    'um780-filebrowser': 'Server file manager for LLM model storage',
    'um780-webui': 'Ollama chat interface',
    'um780-codeserver': 'Browser-based IDE',
    'um780-novnc': 'Virtual XFCE desktop; VNC password: '
                   'sudo cat /etc/llm-postinstall/novnc-vnc-password',
}

EXTRA_CARDS = [
    {'id': 'um780-cockpit', 'name': 'Cockpit',
     'description': 'Server administration: services, logs, storage, updates, terminal',
     'url': 'https://{host}:9090/', 'icon': '\U0001F6E0️'},
    {'id': 'um780-ollama', 'name': 'Ollama API',
     'description': 'Local LLM API (no login); lists installed models',
     'url': 'http://{host}:11434/api/tags', 'icon': '\U0001F999'},
]


HOST_RE = re.compile(r'^(https?://)[^/:]+(:\d+)')
HOST_OK = re.compile(r'^(\{host\}|[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])$')


def transform(config, remove_samples=False, host='{host}'):
    services = []
    for card in config.get('services', []):
        if (remove_samples and card.get('name') in SAMPLES
                and 'um780ManagedBy' not in card):
            continue
        url = str(card.get('url', ''))
        if card.get('um780ManagedBy') == MANAGED_BY and HOST_RE.match(url):
            tags = [t for t in card.get('tags', []) if t != 'ssh-tunnel']
            card = dict(card, url=HOST_RE.sub(lambda m: m.group(1) + host + m.group(2), url, count=1),
                        tags=tags if 'lan' in tags else tags + ['lan'])
            if card.get('id') in DESCRIPTIONS:
                card['description'] = DESCRIPTIONS[card['id']]
        services.append(card)
    ids = {c.get('id') for c in services}
    for extra in EXTRA_CARDS:
        if extra['id'] not in ids:
            services.append({**extra, 'url': extra['url'].replace('{host}', host),
                             'um780ManagedBy': MANAGED_BY, 'group': GROUP,
                             'tags': ['um780', 'lan'], 'statusCheck': False})
    groups = [g for g in config.get('groupOrder', []) if g != GROUP]
    if remove_samples:
        used = {c.get('group') for c in services}
        groups = [g for g in groups if g in used]
    return {**config, 'services': services, 'groupOrder': [GROUP] + groups}


def save(path, config):
    backup = path.with_name(path.name + '.' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S') + '.bak')
    shutil.copy2(path, backup)
    info = path.stat()
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(json.dumps(config, indent=2, ensure_ascii=False) + '\n')
        os.chmod(temp, info.st_mode & 0o777)
        os.chown(temp, info.st_uid, info.st_gid)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--apply', action='store_true', help='write changes (default: preview)')
    parser.add_argument('--remove-samples', action='store_true', help="drop the plugin's sample cards")
    parser.add_argument('--host', default='{host}',
                        help='address for card links (default: {host}, the address used to open Cockpit)')
    args = parser.parse_args(argv)
    if not HOST_OK.match(args.host):
        sys.exit('Invalid --host: use a hostname, IPv4 address, [IPv6] address or {host}')

    config = json.loads(args.config.read_text(encoding='utf-8'))
    if not isinstance(config.get('services'), list):
        sys.exit('Unexpected Cockpit Bookmarks format; nothing changed')
    result = transform(config, args.remove_samples, args.host)
    for card in result['services']:
        print(f"{card.get('name', '?'):22} {card.get('url', '')}")
    if result == config:
        print('Already up to date; nothing to change.')
    elif args.apply:
        print('Saved; backup at', save(args.config, result))
    else:
        print('Preview only; rerun with sudo and --apply to write.')


if __name__ == '__main__':
    main()
