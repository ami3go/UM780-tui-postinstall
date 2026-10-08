# Development, testing, and maintenance

## Purpose

This document is for contributors changing the post-install code. Follow [Architecture](ARCHITECTURE.md), [Security](SECURITY.md) and [Known issues](KNOWN_ISSUES.md); this is a root-running system-modification utility, so a bug can alter persistent service config or mount the wrong disk.

## Local workflow

The installer itself has no third-party Python requirements. Use Python 3.11+ with `unittest`; run from repository root:

```sh
python3 -m compileall -q .
python3 -m unittest discover -s tests -v
python3 install.py --plan
python3 install.py --help
```

Do not run the real `--apply` command in developer CI or on a workstation whose disks/services matter; mocked tests are the default. The current CI workflow runs Python 3.11 and 3.13 on `ubuntu-latest` and is **not** a Debian 13/systemd integration test.

## Code map

| File | Responsibility |
| --- | --- |
| `install.py` | Thin CLI entry point |
| `llmsetup/cli.py` | JSON load, TUI, plan/apply/health dispatch, status |
| `llmsetup/core.py` | Root preflight, Runner commands, atomic writes/backup, system accounts and secrets |
| `llmsetup/assets.py` | GitHub asset metadata, integrity, download/cache |
| `llmsetup/storage.py` | Read-only discovery and consented `fstab` + mount |
| `llmsetup/component_base.py` | Installer registry names, dependencies, base/Vulkan/llama |
| `llmsetup/component_llms.py` | Ollama, uv/Open WebUI, Qwen model |
| `llmsetup/component_bookmarks_auto.py` | Installed-app discovery, additive Cockpit Bookmarks config merge, atomic writes and backups |
| `llmsetup/component_novnc_setup.py` | Dedicated noVNC account, 8-character VncAuth credential, VNC/backend and localhost proxy units |
| `llmsetup/component_optional_tools.py` | Optional Debian utilities, verified binaries and local-only Jupyter/VNC/ttyd units |
| `llmsetup/component_cockpit_plugins.py` | Pinned GitHub Sync system files and verified Bookmarks Debian release |
| `llmsetup/component_addons.py` | Cockpit, Quantum, code-server, Tailscale, updates, diagnostics |
| `llmsetup/components.py` | Import/export callable registry |
| `llmsetup/health.py` | Non-destructive probes and report |
| `tests/` | Current mocked helper, storage, policy and workflow tests |
| `.github/workflows/unit-tests.yml` | Python compile, tests, read-only plan on PR/push |

## Add or modify a component

1. Define a module function `def component(r, cfg, ui)`, registered under a unique name and description in the component registry. Maintain dependency order deliberately.
2. Give the module a preflight: Debian/package/architecture, disk space, binary path, conflicting existing service, port use, externally supplied input checks and authorization.
3. Design rerun behavior explicitly. Do not modify unrelated service units, overwrite unmanaged files, or pull arbitrary upstream versions on a silent rerun.
4. Log changes through `Runner` with safe argument arrays (no `shell=True`), and do not log passwords, tokens or secret material.
5. Use a conservative network bind address, an isolated service user, readable-but-restricted env files, and a systemd sandbox appropriate to the needs of the process.
6. Test cold install, already-installed state, interrupted download/config write, failed systemd startup, corrupt upstream asset, symlink/hardlink escape and dependency absence.
7. Update [Configuration](CONFIGURATION.md), [Operations](OPERATIONS.md), [Security](SECURITY.md) and [Acceptance](ACCEPTANCE.md) as applicable. Remove [Known issues](KNOWN_ISSUES.md) entries only with code and evidence.

## Optional Cockpit extension rules

Plugin install code must preserve existing local Cockpit apps; verify upstream source/package identity, stage writes when possible, record installed files, and refuse to overwrite unmanaged paths. Keep GitHub CLI authorization, scheduled sync, and Bookmarks terminal launchers manual. See [Cockpit plugins](COCKPIT_PLUGINS.md) and `tests/test_cockpit_plugins.py`.

