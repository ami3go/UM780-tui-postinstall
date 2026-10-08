"""Turnkey, localhost-only noVNC desktop on Debian 13.

Creates one dedicated unprivileged virtual XFCE desktop (:2) and an isolated
websockify/noVNC listener. VncAuth supports only eight significant password
characters; enforce SSH forwarding and never publish or embed credentials in
Cockpit Bookmarks or logs.
"""
from __future__ import annotations

import os
from pathlib import Path
import pwd
import re
import secrets
import socket
import stat
import subprocess
import tempfile

from .core import CONF_DIR, SetupError, ensure_dir
from .component_base import unit

VNC_USER = 'llmvnc'
VNC_HOME = Path('/var/lib/llmvnc')
VNC_PASS_FILE = VNC_HOME / '.config/tigervnc/passwd'
CLEAR_PASS_FILE = CONF_DIR / 'novnc-vnc-password'
VNC_SERVICE = 'llm-novnc-vnc.service'
WEB_SERVICE = 'llm-novnc.service'
VNC_PORT = 5902
WEB_PORT = 6080
PASS_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'


def generate_vnc_password():
    """Exactly eight random supported chars (VncAuth ignores later chars)."""
    return ''.join(secrets.choice(PASS_CHARS) for _ in range(8))


def _ensure_service_identity(r):
    r.account(VNC_USER)
    info = pwd.getpwnam(VNC_USER)
    if info.pw_uid == 0 or info.pw_dir != str(VNC_HOME) or info.pw_shell not in (
            '/usr/sbin/nologin', '/bin/false'):
        raise SetupError('Existing llmvnc user has unexpected home/shell/UID; refusing to run GUI')
    ensure_dir(VNC_HOME)
    if VNC_HOME.is_symlink():
        raise SetupError('VNC service home is a symlink')
    if VNC_HOME.stat().st_uid != info.pw_uid:
        raise SetupError('VNC service home is not owned by llmvnc')
    return info


def _private_file(path, uid, gid):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise SetupError('Missing, non-regular, or symlinked credential file: ' + str(path))
    info = path.stat()
    if (info.st_nlink != 1 or info.st_uid != uid or info.st_gid != gid
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise SetupError('Insecure owner, links or permissions for: ' + str(path))


def _secure_dir(path, uid, gid):
    path = Path(path)
    if path.is_symlink():
        raise SetupError('VNC credential directory may not be a symlink')
    if not path.exists():
        path.mkdir(parents=True, mode=0o700)
        os.chown(path, uid, gid)
        os.chmod(path, 0o700)
    info = path.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
            or info.st_gid != gid or stat.S_IMODE(info.st_mode) != 0o700):
        raise SetupError('VNC credential directory has unexpected ownership/permissions')


