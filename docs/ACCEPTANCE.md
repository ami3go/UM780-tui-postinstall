# Hardware acceptance and release sign-off

**Target:** Minisforum UM780 Pro, Ryzen 7 7840HS / Radeon 780M, 64 GB RAM, two 512 GB NVMe devices; Debian 13 minimal bare-metal. **Status: NOT EXECUTED on this target by the project.**

Fill in every field while performing real checks. Do not mark items green from Python unit tests or the installer `--health` output alone. Any open BLOCKER or HIGH finding in [KNOWN_ISSUES.md](KNOWN_ISSUES.md) is a **NO-GO for production / unattended installation**.

## Test record (operator completes)

| Field | Value |
| --- | --- |
| Test date/time/timezone | _not yet recorded_ |
| Tester | _not yet recorded_ |
| Host model/serial (private record only) | _not yet recorded_ |
| BIOS/UEFI | _not yet recorded_ |
| Debian/kernel | _not yet recorded_ |
| Mesa/Vulkan/AMD firmware | _not yet recorded_ |
| Repository revision (commit SHA) | _not yet recorded_ |
| Python/uv/llama.cpp/Ollama/WebUI versions | _not yet recorded_ |
| Disk UUIDs/mounts | _not yet recorded_ |
| Model identifier, quantization and checksum | _not yet recorded_ |
| Test evidence storage path | _not yet recorded_ |
| Final result | **NOT RUN / NO-GO** |

## A. Preconditions and data safety

- [ ] A restore-tested backup exists for OS + model disks and relevant service databases.
- [ ] `cat /etc/os-release` shows Debian 13; `uname -m` is `x86_64`; native systemd active.
- [ ] `lsblk -f`, `findmnt /` and BIOS/device inventory identify the **actual** OS NVMe and second physical SSD.
- [ ] All test operations have a recovery console or alternate SSH session.
- [ ] `python3 install.py --plan` is read-only, and selected modules match operator intent.
- [ ] No component executes any formatting, repartitioning, resize or disk erase action.
- [ ] Declining storage changes preserves `/etc/fstab` and all mounted filesystems.
- [ ] The wrong full UUID aborts before changing `/etc/fstab`.
- [ ] A correct UUID for a **pre-existing** supported filesystem mounts at `/srv/llm-data` without altering existing files.
- [ ] Verify mount identity with `findmnt -no SOURCE,UUID,FSTYPE,TARGET /srv/llm-data`.
- [ ] Missing target mount refuses writes to its unmounted `/srv/llm-data` model destination.
- [ ] An unrelated filesystem already mounted at `/srv/llm-data` is **rejected** (**known limitation: STOR-01; do not mark pass until fixed**).
- [ ] LVM, RAID, LUKS and unexpected mount topologies are conservatively refused (**known limitation: STOR-02**).
- [ ] Model-root JSON input cannot bypass allowed storage paths (**known limitation: STOR-03**).
- [ ] Storage survives reboot and holds original files/data with correct free space.

## B. Runtime installation and services

- [ ] `sudo python3 install.py --apply --component base` completes; SSH still works.
- [ ] `vulkaninfo --summary` identifies Radeon 780M / RADV and not only software Vulkan.
- [ ] `llama.cpp` Vulkan build succeeds; `llama-server` and `llama-bench` binaries exist.
- [ ] `llm-llama.service` does **not** start without a valid GGUF; with GGUF it starts on localhost:8081.
- [ ] Ollama `127.0.0.1:11434/api/tags` responds and Qwen coder inference completes.
- [ ] Open WebUI loads, lists expected Ollama models, and first-install admin account works.
- [ ] Anonymous Open WebUI usage and registration are denied.
- [ ] FileBrowser Quantum stable starts and login works; negative test confirms it **cannot** modify models (**known BLOCKER SEC-01, fix required**).
- [ ] code-server starts on localhost:8443; password authentication works.
- [ ] Cockpit login works over HTTPS and authenticated SSH forwarding.
- [ ] GitHub Sync Cockpit page renders; unprivileged user `gh auth login` is independent of root and `ghsync check` succeeds.
- [ ] GitHub Sync installed hashes match its pinned commit and no cron or timer job is added implicitly.
- [ ] Bookmarks Cockpit page renders, existing bookmark configuration survives rerun, and no launcher is started implicitly.
- [ ] Any manually enabled Bookmarks terminal launcher undergoes bind/auth/write-mode and timeout inspection.
- [ ] Tailscale daemon is active; manual `tailscale up` succeeds; no public serve/funnel route created.
- [ ] Debian unattended security update timers exist; automated reboot remains disabled.

## C. Network and security

