# Automatic Cockpit Bookmarks app cards

The **Cockpit Bookmarks** extension (`ami3go/bookmarks`) supports regular web links and on-demand terminal/application launcher cards. This project automatically creates appropriate entries for applications installed by the UM780 post-install script.

## Default behavior

`config.json` contains `"auto_bookmarks": true`. After any successful **apply** run, the installer checks whether Cockpit Bookmarks is installed. If it is, it scans known application service files and binaries and **adds missing cards**. If the plugin is not installed, nothing happens.

The TUI also has a standalone `bookmark_sync` module for rescan (does not install applications):

```bash
python3 install.py --plan --component bookmark_sync
sudo python3 install.py --apply --component bookmark_sync
sudo python3 install.py --health --component bookmark_sync
```

To disable automatic changes, set `"auto_bookmarks": false` in your `config.json`. The explicit `bookmark_sync` component still works when called intentionally. `--plan` and `--health` never modify the Bookmarks configuration. A failure to sync automatically is recorded as a warning in the installer's last-run result rather than rolling back unrelated successful components.

The Bookmarks plugin should be installed first, for example:

```bash
sudo python3 install.py --apply --component cockpit --component cockpit_bookmarks
sudo python3 install.py --apply --component bookmark_sync
```

## Generated web application cards

Web cards are created **only if their systemd service unit is installed**, not merely because the component was selected in a plan.

| Card | Local URL entered in Bookmarks | Prerequisite |
| --- | --- | --- |
| Open WebUI | `http://127.0.0.1:3000/` | `llm-webui.service` exists |
| code-server | `http://127.0.0.1:8443/` | `llm-codeserver.service` exists |
| FileBrowser Quantum | `http://127.0.0.1:8082/` | `llm-filebrowser.service` exists |
| JupyterLab | `http://127.0.0.1:8888/lab` | `llm-jupyterlab.service` exists |
| noVNC Desktop | `http://127.0.0.1:6080/vnc.html` | `llm-novnc.service` exists; generated VNC password remains in `/etc/llm-postinstall/novnc-vnc-password` (root only) |

Cards are grouped under **UM780 Web Apps**, tagged `um780` and `ssh-tunnel`, with automatic status polling disabled (the server can have a live localhost port that the user's browser cannot access). Some service units may be provisioned disabled until the operator activates them. **The novnc component is different:** selecting it now configures and enables its own dedicated VNC :2 desktop and noVNC browser proxy. The bookmark displays a retrieval hint for the root-held VNC password but never the secret itself; see [noVNC Desktop](NOVNC_DESKTOP.md). A bookmark is not proof that its backend is running.

**Important: `127.0.0.1` in a bookmark points to the BROWSER's computer.** The installer does **not** weaken the service's server-side loopback binding or create a proxy. For each desired service, forward its TCP port via SSH:

```bash
ssh -N -L 3000:127.0.0.1:3000 \
  -L 8443:127.0.0.1:8443 \
  -L 8082:127.0.0.1:8082 \
  -L 8888:127.0.0.1:8888 \
  -L 6080:127.0.0.1:6080 \
  user@SERVER_IP
```

Now those links can open from the same client computer. A browser running on a different machine without forwarding those ports will not be able to open them. Use a separately authenticated reverse proxy if you prefer server-hostname URLs; that is not configured by this feature.

The existing **GitHub Sync** and **Bookmarks** Cockpit plugins already appear in the Cockpit navigation, so they are not duplicated as external web links. Native VNC port 5901 is not an HTTP URL and is deliberately not emitted as a web link. API endpoints without authentication (Ollama/llama.cpp) are also deliberately excluded.

## Generated terminal application cards

When the verified ttyd executable has been installed at `/opt/llm-stack/bin/ttyd`, the synchronizer can add actual Cockpit Bookmarks `gotty-launcher` entries with **ttyd** as the provider. These are compatible with Bookmarks' on-demand **Applications** manager.

| Application | Command run on the Cockpit host | Suggested port |
| --- | --- | --- |
| Fish Shell | `fish` | 47200 |
| btop | `btop` | 47201 |
| Midnight Commander | `mc` | 47202 |
| Agent of Empires | `aoe` | 47203 |

Cards are created only if both ttyd and the respective command are detected. An occupied *configuration-assigned* port is skipped; the first available port within 47200–47299 is chosen. The cards use `127.0.0.1` binding, **on-demand** process startup, and a 30-minute maximum runtime. They do **not** launch when generated or on boot. They run as the **currently signed-in Cockpit Linux user**, not as root.

Example after installing ttyd and the CLI applications:

```bash
sudo python3 install.py --apply --component ttyd --component fish --component btop --component mc --component agent_of_empires
sudo python3 install.py --apply --component bookmark_sync
```

An on-demand terminal card needs its **own** SSH tunnel, e.g. `ssh -N -L 47202:127.0.0.1:47202 user@SERVER_IP` for Midnight Commander. The Bookmarks frontend starts the ttyd process under that port when the card is opened. Without the tunnel, a browser on another machine cannot connect; the card can appear to fail after starting the user service. A host-level listener also can already occupy the port even when not reserved in Bookmarks; that will be detected by Bookmarks at launcher startup.

**Security:** These terminal cards are writable shell processes. Even when bound to loopback, other processes on the same host can contact them. Do not treat them as equivalent to a separately authenticated terminal gateway. Disable the `bookmark_sync` run or remove individual generated launchers if this risk is unacceptable. Using SSH directly is generally the safer administrative terminal.

## Data and rerun guarantees

The tool manages only entries with deterministic IDs such as `um780-webui` and `um780-mc`, adding `um780ManagedBy: "um780-postinstall"` to the generated entries. It never deletes cards, overwrites existing cards, or modifies a manually edited entry even if its ID matches a generated ID. It avoids duplicates on ID, name, or URL.

- Original title, display preferences, groups, service ordering, custom keys and history are preserved.
- New groups are appended to `groupOrder` only if needed.
- Files are written to `/etc/cockpit/cockpit-bookmarks.json` only if something new is found. Existing file permissions and owner/group are retained.
- Before each real change, a timestamped backup of the previous raw file is saved under `/var/backups/llm-postinstall/`.
- Invalid JSON, unsupported future schema versions, symlinked config files, files over the upstream read budget, and oversized output are refused without writing.
- An advisory installer lock is taken and file content is checked before replacement. This does **not** fully coordinate with the Bookmarks browser UI's optimistic file-tag writes; avoid simultaneous editing in Cockpit while syncing.

No registry for removed applications is kept. Uninstalling a service therefore does **not** automatically remove its old card. Removing cards is an explicit user action in the Bookmarks UI.

## Verification

```bash
sudo python3 install.py --health --component bookmark_sync
sudo cat /etc/cockpit/cockpit-bookmarks.json
sudo ls -lt /var/backups/llm-postinstall/cockpit-bookmarks-*.json
python3 -m unittest discover -s tests -v
```

`--health` verifies only file presence. After installing or syncing, refresh Cockpit Bookmarks and check that cards render, nonmatching manual entries remain unchanged, web links work through tunnels, and application launcher start/stop works for the signed-in user. This feature is still **not integration-tested on the physical UM780 Pro**.

Upstream documentation: [Cockpit Bookmarks](https://github.com/ami3go/bookmarks), [terminal launcher format](https://github.com/ami3go/bookmarks/blob/main/docs/GOTTY-LAUNCHERS.md).
