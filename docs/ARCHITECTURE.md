# Architecture and implementation notes

## Scope and constraints

This is a **single-host, bare-metal Debian 13 (x86_64) installer** tailored for the UM780 Pro. The installer itself is Python 3.11+ standard library plus external OS utilities (`apt-get`, `systemctl`, `lsblk`, `mount`, `git`, `cmake`). It selects Debian packages, downloads vendor releases, configures native systemd services and checks runtime state. It has no Docker orchestration, config transaction manager, installer-level scheduler or generalized hardware discovery engine.

## Execution path

```text
install.py
  |
  v
llmsetup/cli.py
  +- load_config(config.json + persisted storage.json)
  +- --plan ----------> print high-level plan + preflight warnings
  +- --health --------> llmsetup/health.py (read-only probes)
  \- TUI / --apply
       +- optional whiptail checklist / numbered fallback
       +- review + confirmation
       +- preflight: Debian 13, x86_64, systemd, bare metal
       \- each selected component, in fixed registry order
            +- Runner.run(argv) / Runner.apt() / Runner.service()
            +- Runner.write(): managed-marker enforcement for owned files
            +- Runtime success/failure per module
            \- last-run.json
                  |
                  \- health.render(): shallow local checks
```

The component registry in `llmsetup/components.py` imports functions from:

- `component_base.py`: module list/description, base packages, storage, AMD Vulkan, llama.cpp.
- `component_llms.py`: Ollama, uv/Python/Open WebUI, optional Qwen pull.
- `component_bookmarks_auto.py`: post-apply plugin detection, installed service/CLI discovery, safe additive JSON merge, backup and concurrency check.
- `component_novnc_setup.py`: secure noVNC dedicated user, VNC auth password generation, two localhost systemd services (:2 VNC and web proxy).
- `component_optional_tools.py`: Fish/btop/MC APT packages; verified ttyd and AoE executables; non-root Jupyter; disabled VNC/noVNC systemd units.
- `component_cockpit_plugins.py`: Pinned upstream GitHub Sync Cockpit plugin; digest-verified Bookmarks Debian plugin.
- `component_addons.py`: Cockpit, FileBrowser Quantum, code-server, Tailscale, unattended security upgrades, benchmark prerequisites.
- `storage.py`: existing-filesystem candidate discovery, fstab entry construction, mount.
- `core.py`: command execution, managed write/backups, system services, secrets, accounts and host preflight.
- `assets.py`: release-asset SHA256 validation, streamed download and cache.
- `health.py`: systemd, localhost ports, Vulkan, mount and listener checks.

Plugin installers require the loopback Cockpit socket override and use upstream releases; they have no independent always-on TCP service. See [Cockpit plugins](COCKPIT_PLUGINS.md).

After an apply run, the optional Bookmarks post-hook detects installed apps and adds missing cards, without altering existing app entries or starting any services. The `bookmark_sync` module also allows an explicit rescan; see [Bookmarks auto-configuration](BOOKMARKS_AUTO.md).

This is modular **at the function/registry level**, not a third-party plugin interface. New modules require code changes and tests.

## Service and client topology

```text
Browser/IDE/client on trusted PC
      |
      | SSH -L over local LAN or Tailscale SSH transport
      v
SSH server on Debian 13
  +- localhost:3000  Open WebUI --HTTP--> localhost:11434 Ollama
  +- localhost:11434 Ollama API  [unauthenticated]
  +- localhost:8081  llama.cpp API (only after GGUF selected)
  +- localhost:8082  FileBrowser Quantum
  +- localhost:8443  code-server
  \- localhost:9090  Cockpit HTTPS (PAM)
       +- Tools / GitHub Sync (per-user gh credentials)
       \- Bookmarks (optional on-demand launchers only)
  
  /dev/dri/renderD* <-- Vulkan/Mesa for llama.cpp, when working
  /srv/llm-data/models or /var/lib/llm-stack/models
       +- ollama/
       \- gguf/
```

Optional localhost endpoints use ports 7681 (ttyd), 8888 (JupyterLab), 5901 (TigerVNC) and 6080 (noVNC). ttyd and the user-specific VNC template require explicit activation; selecting novnc activates an independent :2 VNC backend and web proxy, and AoE provides only the per-user TUI. See [Optional Tools](OPTIONAL_TOOLS.md) and [noVNC Desktop](NOVNC_DESKTOP.md).