- [ ] `sudo ss -lntp` confirms expected ports only on `127.0.0.1` or as separately approved; include IPv6.
- [ ] From an independent LAN client, unauthenticated direct access to ports 11434, 8081, 3000, 8082, 8443 and 9090 is blocked unless an approved authenticated tunnel is used.
- [ ] From Tailscale-connected client, SSH forwarding works, without unreviewed listeners.
- [ ] Code detects listener bound to any specific external IP as unsafe (**known limitation: NET-01; fix required**).
- [ ] Service users cannot read unrelated secrets or OS data; selected group/write permissions match documented policy.
- [ ] Generated files under `/etc/llm-postinstall/` are protected; `last-run.json` and logs contain no passwords.
- [ ] Malicious path traversal, symlink/hardlink release archive fixtures cannot write outside staging (**known limitation: SUP-01**).
- [ ] Upstream binary versions/digests, Tailscale signing key fingerprint and Python wheel versions are recorded.
- [ ] Signed Debian updates and repo trust paths work as configured.

## Optional terminal, notebook and desktop additions

- [ ] Fish, btop and mc run as normal users, with the login shell unchanged.
- [ ] ttyd static asset checksum matches the pinned upstream manifest; service is disabled until explicitly enabled, and then listens **only** on `127.0.0.1:7681` under `llmterminal`.
- [ ] AoE executable is pinned/verified, runs as a normal user, creates no root agent process or public dashboard.
- [ ] JupyterLab is token-authenticated, executes under `llmjupyter`, and listens only on `127.0.0.1:8888`.
- [ ] TigerVNC service cannot start as root or without a VNC password; a normal user receives a working virtual XFCE session on loopback `5901`.
- [ ] noVNC stays disabled until explicitly enabled; WebSocket port `6080` is localhost-only and cannot bypass VNC authentication.
- [ ] Untrusted LAN client cannot connect directly to ttyd, notebook, VNC or noVNC; SSH forwarded access works.
- [ ] Re-run the modules without starting disabled services or overwriting external executables/configuration.

## D. CPU, GPU, memory, temperature and throughput

- [ ] Same quantized GGUF, prompt and batch settings used for CPU-only and Vulkan offload runs.
- [ ] Collect `llama-bench` tokens/sec with `-ngl 0` and `-ngl 99` (verify syntax against installed version).
- [ ] Record input prompt tokens, output tokens, model load time, peak resident/system memory and CPU/GPU utilization.
- [ ] Verify actual Vulkan backend/layer-offload statements in daemon logs.
- [ ] Check Ollama backend selection independently; do not assume the Ollama generic AMD64 archive guarantees GPU inference.
- [ ] Monitor power and thermals during sustained inference, repeat under representative 64 GB RAM load.
- [ ] Confirm memory/storage usage does not interfere with SSH, kernel, disk or other services.

## E. Failure recovery, reruns and durability

- [ ] Rerun each installed module: no unrelated file deletion or credential reset.
- [ ] Stop an installer halfway through a release download; rerun safely without unpacking corrupted content.
- [ ] Corrupt SHA256 asset rejected; no unsigned/unverified asset executed.
- [ ] Network loss/apt failure results in useful error and non-secret logs.
- [ ] `/var/lib/llm-postinstall/last-run.json` shows accurate per-module result.
- [ ] `--health` is interpreted as a shallow probe and does not mask high-severity failures as release-pass.
- [ ] Existing third-party services/configs do not get silently overwritten.
- [ ] Demonstrate rollback or documented manual recovery from bad service config, fstab edit and failed package changes.
- [ ] Two cold reboots: mount UUID stable, SSH survives, services restart as intended, credentials remain unchanged.
- [ ] Restored backup of databases/configs can be opened and integrity checked.

## F. Result and sign-off

| Finding | Status | Evidence link/path | Date | Reviewer |
| --- | --- | --- | --- | --- |
| SEC-01 / model-write isolation | OPEN | — | — | — |
| STOR-01/02/03 / storage identity | OPEN | — | — | — |
| SUP-01 / archive extraction | OPEN | — | — | — |
| NET-01 / external listeners | OPEN | — | — | — |
| REL-01 / bare-metal end-to-end | OPEN | — | — | — |

**GO only when** all BLOCKER and HIGH safety items are closed, all acceptance assertions above have reproducible positive or correctly rejected-negative evidence, and no unreviewed external listener or storage hazard remains. If any item remains untested, state **NOT VERIFIED**, not PASS.

Keep sanitized terminal output, hashes, logs, CI URLs, version inventory and storage layout in a protected evidence directory. Never attach unredacted passwords, Tailscale keys, tokens or device identifiers to public PRs.
