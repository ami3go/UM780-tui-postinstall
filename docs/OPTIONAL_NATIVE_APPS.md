# Optional native coding-agent, router, monitoring, and UPS modules

All five modules are **unchecked by default**, install no Docker, and do not silently configure externally reachable listeners. Use `sudo python3 install.py --apply --component NAME` on Debian 13 bare metal.

| Module | Action | Network and follow-up |
| --- | --- | --- |
| `opencode` | Installs official SHA256-verified OpenCode Linux x64 CLI from tag `v1.18.32`, linked in `/usr/local/bin` | Run `opencode auth` per-user; no server |
| `llama_swap` | Installs official SHA256-verified llama-swap v262 binary | No daemon; prepare model command mapping yourself, then start localhost-only after review |
| `uptime_kuma` | Installs pinned 2.5.0 Git source with Node.js/npm, native `llm-uptime-kuma.service` as an unprivileged user | Runs on **127.0.0.1:3001**; first-visit admin creation; manual monitor/notification setup |
| `secure_ingress` | Preflight checks Tailscale is installed and enrolled | Does not automatically enable Serve, TLS, funnel, firewall or network listeners; prints manual next steps |
| `ups_wol` | Clones the owned [Cockpit UPS/WOL project](https://github.com/ami3go/cockpit-ups-wol) under `/opt/llm-stack`, verifies origin | Source preparation **only**; hardware-independent `install.sh --check` and explicit dry-run/TUI setup happen separately |

## Application cards

The normal Bookmarks auto-sync adds **Uptime Kuma** as a web link on `http://127.0.0.1:3001/` when its systemd unit has been installed. OpenCode can be added as an on-demand terminal card only when the ttyd executable is available. Both require individual SSH port forwards on the browser client. Neither bookmark initiates authentication or installs external AI coding providers.

## Native installation safety and limitations

- Upstream tar archives are verified against official GitHub release SHA256 digests or release-supplied checksum files. Only the matching, regular executable member is extracted; no tar shell extraction, no unapproved symlink overwrites and no script pipes.
- **Uptime Kuma v2.5.1 has a known broken native dependency manifest**; pin `2.5.0` and refuse unexpected checkout/remotes/empty package manifests. `npm ci` and `npm run download-dist` execute third-party install steps; this must be supervised and tested on target hardware before trusted deployment. <https://github.com/louislam/uptime-kuma/issues/7752>
- Uptime Kuma is powerful enough to request URLs and execute monitoring operations as its local process account. Keep its admin login private and never expose TCP 3001 directly to LAN/WAN.
- `llama_swap` is installed without models, YAML configuration or listener. Configuring it to run llama-server is a separate explicit decision; use allowlisted GGUF paths and preserve your existing running LLM services.
- `secure_ingress` is a **readiness check, not a complete HTTPS deployment**. Tailscale Serve should only be configured after reviewing identity, ACLs and which service is intended to be exposed. Do not use unauthenticated Funnel for Ollama.
- `ups_wol` clones the current repo code for later inspection. **It does not run the privileged installer or arm UPS operations**. Review the source, run `./install.sh --check` and use its native dry-run TUI only with validated NUT hardware and a safe power topology. Source checkout is unpinned: this is preview-only, never a reproducible deployment.
- Upgrades and full removals are not automated. Real Debian 13/UM780/Browser integration is not yet verified; see [Known Issues](KNOWN_ISSUES.md).

## Example

```sh
sudo python3 install.py --apply --component opencode
sudo python3 install.py --apply --component llama_swap
sudo python3 install.py --apply --component uptime_kuma
sudo python3 install.py --apply --component secure_ingress
sudo python3 install.py --apply --component ups_wol
sudo python3 install.py --apply --component bookmark_sync
```

Uptime Kuma first-run auth through your SSH forwarded `localhost:3001`. Do not reuse root credentials in monitoring application settings.