def _exclusive_binary(path, payload, uid, gid):
    """Create a credential securely and fail instead of replacing any existing file."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise SetupError('Credential already exists, refusing replacement: ' + str(path))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as out:
            fd = -1
            os.fchown(out.fileno(), uid, gid)
            os.fchmod(out.fileno(), 0o600)
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
    finally:
        if fd >= 0: os.close(fd)


def encode_vnc_password(password):
    """Never pass a secret in argv/env or log it. TigerVNC filter mode -> 8 bytes."""
    if not re.fullmatch(r'[A-Za-z0-9]{8}', password):
        raise SetupError('VNC password must be exactly eight safe alphanumeric characters')
    try:
        p = subprocess.run(['/usr/bin/tigervncpasswd', '-f'],
                           input=(password + '\n').encode('ascii'),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           check=False, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError('TigerVNC password encoder failed (details redacted)') from exc
    if p.returncode != 0 or len(p.stdout) != 8:
        raise SetupError('TigerVNC password encoder returned invalid data (details redacted)')
    return p.stdout


def provision_credentials(r):
    """First-run secret generation; never silently rotate or replace credentials."""
    service = _ensure_service_identity(r)
    _secure_dir(CONF_DIR, 0, 0)
    _secure_dir(VNC_HOME / '.config', service.pw_uid, service.pw_gid)
    _secure_dir(VNC_HOME / '.config/tigervnc', service.pw_uid, service.pw_gid)

    if CLEAR_PASS_FILE.exists() or CLEAR_PASS_FILE.is_symlink():
        _private_file(CLEAR_PASS_FILE, 0, 0)
        password = CLEAR_PASS_FILE.read_text(encoding='ascii').strip()
        if not re.fullmatch(r'[A-Za-z0-9]{8}', password):
            raise SetupError('Existing noVNC password is invalid; manual recovery needed')
    else:
        if VNC_PASS_FILE.exists() or VNC_PASS_FILE.is_symlink():
            raise SetupError('Found VNC password file but no recoverable root credential; refusing rotation')
        password = generate_vnc_password()
        _exclusive_binary(CLEAR_PASS_FILE, (password + '\n').encode('ascii'), 0, 0)

    encrypted = encode_vnc_password(password)
    if VNC_PASS_FILE.exists() or VNC_PASS_FILE.is_symlink():
        _private_file(VNC_PASS_FILE, service.pw_uid, service.pw_gid)
        if VNC_PASS_FILE.read_bytes() != encrypted:
            raise SetupError('VNC password differs from stored root credential; manual recovery required')
    else:
        _exclusive_binary(VNC_PASS_FILE, encrypted, service.pw_uid, service.pw_gid)
    return CLEAR_PASS_FILE


def _loopback_port_busy(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


def _preflight_ports(r):
    """Avoid routing noVNC to another user's VNC session."""
    for port, service in ((VNC_PORT, VNC_SERVICE), (WEB_PORT, WEB_SERVICE)):
        if _loopback_port_busy(port):
            active = r.run(['systemctl', 'is-active', '--quiet', service],
                           capture=True, check=False)
            if active.returncode != 0:
                raise SetupError(f'Port {port} is occupied by an unrelated service; refusing to proxy it')


def configure_novnc(r, cfg, ui):
    """Install, configure credentials, enable both backend and frontend."""
    r.apt('tigervnc-standalone-server', 'tigervnc-tools', 'xfce4', 'dbus-x11',
          'dbus-user-session', 'novnc', 'websockify')
    credentials = provision_credentials(r)
    if not Path('/usr/share/novnc/vnc.html').is_file():
        raise SetupError('Debian noVNC vnc.html missing; refusing to start empty proxy')
    _preflight_ports(r)

    # Deliberately separate :2 from the older optional user VNC template (:1).
    unit(r, VNC_SERVICE, f"""[Unit]
Description=Isolated UM780 XFCE virtual desktop for noVNC
After=network.target
[Service]
Type=simple
User={VNC_USER}
Group={VNC_USER}
WorkingDirectory={VNC_HOME}
Environment=HOME={VNC_HOME}
Environment=XDG_CONFIG_HOME={VNC_HOME}/.config
ExecStartPre=/usr/bin/test -s {VNC_PASS_FILE}
ExecStart=/usr/bin/tigervncserver -fg :2 -rfbport {VNC_PORT} -localhost yes -SecurityTypes VncAuth -rfbauth {VNC_PASS_FILE} -geometry 1600x900 -xstartup /usr/bin/startxfce4
ExecStop=/usr/bin/tigervncserver -kill :2
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths={VNC_HOME}
[Install]
WantedBy=multi-user.target
""")
    unit(r, WEB_SERVICE, f"""[Unit]
Description=Local-only noVNC browser proxy with VncAuth backend
Requires={VNC_SERVICE}
After={VNC_SERVICE}
[Service]
Type=simple
User=nobody
Group=nogroup
ExecStart=/usr/bin/websockify --web /usr/share/novnc 127.0.0.1:{WEB_PORT} 127.0.0.1:{VNC_PORT}
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
[Install]
WantedBy=multi-user.target
""")
    print('noVNC configured; virtual XFCE server and browser proxy enabled on localhost.')
    print('Desktop URL (through SSH forwarding): http://127.0.0.1:6080/vnc.html')
    print('VNC authentication is password-only; username is not required.')
    print('Root-only VNC credential file: ' + str(credentials))
    print('Read it locally with: sudo cat ' + str(credentials))
    print('Cockpit Bookmarks auto-sync will add the desktop card if enabled.')
