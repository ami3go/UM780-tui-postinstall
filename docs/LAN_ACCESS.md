# Optional LAN access

By default every web service listens on `127.0.0.1` only and is reached through an SSH tunnel (see [Operations](OPERATIONS.md)). On a **trusted** LAN you can opt in to direct access with two helper scripts in `scripts/`. Neither is run by the installer.

> **Security:** Ollama's API has no authentication. With LAN access enabled, any device on the network can run, pull and delete models. code-server is served over plain HTTP, so browser features that need a secure context (clipboard, some extension webviews) may not work from LAN clients.

## Listen on the LAN: `scripts/lan-access.sh`

```sh
sudo sh scripts/lan-access.sh enable    # bind services to 0.0.0.0 and restart them
sh scripts/lan-access.sh status         # show listening addresses
sudo sh scripts/lan-access.sh disable   # back to localhost only
```

`enable` writes systemd drop-ins named `zz-lan-access.conf`; the installer's unit files are not edited, and installer reruns do not remove the drop-ins.

| Service | Port | How the bind is changed |
| --- | --- | --- |
| Ollama | 11434 | Extra `EnvironmentFile` (`/etc/llm-postinstall/lan-ollama.env`) setting `OLLAMA_HOST=0.0.0.0:11434` |
| Open WebUI | 3000 | `ExecStart` override, `--host 0.0.0.0` |
| code-server | 8443 | `ExecStart` override, `--bind-addr 0.0.0.0:8443` |
| FileBrowser Quantum | 8082 | `ExecStartPre` copies `config.yaml` to `/run/llm-filebrowser-lan/` with `listen: 0.0.0.0` |
| noVNC | 6080 | `ExecStart` override for the web proxy; the VNC backend stays on `127.0.0.1:5902` |
| Cockpit | 9090 | `cockpit.socket` drop-in resetting `ListenStream` to `9090` |

The `ExecStart` overrides copy the installer's current command line and change only the address. If an installer rerun changes a command (for example a new FileBrowser version path), run `enable` again. `enable` refuses to write anything if it cannot find the expected address in a unit.

No firewall rules are added. If you run one, allow the ports above from your LAN.

## Bookmarks for LAN clients: `scripts/cockpit-bookmarks-lan.py`

The installer's Cockpit Bookmarks cards link to `127.0.0.1`, which only works through a tunnel. This script switches installer-managed cards to the `{host}` placeholder (the address the browser used to open Cockpit), drops their SSH-tunnel notes, and adds **Cockpit** and **Ollama API** cards.

```sh
python3 scripts/cockpit-bookmarks-lan.py                                  # preview
sudo python3 scripts/cockpit-bookmarks-lan.py --apply                     # write, with timestamped .bak
sudo python3 scripts/cockpit-bookmarks-lan.py --apply --remove-samples    # also drop the plugin's sample cards
```

Re-running is safe; an unchanged config is not rewritten. Cards you added yourself are never modified. The installer's bookmark auto-sync only adds missing cards, so the result survives installer reruns; cards it adds later will again use `127.0.0.1` until you rerun the script.

To undo, copy the `.bak` file the script printed back over `/etc/cockpit/cockpit-bookmarks.json`.
