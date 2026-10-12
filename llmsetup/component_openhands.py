"""Opt-in OpenHands local GUI; Docker is an explicit security exception.

No cloud credentials are collected, saved, echoed or placed in service arguments.
The optional Ollama relay listens ONLY on Docker's default bridge gateway.
"""
from __future__ import annotations

import ipaddress
import re
import shutil
import socket
from pathlib import Path

from .core import SetupError, ensure_dir
from .component_base import unit

# Pair published in upstream OpenHands Local GUI documentation (V1).
OPENHANDS_IMAGE = 'docker.openhands.dev/openhands/openhands:1.8'
AGENT_REPOSITORY = 'ghcr.io/openhands/agent-server'
AGENT_TAG = '1.26.0-python'
UNIT = 'llm-openhands.service'
BRIDGE_UNIT = 'llm-openhands-ollama-bridge.service'
RESERVED_PORTS = frozenset((3000, 3001, 8081, 8082, 8443, 8888, 9090, 11434, 11435))


def options(cfg):
    raw = cfg.get('openhands', {})
    if not isinstance(raw, dict):
        raise SetupError('openhands configuration must be an object')
    port = raw.get('port', 3002)
    if type(port) is not int or not 1024 <= port <= 65535 or port in RESERVED_PORTS:
        raise SetupError('openhands.port must be a free, non-reserved TCP port from 1024 to 65535')
    relay = raw.get('ollama_bridge', True)
    if type(relay) is not bool:
        raise SetupError('openhands.ollama_bridge must be true or false')
    model = raw.get('local_model', cfg.get('model', 'qwen2.5-coder:7b'))
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}', model):
        raise SetupError('openhands.local_model must be a valid Ollama model ID')
    return port, relay, model


def docker_gateway(raw):
    value = raw.strip()
    try:
        gateway = ipaddress.ip_address(value)
    except ValueError as exc:
        raise SetupError('Could not determine Docker default bridge gateway') from exc
    if not isinstance(gateway, ipaddress.IPv4Address) or not gateway.is_private or gateway.is_loopback or gateway.is_unspecified or gateway.is_link_local or gateway.is_multicast or gateway.is_reserved:
        raise SetupError('Docker bridge gateway must be a private non-loopback IPv4 address')
    return str(gateway)


def installed_port():
    """Read the installed managed systemd mapping for diagnostics/bookmarks."""
    path = Path('/etc/systemd/system') / UNIT
    try:
        if path.is_symlink() or not path.is_file():
            return 3002
        raw = path.read_text(encoding='utf-8')
        if not raw.startswith('# Managed by debian-llm-postinstall'):
            return 3002
        matches = re.findall(r' -p 127\.0\.0\.1:(\d{4,5}):3000(?: |$)', raw)
        if len(matches) == 1:
            port = int(matches[0])
            if 1024 <= port <= 65535:
                return port
    except (OSError, UnicodeError, ValueError):
        pass
    return 3002


def _already_owned_unit():
    path = Path('/etc/systemd/system') / UNIT
    if path.is_symlink():
        raise SetupError('Refusing symlinked OpenHands service unit')
    if not path.exists():
        return False
    return path.is_file() and path.read_text().startswith('# Managed by debian-llm-postinstall')


def _ensure_docker(r, ui):
    # The repo otherwise intentionally installs native apps only.
    if not ui.confirm('OpenHands requires Docker socket access (effectively host-root privileges). Install/enable Docker and run this SINGLE-USER service?'):
        raise SetupError('Docker/OpenHands consent declined; no changes made')
    if not shutil.which('docker'):
        if not ui.confirm('Docker is absent. Install Debian docker.io (new daemon and bridge networking)?'):
            raise SetupError('Docker installation declined')
        r.apt('docker.io')
    r.run(['systemctl', 'enable', '--now', 'docker.service'], timeout=60)
    r.run(['docker', 'info', '--format', '{{.ServerVersion}}'], capture=True, timeout=20)
    if not Path('/var/run/docker.sock').exists():
        raise SetupError('Docker socket missing; refusing to install OpenHands')


def _check_port(port):
    if _already_owned_unit():
        return
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        if sock.connect_ex(('127.0.0.1', port)) == 0:
            raise SetupError('OpenHands port already in use by an unmanaged service: ' + str(port))


