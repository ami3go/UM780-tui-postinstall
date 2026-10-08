# Installed / configured software verification

The UM780 Debian 13 installer can now **inspect the local machine without changing it**. Each of the 39 components is reported separately: a binary or Debian package being present is not proof of a configured, running service, and an active service is not proof its login/model/permissions are correct.

## Inspect the machine

```sh
# All 39 components, selected and optional, grouped in canonical install order
python3 install.py --inventory

# JSON for scripts or offline review (no passwords, tokens, or config values)
python3 install.py --inventory --json

# Inspect an entire stage INCLUDING its unchecked optional modules
python3 install.py --inventory --stage 3

# Inspect one or more components
python3 install.py --inventory --component ollama --component webui
```

The inventory works without sudo when local file/package permissions allow. No package is installed or upgraded, no systemd service is started or restarted, and no config, disk, or model is changed by this command. Running as root may allow checking private config files but does **not** cause privileged actions. `--json` is accepted only with `--inventory`.

### Interpreting reported status

| Status | Installed evidence | Configuration evidence | Meaning / follow-up |
| --- | --- | --- | --- |
| **NOT INSTALLED** | No | No | Required package or executable missing |
| **INSTALLED ONLY** | Yes | No | Binary/package exists; required managed configuration is absent or incomplete |
| **CONFIGURED ONLY** | No | Yes | Configuration artifacts remain but software is missing (potential stale installation) |
| **INSTALLED + CONFIGURED** | Yes | Yes | Both available, but runtime/authentication still require verification |
| **INSTALLED / SETUP UNVERIFIED** | Yes | Cannot be proven | Per-user login, password, hardware setup or external tool configuration cannot be checked safely |
| **UNVERIFIED** | Unknown | Unknown | Probe unavailable, e.g. Ollama stopped when model presence must be queried |
| **ACTION PENDING / DONE / UNKNOWN** | N/A | N/A | A one-shot operation such as `preflight`, snapshot, benchmark or bookmark rescan, not a persistent service |

Runtime is a **separate** column: `RUNNING`, `STOPPED` or `N/A`. These values are read-only results of `systemctl is-active` on applicable services; a stopped but intentionally disabled ttyd/VNC template can still be installed/configured.

### What is actually checked

- **Packages and executables:** local Debian dpkg status, binaries on PATH, managed versioned binaries under `/opt/llm-stack`, or Cockpit page manifests. No internet queries or downloading of releases.
- **Managed configuration:** selected `/etc/llm-postinstall/` files, localhost service units, Cockpit files, systemd enablement where relevant, selected storage configuration and valid JSON structure.
- **Service activity:** `systemctl is-active` for applicable services, including Ollama, WebUI, Cockpit, code-server, noVNC, watchdog, and backup timer.
- **Model availability:** `GET http://127.0.0.1:11434/api/tags` with short timeout, looking for the `model` named in `config.json`. If Ollama's local API is unavailable, presence is **unknown**, not absent.
- **Network identity:** Tailscale status reports whether the local daemon is enrolled and running; no ACLs, Serve routes or internet exposure are inferred.
- **Action history evidence:** report/snapshot files for selected one-shot modules. A report's presence does not mean an old result is still valid.

Certain types of configuration are deliberately **unverifiable from the root installer**: OpenCode provider credentials belonging to a user; Agent of Empires sessions; a manually configured per-user TigerVNC desktop; hardware-backed UPS/WOL. The result is not guessed. Likewise, FileBrowser's model read-only isolation is a known unresolved security issue: a configuration file being present does **not** resolve it.

## In the staged installer

Each of the five TUI category checklists displays a concise status next to the corresponding module, for example:

```text
STEP 2/5: Local LLM engines and models
[x] vulkan       [CONFIGURED] AMD firmware and Mesa...
[x] ollama       [INSTALLED]  Ollama native service...
[x] llama        [MISSING]    Build llama.cpp...
[ ] llama_swap   [UNVERIFIED] Model router...
```

The plan also shows `Current: ...; runtime: ...` for every selected component. The installer **does not automatically uncheck, skip, repair, reinstall or remove existing applications based on this scan**. The detection is informational, not an authorization to overwrite configs or bypass explicit SSD UUID approval.

After a selected module's installer finishes, a second inspection for that module records `status`, `installed`, `configured` and `running` under `verification` in `/var/lib/llm-postinstall/last-run.json`. An installation result of `OK` means the module function returned successfully; a separate `INSTALLED ONLY`/unverified status is still possible when manual follow-up is required.

```sh
# First inspect; then review setup plan; then choose what to install
python3 install.py --inventory --stage 1
python3 install.py --plan --stage 1
sudo python3 install.py
sudo python3 install.py --health
```

## Limits and cautions

Inventory is a **local evidence scan**, not exhaustive functional acceptance. In particular it does not:
- test actual first-login passwords for Open WebUI, FileBrowser, JupyterLab, VNC or Cockpit;
- prove AMD GPU offload, model response correctness, SSD backing UUID, or backup restorability;
- guarantee any package is at the correct version, or that unmanaged installations are safe;
- change service state or remove stale configuration files.

A missing/inaccessible private config can look `INSTALLED ONLY` when scanning as an unprivileged user. For precise evaluation, run the read-only command under `sudo`, review the existing [health checks](OPERATIONS.md), and perform physical [acceptance testing](ACCEPTANCE.md). Do not paste privileged configuration files or credentials into logs.