## Bookmarks synchronization rules

Do not overwrite user-managed bookmark IDs, names, URLs, history or preferences, even if a generated entry was edited. Keep future-schemas and malformed JSON fail-closed. Preserve original ownership/mode, check before atomic replace, and keep actual modifications out of `--plan` and `--health`. New terminal app templates must be non-root, loopback-only and opt-in on click. Add fixtures in `tests/test_bookmarks_auto.py` and update [Bookmarks auto-configuration](BOOKMARKS_AUTO.md) for every schema change. Remember that Cockpit browser edits use separate optimistic file tags; the installer lock is only advisory.

## Optional tool constraints

Use Debian stable packages when available. When installing upstream release binaries, validate a unique release asset against a SHA256 checksum, do not use `curl | sh`, do not overwrite unmanaged executables, and keep version upgrades explicit. Only localhost ports are allowed for ttyd/Jupyter/VNC/noVNC, and terminal/desktop entry points must run as non-root users. Do not auto-enable a writable terminal or VNC/noVNC service without explicit operator action. Add coverage in `tests/test_optional_tools.py` and update [Optional Tools](OPTIONAL_TOOLS.md).

## Critical contract: storage changes

There is no implicit permission to format or wipe a disk, even if a user selected the storage module. The existing contract permits **only** identifying and mounting a pre-existing, supported filesystem with typed UUID authorization.

Never add:
- `mkfs`, `wipefs`, partition table writing, resize, blind `dd` or disk erase APIs to default operation.
- Auto-approval based on `/dev/nvme1n1` naming or on a candidate being unmounted.
- A path that writes models into `/srv/llm-data` when the expected external filesystem is not currently mounted.
- A second-disk mount operation that can silently replace unrelated entries in `/etc/fstab`.

Add fixtures for GPT partitions, non-root disks, RAID, LVM, LUKS, mounts with multiple devices, UUID collisions, pre-existing fstab lines, a populated target directory, symlinked target, and failed partial mounting.

## Security regression testing

Maintain negative tests for:
- External listeners on every address type including `0.0.0.0`, `::` and specific RFC1918 or Tailscale IPs.
- Preventing unauthorized modifications from FileBrowser to shared models.
- Redaction of secrets in command logs, app configs, crash reports and error messages.
- Refusing non-matching SHA256; malicious tar symlink and hardlink entries.
- Refusing pre-existing unmanaged binaries/configs unless explicitly selected.
- Idempotent file content and permissions under repeated execution.

The current tests cover only a **subset** of these. A green unittest job does not close a live permission or storage safety gap.

## Evidence requirements for PRs

- State which components, configuration files, systemd services and persistent paths changed.
- Include deterministic tests showing both success and safe failure.
- Include logs or sample output **without any secrets**.
- If a fix affects data paths, document migration and backup behavior; no silent destructive upgrade.
- For on-hardware claims, attach the Debian version, AMD firmware/kernel/Mesa, model/checksum, command, result and reboot outcome (sanitized).

## CI and release gates

Current CI: syntax compilation + unittests + `--plan` on Ubuntu for Python 3.11/3.13. Keep it green. Separately, obtain full [physical acceptance evidence](ACCEPTANCE.md) for the UM780 Pro.

Release should remain **pre-release** until all BLOCKER and HIGH safety gaps in [Known issues](KNOWN_ISSUES.md) are resolved, critical services work on actual Debian 13 hardware, and a documented rollback/recovery method exists.

## Documentation style

Use precise status words: `implemented` for code present, `unit-tested` for mocked tests, `integrated` for real end-to-end proof, and `verified on UM780 Pro` only with dated evidence. Avoid calling a service "read-only", "secure", "fully idempotent" or "GPU accelerated" without executable enforcement and relevant tests.

Any stale docs that claim such guarantees should be updated in the same PR as the implementation.