def _bridge(r):
    ollama_unit = Path('/etc/systemd/system/llm-ollama.service')
    if not ollama_unit.is_file() or ollama_unit.is_symlink():
        raise SetupError('Install the native ollama component before enabling OpenHands Ollama bridge')
    r.apt('socat')
    out = r.run(['docker', 'network', 'inspect', 'bridge',
                 '--format', '{{(index .IPAM.Config 0).Gateway}}'],
                capture=True, timeout=20)
    gateway = docker_gateway(out.stdout)
    unit(r, BRIDGE_UNIT, f"""[Unit]
Description=OpenHands Ollama proxy on Docker bridge ONLY (unauthenticated)
Requires=docker.service
After=docker.service llm-ollama.service
Wants=llm-ollama.service
[Service]
Type=simple
ExecStart=/usr/bin/socat TCP-LISTEN:11435,bind={gateway},reuseaddr,fork TCP:127.0.0.1:11434
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectHome=yes
ProtectSystem=strict
PrivateTmp=yes
[Install]
WantedBy=multi-user.target""")
    return gateway


def _stop_managed_bridge_if_disabled(r):
    path = Path('/etc/systemd/system') / BRIDGE_UNIT
    if path.is_symlink():
        raise SetupError('Refusing symlinked Ollama bridge unit')
    if path.is_file():
        if not path.read_text().startswith('# Managed by debian-llm-postinstall'):
            raise SetupError('Existing Ollama bridge unit is unmanaged')
        r.service(BRIDGE_UNIT, enable=False)


def openhands(r, cfg, ui):
    """Install OpenHands with explicit Docker consent and localhost-only UI.

    Provider credentials and the active model are configured separately in the
    OpenHands UI. This installer does NOT enable automatic multi-model routing.
    """
    port, relay, model = options(cfg)
    _check_port(port)
    if relay:
        ollama_unit = Path('/etc/systemd/system/llm-ollama.service')
        if not ollama_unit.is_file() or ollama_unit.is_symlink():
            raise SetupError('OpenHands Ollama bridge needs the native ollama component first')
    _ensure_docker(r, ui)
    # Versioned images avoid surprise drift on repeat installation.
    r.run(['docker', 'pull', OPENHANDS_IMAGE], timeout=1800)
    r.run(['docker', 'pull', AGENT_REPOSITORY + ':' + AGENT_TAG], timeout=1800)
    ensure_dir('/var/lib/llm-openhands', mode=0o700)
    if relay:
        _bridge(r)
    else:
        _stop_managed_bridge_if_disabled(r)

    unit(r, UNIT, f"""[Unit]
Description=OpenHands local coding agent (Docker, single user)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=/usr/bin/docker run --rm --name llm-openhands --pull=never -p 127.0.0.1:{port}:3000 --add-host host.docker.internal:host-gateway -e AGENT_SERVER_IMAGE_REPOSITORY={AGENT_REPOSITORY} -e AGENT_SERVER_IMAGE_TAG={AGENT_TAG} -e LOG_ALL_EVENTS=false -v /var/run/docker.sock:/var/run/docker.sock -v /var/lib/llm-openhands:/.openhands {OPENHANDS_IMAGE}
ExecStop=/usr/bin/docker stop -t 20 llm-openhands
Restart=on-failure
RestartSec=8
TimeoutStartSec=180
TimeoutStopSec=45
[Install]
WantedBy=multi-user.target""")
    print(f'OpenHands: http://127.0.0.1:{port}/ (forward with ssh -L {port}:127.0.0.1:{port})')
    print('LLM settings in OpenHands: GPT => OpenAI and your API key; Claude => Anthropic and your API key.')
    if relay:
        print(f'Local LLM: Advanced model=openai/{model}; base=http://host.docker.internal:11435/v1; API key=local-key')
        print('WARNING: Ollama relay is unauthenticated and reachable by containers on Docker default bridge, not LAN.')
        print('For reliable tool use configure Ollama context >= 22000; test your model capabilities.')
    print('Credentials are NOT configured by this installer; configure/rotate them in OpenHands Settings.')
    print('This installs manual model choice only, NOT autonomous cross-model task delegation.')
