# Known issues, gaps and release readiness

Reviewed against `main` source on **2026-10-08**. This is a transparent engineering backlog, not proof each issue reproduces on an UM780 Pro. Severity describes impact if the behavior is exercised; final resolution requires code, unit/integration coverage and bare-metal verification.

**Readiness verdict:** **NO-GO for unattended or production deployment.** The scripted install is suitable for supervised experimentation on a backed-up, recoverable machine only.

## Prioritized findings

| ID | Severity | Area | Code-observed behavior / risk | Closure requirement |
| --- | --- | --- | --- | --- |
| SEC-01 | **BLOCKER** | FileBrowser write access | `filebrowser` is added to `llmshare`; model directories use group-write mode `2775`. The generated Quantum config does not impose a reliable read-only model source. A FileBrowser user may be able to change/delete model files. | Enforce OS-level read-only source permissions and deny-modification tests, or explicitly redesign feature as write-enabled with authorization |
| STOR-01 | **HIGH** | Existing mounted volume | `configure_storage()` reuses any existing `/srv/llm-data` mount without checking its backing UUID, origin or intent. | Compare against recorded UUID and reject unexpected filesystems; test wrong-device mounts |
| STOR-02 | **HIGH** | Disk topology | `partition_options()` uses `lsblk` parent/root inference; unusual LVM, RAID, dm-crypt, bind/multipath and mixed configurations need better exclusion and fuzzed fixture tests. | Conservative allowlist + explicit physical device/source checks; refuse ambiguous topology |
| STOR-03 | **HIGH** | Storage path input | First-run `model_storage` from JSON is not restricted to managed roots or validated like persisted `storage.json`. | Validate schema/path, reject symlinks/traversal/mountpoint fallthrough and add tests |
| SUP-01 | **HIGH** | Archive unpacking | `_safe_tar_list()` validates entry paths, not archive symlink/hardlink destinations or all extraction hazards. | Harden tar handling or use a safe verified extraction routine with negative fixtures |
| NET-01 | **HIGH** | Listener diagnostics | `public_bindings()` detects wildcard binds but does not flag services bound to a specific non-loopback LAN/Tailscale IP; an unexpected service/port may also go undetected. | Enumerate expected listeners/interfaces, reject every unintended public/non-loopback bind and test IPv4/IPv6 |
| REL-01 | **HIGH** | Runtime validation | There are no Debian 13/UM780 Pro integration results, login/inference acceptance artifacts, soak tests or reboot persistence results. | Execute and record [Acceptance](ACCEPTANCE.md) on physical system |
| REL-02 | **HIGH** | Version reproducibility | llama.cpp/upstream releases and uv Python package installs are mutable latests; no manifest/lockfile records exact resolved versions and SHA for all sources. | Version locking, dependency manifest and tested upgrade/rollback policy |
| SUP-02 | **HIGH** | Tailscale key integrity | Tailscale repository key is fetched over HTTPS but its fingerprint is not pinned/verified by the installer. | Pin and validate authenticated signing-key identity before use |
| OPS-01 | **MEDIUM** | Health semantics | `health.render()` exits nonzero only on `FAIL`; inactive services often yield `WARN`, and llama errors report `PENDING`. It checks open ports, not application health/auth/inference. | Meaningful required checks, explicit exit codes and end-to-end smoke tests |
| OPS-02 | **MEDIUM** | Transaction/rollback | A failed module can leave partial installations, mutable `fstab` or restarted services. No holistic rollback/uninstall workflow. | Journal changes, restore validated prior state or document supported manual rollback |
| OPS-03 | **MEDIUM** | Idempotence | Existing module binaries may skip updates even when outdated; some paths/install actions are outside managed ownership and backup semantics; modules are not guaranteed rerunnable after interrupted unpack. | Idempotence fixtures with interrupted and repeated runs |
| OPS-04 | **MEDIUM** | Secrets/rotation | Random initial secrets are generated, but automatic rotation of persisted app accounts or audit history is absent. | Verified rotation/recovery workflow with protection of secrets |
| OPS-05 | **MEDIUM** | Modules/dependencies | No dependency resolver; `--component` can be invoked alone in the wrong order; default config selects every component. | Dependency graph, preflight and staged defaults |
| GPU-01 | **MEDIUM** | AMD APU acceleration | llama.cpp Vulkan is configured, but Vulkan detection does not prove offload. Ollama uses generic AMD64 package and may fall back to CPU. | Benchmark on Radeon 780M, record VRAM/shared RAM and backend logs |
| WEB-01 | **MEDIUM** | WebUI bootstrap | Automatic admin creation depends on an empty Open WebUI database and upstream env conventions; installation code does not verify login or record user creation. | Automated first-run login test and recovery path |
| QUANT-01 | **MEDIUM** | Quantum release | Quantum is pinned to `v1.5.6-stable`; actual release asset/digest availability and standalone startup remain unverified on target. | Fetch release in integration test and exercise login and file access |
| CI-01 | **MEDIUM** | Test coverage | CI compiles Python, runs mocked unittests and a plan command on Ubuntu, not Debian systemd on UM780 Pro. | Debian test VM/container where practical; supervised real-machine CI gate for hardware functions |
| PERF-01 | **LOW** | Benchmark terminology | `benchmarks` writes CPU/sysbench and Vulkan summaries, not tokens/sec benchmarks. | Separate model benchmark command/evidence and performance thresholds |

## Where to start fixing

**Phase 1: safety invariants** — SEC-01, STOR-01/02/03, SUP-01, NET-01. Require code tests and manual negative testing. No data-destructive or network-exposure regressions allowed.

**Phase 2: deterministic install** — REL-02, SUP-02, OPS-02/03/05, WEB-01, QUANT-01. Ensure service identity, version selection, preflight and rollback documentation are consistent.

**Phase 3: hardware acceptance** — REL-01, GPU-01, CI-01 and PERF-01. Record real inference throughput, CPU vs Vulkan, boot recovery, SSD and memory behavior.

## Additional optional-tool verification gaps

- **HIGH (REMOTE-01):** ttyd/Jupyter/VNC/noVNC have no physical Debian 13 browser/session integration evidence. Their host listener policies, VNC password handling, Jupyter token login, XFCE startup, and root-denial gate require a real security acceptance test.
- **MEDIUM (REMOTE-02):** ttyd v1.7.7 and AoE v1.17.2 are fixed upstream releases, and their asset/checksum availability must be confirmed against the official release API on a live host. Missing hashes fail closed. Upgrade is manual.
- **MEDIUM (REMOTE-03):** The optional tools rely on a manually managed SSH tunnel and do not provide a managed auth/TLS reverse proxy. Bookmarks launchers remain separate and may bind differently if enabled.

## What the existing tests *do* verify

The GitHub Actions workflow uses Python 3.11 and 3.13 on `ubuntu-latest` to byte-compile code, run the unittest suite and execute `--plan`. Relevant unit tests include candidate partition filtering, wrong-UUID refusal, secret-file handling, managed-file conflicts, digest requirements, and listener wildcard detection.

**Not currently covered:** full apt/UV/GitHub install paths, real storage mounts, actual network reachability, service startup, authentication, GPU offload, and rollback under failure.

## Documentation status

These issues are intentionally described rather than papered over. The docs explain **current executable behavior** and how to operate it cautiously. They do not claim the release blockers have been fixed merely by documentation updates. Future PRs should update this file when a finding closes, naming the specific tests/evidence that support the closure.