**Ollama and llama.cpp are separate processes and model layouts.** Open WebUI's configured backend is Ollama; the installer does **not** automatically register llama.cpp as an OpenAI-compatible backend in WebUI. It also does not set up a fronting proxy, LAN firewall, Tailscale Serve, DNS, external TLS certificate, high availability or GPU/CPU autoscheduling.

The Radeon 780M has shared memory. GPU enumeration and offload depend on driver/backend, BIOS memory allocation and model support; do not infer accelerator use solely from `vulkaninfo` or from the existence of the device node.

## Files, data and permissions

The installer owns files with a header `# Managed by debian-llm-postinstall` where `Runner.write` uses its default owned-file policy. Some files such as `/etc/fstab` and persisted storage JSON are written with `owned=False`; these are not generally safe to overwrite manually.

Relevant ownership and access design:
- `llama`, `ollama`, `openwebui`, `filebrowser` and `codeserver` are system users created for their respective services.
- Shared model directory is created as group `llmshare` with mode `2775`. **This means group members may write to the directory**. FileBrowser belongs to that group; the current code does not guarantee read-only access.
- systemd unit files are placed under `/etc/systemd/system/`; additional `ProtectSystem`/`NoNewPrivileges` safeguards are configured on most application units, but not equivalent to a fully audited sandbox.
- All listening addresses should be independently inspected. API authentication is not configured for Ollama or llama.cpp.

See [Security](SECURITY.md) for residual risks and [Configuration](CONFIGURATION.md) for exact paths.

## State machine and failures

`execute()` checks root and host compatibility, then runs modules in registry order, recording `OK` or `FAILED` in `last-run.json` after each attempt. On failure, a normal interactive run offers the choice to continue; the `--yes` mode stops on the first module error. Some modules may have partially completed before an exception; there is **no global rollback**. The next rerun is intended to skip compatible existing work but may not always do so.

- `Runner.write` avoids rewriting identical content and backs up existing files **only when changes go through this helper**.
- Upstream binaries are downloaded from release APIs and checked against API-provided SHA256 hashes. `llama.cpp` source, apt repositories, Tailscale key and Python package downloads have separate trust mechanisms.
- Version pinning is inconsistent: certain release selections are dynamic, and dependencies in Open WebUI are not locked. CI cannot certify reproducible deployment.
- `health.render()` returns nonzero only for `FAIL` records. Service inactivity often produces `WARN`; `llama` inactivity is always `PENDING`. It does not send authenticated HTTP requests, run a model, or verify GPU offload.

## Storage behavior

`storage.configure_storage()` uses `lsblk --json` and excludes detected disks backing the root filesystem. It proposes certain existing unmounted ext4/XFS/Btrfs partitions with UUIDs, asks for explicit consent and an exact UUID, then adds a managed line to `/etc/fstab` and invokes `mount /srv/llm-data`.

Limitations matter:

1. Root-on-LVM, encrypted or multipath layouts may be ambiguous; operator verification is mandatory.
2. Candidate selection is not a claim that a filesystem is empty, expendable or physically the second NVMe.
3. If `/srv/llm-data` was already mounted, the code reuses it without validating its backing UUID.
4. No filesystem contents backup exists, and no robust transaction or mount rollback is guaranteed on every exception.
5. Mounted model storage must be available before launching the inference daemons.

## Testing layers

| Layer | Current coverage | What remains |
| --- | --- | --- |
| Static Python compile | GitHub Actions | Does not exercise services or imported binaries |
| Unittest with mocks | Storage candidate rules, safety helpers, CLI invariants | Not destructive device testing or live services |
| `--plan` on CI | Plan is callable without changes | No exact runtime preflight on Debian hardware |
| `--health` | Local status/probe heuristics | No model, auth, permission or thermal proof |
| Physical UM780 Pro | **Not yet validated** | Acceptance tests in [ACCEPTANCE.md](ACCEPTANCE.md) |

## Planned extension pattern

New components should be a dedicated installer function, registered in `components.py`, with explicit prerequisite checks, tests for repeated execution and failure recovery, logged changes, and a doc update. Keep install/uninstall and network exposure as separate operator-authorized actions. Do not add hidden disk formatting, background update agents or implicit port publishing.
