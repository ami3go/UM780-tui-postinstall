# Security model and storage safety

## Scope and trust assumptions

Designed for a **trusted private LAN, single-operator Debian 13 bare-metal host**. This is **not a hardened multi-tenant LLM platform**. The installer executes as root, installs third-party binaries and services, and changes persistent system configuration. Its hardening is partial and has **not** undergone an independent threat model, penetration test or bare-metal acceptance.

**Security policy:** keep all LLM and management HTTP endpoints on `127.0.0.1`, access them via SSH forwarding or an independently configured authenticated ingress, avoid publishing unauthenticated APIs, and require explicit operator approval for mounting existing storage.

## Network exposure

| Endpoint | Intended listener | Auth at application/API layer |
| --- | --- | --- |
| Ollama | `127.0.0.1:11434` | **None** |
| llama.cpp after GGUF | `127.0.0.1:8081` | **None configured** |
| Open WebUI | `127.0.0.1:3000` | Application login; needs live verification |
| FileBrowser Quantum | `127.0.0.1:8082` | Generated admin password; permission review needed |
| code-server | `127.0.0.1:8443` | Generated password |
| Cockpit | `127.0.0.1:9090` | PAM/Linux account over HTTPS |

The `webui_bind` JSON key does **not** control binding; addresses are written into unit/config templates. `tailscale` installs/enables a daemon but does not enroll or expose services automatically. An incorrectly configured outside service may still be reachable even if this installer's own unit is localhost-bound.

Check all listening sockets manually:

```sh
sudo ss -lntp
sudo python3 install.py --health
sudo systemctl list-units '*ollama*' '*code-server*' '*cockpit*'
```

The current `--health` wildcard-listener check does not reliably detect listeners bound to a **specific** external IP, unexpected ports or sidecar services. Exit status 0 is not a security attestation.

## FileBrowser Quantum: outstanding write-permission risk

The `filebrowser` module currently joins the `filebrowser` system account to `llmshare` and creates the model directory group-owned by `llmshare` with mode `2775`. That allows group write access. The generated FileBrowser Quantum config does **not** set per-source immutable/read-only filesystem restrictions or fully restrict default user permissions.

**Therefore the interface is NOT guaranteed read-only.** Treat its account as permitted to modify or delete models wherever Linux ACLs allow it. This conflicts with the current description in the installer component list and must be fixed in code and tested before production use. Until then, do not expose FileBrowser or permit untrusted users to log in. Limiting the UI does not replace kernel-level filesystem permissions.

## Storage integrity

The storage module does **not** call `mkfs`, `wipefs`, disk repartitioning, resizing or forced overwrite tools. It can, with consent, modify `/etc/fstab` and mount an **existing** filesystem. This is still a privileged operation.

Safeguards actually implemented:

1. Collect `lsblk --json` details; propose unmounted ext4/XFS/Btrfs partitions whose parent disk was not identified as root.
2. Display candidates; ask consent; require typing the **exact selected filesystem UUID**.
3. Refuse to shadow a nonempty `/srv/llm-data` directory, and refuse certain duplicate fstab destinations/UUIDs.
4. Back up the existing fstab on write, then attempt a mount. Attempt to restore fstab if mounting fails.
5. Persist model directory selection to `/etc/llm-postinstall/storage.json`.

Safeguards **not** implemented:

- Verify human intent beyond the UUID, automatically take a full disk/filesystem backup, or independently verify physical drive identity.
- Detect every RAID/LVM/dm-crypt/loop/multipath or unusual mount layout safely.
- Check the **backing UUID of an already mounted** `/srv/llm-data`. The code currently trusts that mountpoint.
- Guarantee atomic recovery of all changes after interruption (power loss, process kill or I/O failure).
- Validate all model directory permissions on every repeated run.
- Prevent an operator from manually passing an arbitrary first-run `model_storage` JSON path (this input needs stronger validation).
- Format an unformatted disk. **Formatting is out of scope even after consent**.

**Required manual preflight:**

```sh
lsblk -e7 -o NAME,PATH,SIZE,FSTYPE,UUID,MOUNTPOINTS
findmnt -no SOURCE,UUID,TARGET /
findmnt -no SOURCE,UUID,TARGET /srv/llm-data || true
sudo cat /etc/fstab
```

If anything is ambiguous, stop and inspect from a local console. The acceptable fallback is to **decline** storage changes and use the system SSD; no change to existing partitions is necessary.

## Secrets and sensitive information

Generated secrets live under `/etc/llm-postinstall/` and are reused when possible. Runner-generated log files use `0600` and the environment files are root-readable only. Avoid sharing `/etc/llm-postinstall/` or log archives publicly. `last-run.json` can contain error messages and paths, so treat it as operationally sensitive.

- Password files are **bootstrap/admin artifacts**, not a supported credential-rotation system.
- Open WebUI's `WEBUI_ADMIN_EMAIL`/`WEBUI_ADMIN_PASSWORD` work only for an empty user database; changing the file does not reset an existing user.
- FileBrowser Quantum's admin password appears in the generated YAML config and should be protected as carefully as the original root-owned password file.
- SSH key setup, firewall rules, password rotation, audit/retention policy and TLS certificate provisioning are **not** managed here.

## Software supply chain

- `assets.py` downloads selected official GitHub release assets only when the release API includes an `sha256:` digest and the downloaded bytes match it. This checks consistency with the API, **not an independently pinned trusted checksum**.
- `llama.cpp` is cloned from a dynamic latest upstream tag; no independently pinned commit or source signature check in this project.
- `uv pip` installs Open WebUI and torch without a committed lock file; different dates can install different versions.
- The Tailscale repository key/list is fetched over HTTPS and checked only superficially; **no pinned signing-key fingerprint** is validated before trusting it.
- The tar extraction precheck rejects unsafe *member paths* but does **not thoroughly validate symlink/hardlink targets** in archives. Do not regard tar unpacking as safe against a malicious upstream archive.
- APT repository package signatures are enforced by the configured Debian/Tailscale repository mechanisms, subject to correct host trust configuration.
- GitHub Actions exercises mocks; it does not vulnerability-scan dependency trees or execute real third-party install binaries.

See [Known issues](KNOWN_ISSUES.md) for prioritized remediation before promoting this project as secure for non-expert deployment.

## Minimum acceptance conditions

Do not mark a real installation accepted until:
- External backups of disks/application data were verified.
- Actual `ss -lntp` shows no unexpected externally exposed service.
- User login/access tests and permissions are exercised, including a **negative write test** for FileBrowser.
- Runtime model generation, systemd restart behavior and two reboot cycles pass.
- GPU offload is shown by llama.cpp logs and measured CPU/GPU benchmark comparison.
- All blocker findings are closed with code fixes and regression tests.

Full sign-off template: [ACCEPTANCE.md](ACCEPTANCE.md).
