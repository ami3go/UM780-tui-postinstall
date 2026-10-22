#!/usr/bin/env python3
"""Manage the Open WebUI account used for no-login (WEBUI_AUTH=False) mode.

Open WebUI only allows WEBUI_AUTH=False on an installation with existing
users if an `admin@localhost` account with password `admin` exists; every
visitor is then signed in as that account. Called by lan-access.sh:

    sudo python3 webui-lan-user.py ensure   # create/reset admin@localhost / admin (role admin)
    sudo python3 webui-lan-user.py lock     # give it a random password once login is back on

`lock` matters: with login enabled again, a known `admin` password would let
anyone on the LAN sign in as an administrator. Signs in with the installer's
bootstrap admin (admin@llm.local, password in
/etc/llm-postinstall/webui-admin-password); Open WebUI must be running with
authentication on.
"""
from __future__ import annotations

import json
import secrets
import sys
import time
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:3000'
ADMIN_EMAIL = 'admin@llm.local'
ADMIN_PASSWORD_FILE = '/etc/llm-postinstall/webui-admin-password'
NOLOGIN_EMAIL = 'admin@localhost'
NOLOGIN_PASSWORD = 'admin'  # fixed by Open WebUI for WEBUI_AUTH=False


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json',
                                          **({'Authorization': 'Bearer ' + token} if token else {})})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read() or b'null')


def wait_until_up(seconds=180):
    end = time.time() + seconds
    while time.time() < end:
        try:
            call('GET', '/health')
            return
        except (OSError, urllib.error.URLError):
            time.sleep(3)
    sys.exit('Open WebUI did not come up on 127.0.0.1:3000')


def admin_token():
    try:
        password = open(ADMIN_PASSWORD_FILE, encoding='utf-8').read().strip()
        return call('POST', '/api/v1/auths/signin',
                    {'email': ADMIN_EMAIL, 'password': password})['token']
    except urllib.error.HTTPError as exc:
        sys.exit(f'Cannot sign in as {ADMIN_EMAIL} (HTTP {exc.code}). If you changed its '
                 f'password, put the current one in {ADMIN_PASSWORD_FILE} and retry.')


def find_user(token, email):
    users = call('GET', '/api/v1/users/all', token=token)['users']
    return next((u for u in users if u['email'].lower() == email), None)


def main(mode):
    wait_until_up()
    token = admin_token()
    user = find_user(token, NOLOGIN_EMAIL)
    if mode == 'ensure':
        if user is None:
            call('POST', '/api/v1/auths/add', {'name': 'LAN', 'email': NOLOGIN_EMAIL,
                                              'password': NOLOGIN_PASSWORD, 'role': 'admin'}, token)
            print(f'Created Open WebUI account {NOLOGIN_EMAIL} for no-login mode.')
        else:
            call('POST', f"/api/v1/users/{user['id']}/update",
                 {'role': 'admin', 'name': user['name'], 'email': NOLOGIN_EMAIL,
                  'password': NOLOGIN_PASSWORD}, token)
            print(f'Reset Open WebUI account {NOLOGIN_EMAIL} for no-login mode.')
    elif user is not None:
        call('POST', f"/api/v1/users/{user['id']}/update",
             {'role': user['role'], 'name': user['name'], 'email': NOLOGIN_EMAIL,
              'password': secrets.token_urlsafe(24)}, token)
        print(f'Locked Open WebUI account {NOLOGIN_EMAIL} with a random password.')


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('ensure', 'lock'):
        sys.exit('usage: webui-lan-user.py ensure|lock')
    main(sys.argv[1])
