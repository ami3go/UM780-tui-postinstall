# Optional installation safety and Cockpit status modules

These three modules are **unchecked by default**. They complement the existing post-installer's required Debian 13/bare-metal checks; selecting the new modules is an explicit, additional action.

## 1. preflight — conservative read-only safety checks

```sh
python3 install.py --plan --component preflight
sudo python3 install.py --apply --component preflight
```

The optional `preflight` module is first in execution order when selected together with other modules. It checks Debian 13/x86-64/bare-metal constraints, path validity, free space on `/`, `/var` and `/opt`, and existing Cockpit private socket override. A root-only report is written to `/var/log/llm-postinstall/preflight.txt`. A failure stops the run, rather than silently proceeding. This is not a full partition-topology or all-ports proof. Always use `lsblk -f`, inspect intended SSD UUIDs and review [Known Issues](KNOWN_ISSUES.md).

## 2. config_snapshot — protected configuration backup

```sh
sudo python3 install.py --apply --component config_snapshot
sudo ls -l /var/backups/llm-postinstall/snapshots
```

On a completely clean system with no installer-managed configuration, it reports that there is nothing to preserve and exits successfully without creating an empty archive.

Otherwise, the optional module creates a unique mode-0600 `.tar.gz` containing **only** the installer config files, the Cockpit Bookmarks configuration (if present), and installer-prefixed `/etc/systemd/system/llm-*.service` / `*.timer` units. Each regular file gets a SHA-256 digest and file mode in an embedded manifest. Symlinks and unsupported locations are rejected. A file is limited to 5 MiB, total uncompressed config to 16 MiB. The snapshots **contain secrets** such as VNC passwords and must remain root-only. Exclude from unencrypted shared logs or web exports.

To restore a verified snapshot, from the local console or an interactive SSH session:

```sh
sudo python3 install.py --restore-config /var/backups/llm-postinstall/snapshots/um780-config-YYYYMMDDTHHMMSSffffffZ.tar.gz
```

The CLI requires a root shell and the exact typed word `RESTORE`; `--yes` cannot bypass this. It verifies the archive member allowlist, SHA-256 checksums, manifest and sizes **before changing any live file**. A new `before-restore-*.tar.gz` is created for the existing affected configuration before replacement. Restart/reload affected systemd services yourself after verifying changes.

**This is config-file recovery, NOT transactional rollback.** It does not revert APT packages, Git checkouts, SSD partitions, mounts, WebUI/Jupyter databases, model weights, running processes, network policies or upstream application versions. Restoring saved configurations against newer application versions may be incompatible. Test recovery while backups are safely available.

## 3. cockpit_status — read-only installer dashboard

```sh
sudo python3 install.py --apply --component cockpit
sudo python3 install.py --apply --component cockpit_status
```

Open **Cockpit → Tools → UM780 Status** and use Refresh. The static plugin page displays the results of regular unprivileged `systemctl is-active` commands for Ollama, llama.cpp, WebUI, code-server, FileBrowser, JupyterLab, noVNC, Uptime Kuma, watchdog, backup timer and Cockpit. It uses Cockpit's existing login/session, requires no separate daemon, exposes no new TCP port, reads no credential files and has no privileged mutation actions.

A green `active` unit is **not** proof that a model can generate tokens, that auth works, that a backup can restore, that the GPU is used, or that the disk is healthy. Use `sudo python3 install.py --health` and the hardware acceptance checklist.

## Development and acceptance

Tests verify registration/default selection, allowlisted backup paths, symlink rejection, snapshot integrity, explicit restore consent and dashboard safety. CI is mocked on Ubuntu/Python 3.11 and 3.13; real physical Debian 13 UM780 tests are still required.

For service recovery, the `service_watchdog` module in [Optional maintenance](OPTIONAL_MAINTENANCE.md) can report inactive enabled units to the journal. It **does not** force restarts or issue remote notifications.
