# Cockpit plugins — GitHub Sync and Bookmarks

The TUI includes two optional Cockpit plugins maintained under the same GitHub account as this installer:

| Module | Upstream | What gets installed |
| --- | --- | --- |
| `cockpit_ghsync` | [ami3go/ghsync](https://github.com/ami3go/ghsync) | CLI, maintenance helpers, system-wide Cockpit page |
| `cockpit_bookmarks` | [ami3go/bookmarks](https://github.com/ami3go/bookmarks) | Prebuilt Cockpit Bookmarks Debian package and default config if absent |

## Automatic bookmarks for installed apps

When Cockpit Bookmarks is installed, the UM780 post-install script can auto-add web app links and on-demand terminal application cards for installed tools, without touching custom entries. The auto-hook is enabled by `auto_bookmarks: true` in the installer configuration; you can explicitly run `sudo python3 install.py --apply --component bookmark_sync`. See [automatic app bookmarks](BOOKMARKS_AUTO.md) for detection criteria, per-client SSH forwarding, launcher security and backup/recovery behavior.

## Automatic noVNC desktop bookmark

When the `novnc` module is selected, the installer starts a dedicated localhost XFCE VNC desktop and proxy with **generated root-only VNC credentials**. After an apply run with `auto_bookmarks: true`, Cockpit Bookmarks adds the `noVNC Desktop` card with a password-retrieval hint, not the actual secret. Read [noVNC Desktop](NOVNC_DESKTOP.md) for startup, network forwarding and credentials.

## Safe install sequence

Start with the Debian 13 host and the base Cockpit module. The plugin modules **intentionally refuse** to install unless the Cockpit loopback socket override is already present at `/etc/systemd/system/cockpit.socket.d/llm-postinstall.conf`.

```sh
python3 install.py --plan --component cockpit --component cockpit_ghsync --component cockpit_bookmarks
sudo python3 install.py --apply --component cockpit
sudo python3 install.py --apply --component cockpit_ghsync
sudo python3 install.py --apply --component cockpit_bookmarks
sudo python3 install.py --health --component cockpit_ghsync --component cockpit_bookmarks
```

Both plugins are in the default checklist but can be toggled off independently with SPACE in `whiptail` or by selecting only desired modules with `--component`.

### GitHub Sync behavior

The installer:
1. Installs `git`, `gh`, `cron`, and `bash` from Debian repositories.
2. Clones `https://github.com/ami3go/ghsync.git` and checks out the **pinned commit** `a7486866b8be162e1321690d2f5991ea33f0f13b` into `/opt/llm-stack/cockpit-ghsync-src`.
3. Runs that revision's documented `install.sh --system` into an isolated `DESTDIR` staging directory, inspects staged file locations, and copies only accepted files to `/usr/local/bin/`, `/usr/share/cockpit/ghsync/`, and `/usr/share/metainfo/`.
4. Saves a root-only manifest of installed paths and file SHA256 hashes in `/etc/llm-postinstall/cockpit-ghsync.json`. A rerun verifies those hashes and does not overwrite modifications. A partially completed install can resume if existing file contents match staged pinned files.
5. **Does not** log into GitHub, clone your repositories, perform a sync, or schedule background jobs.

Authenticate **as the real Linux account you use to log into Cockpit**, *not with sudo*:

```sh
gh auth login
gh auth status
ghsync check
ghsync                 # terminal TUI
```

Open Cockpit → Tools → **GitHub Sync** (reload Cockpit if it was already open). The Cockpit UI runs with the logged-in user's GitHub CLI token/SSH keys; it does not read root's authentication. Choose and review the repository root, owner, clone mode and schedule before initiating a sync. Clones can consume substantial disk space: decide whether to put them on the OS SSD or a deliberately provisioned, writable data directory. The LLM storage module does **not** automatically configure GitHub Sync storage.

Sync and scheduling are optional and always initiated by the user. Only after reviewing [the upstream scheduler instructions](https://github.com/ami3go/ghsync#scheduled-updates), configure a user timer if desired:

```sh
ghsync timer install "*-*-* 00/6:00:00"
# Optional, for background timer when logged out:
sudo loginctl enable-linger "$USER"
```

**No scheduler is installed by the TUI.** Beware of token scope: `gh auth login` may grant access to private repositories, and these repositories are available to whatever account runs GitHub Sync.

### Bookmarks behavior

The installer:
1. Queries the official `ami3go/bookmarks` latest **stable** GitHub release.
2. Accepts only a single `cockpit-bookmarks_*_all.deb` release asset with a `sha256:` digest in GitHub API metadata. Missing or inconsistent digests **fail closed**; the installer does not fall back to unverified downloads.
3. Downloads and validates the Debian package, then installs it with `apt-get install -y /path/to/package.deb`. **No Node.js/npm or source build on the target machine.**
4. Skips an already-installed `cockpit-bookmarks` Debian package without silently upgrading it.
5. Preserves the existing configuration under `/etc/cockpit/cockpit-bookmarks.json` according to upstream Debian packaging behavior and checks for `/usr/share/cockpit/cockpit-bookmarks/manifest.json`.

Access Cockpit → **Bookmarks** (reload the page). Edit entries within Cockpit using an administrator account. This installer **does not** automatically import any bookmarks or enable application launchers.

Bookmarks includes *optional on-demand terminal/application launchers*. These can expose writable shells or other services. Upstream defaults for terminal launchers may bind to the hostname and allow writing; **do not enable them without checking network bind, authentication, write mode and timeout**. Review [upstream security guidance](https://github.com/ami3go/bookmarks/blob/main/SECURITY.md).

**Loopback caveat:** Other installed services are bound to `127.0.0.1` on the **server**. A URL such as `http://{host}:3000` from a browser on your PC may fail because the service is not bound to the server's LAN IP. Use SSH port forwards or a deliberately authenticated reverse proxy. In bookmark URLs, `127.0.0.1` normally refers to the **client browser's** localhost. Configure links to match how your users access the services.

## Operational checks

```sh
sudo python3 install.py --health --component cockpit_ghsync --component cockpit_bookmarks
test -f /usr/share/cockpit/ghsync/manifest.json
test -f /usr/share/cockpit/cockpit-bookmarks/manifest.json
ghsync check
dpkg-query -W cockpit-bookmarks
sudo systemctl status cockpit.socket --no-pager
sudo ss -lntp | grep ':9090'
```

The plugin health checks verify **file presence only**. They do **not** verify successful browser rendering, GitHub authentication, active sync, Bookmarks config validity, auth, or the security of launcher-created network services. Log into Cockpit and run the relevant functions manually.

## Reruns and updates

- GitHub Sync is pinned to the commit above. Rerunning the module validates installed file hashes and exits without updating. If upstream code changes, update the pin and review/tests in a separate PR; the existing state will require a deliberate migration step.
- Bookmarks uses the then-current stable release for its **first** installation. Subsequent invocations detect the installed Debian package and do not auto-upgrade. Update manually using a verified .deb or a dedicated, reviewed future upgrade workflow.
- Neither plugin is automatically uninstalled if unchecked later.
- The plugin modules require Cockpit but do not modify the Cockpit socket/firewall rules themselves. Keep `cockpit.socket` bound to loopback.
- The installer does not claim guaranteed unattended installation or transactional rollback. If a source checksum, staged file, package or service verification fails, inspect the installation log before rerunning.

## Security boundary

GitHub Sync's Cockpit page executes under the logged-in Linux user. Bookmarks permits privileged configuration changes and can launch user applications/terminals. Both therefore belong on a **trusted, authenticated Cockpit deployment**, not on a public unauthenticated dashboard. Do not export GitHub tokens or SSH keys into installer config or GitHub issues.

Relevant source files: `llmsetup/component_cockpit_plugins.py`, `llmsetup/component_base.py`, `llmsetup/health.py`, `tests/test_cockpit_plugins.py`.
