# Optional host maintenance modules

All seven modules introduced here are **unchecked by default** in the TUI. Each can be run independently using `sudo python3 install.py --apply --component NAME`. Existing default components and `auto_bookmarks` are unchanged. This guide describes actual present behavior and deliberately distinguishes an installer from a complete monitoring/backup policy.

| Module | Implementation | Activation |
| --- | --- | --- |
| `hardware_health` | Debian `smartmontools`, `nvme-cli`, `lm-sensors`; collects non-destructive SMART/NVMe/temperature baseline | Manual install / report; no background daemon |
| `cockpit_storage` | `cockpit-storaged` and `cockpit-packagekit`; requires the already locked-down Cockpit socket override | Immediate Cockpit pages; NO disk changes |
| `developer_tools` | Debian `ripgrep`, `fd-find`, `fzf`, `lazygit`, `zoxide`, `git` and `curl` | CLI only; no shell customization |
| `zram` | Debian `zram-tools`; retains vendor config | Enables `zramswap.service`; never calls `swapoff` or modifies disk swap |
| `service_watchdog` | Root-only systemd oneshot check with 5-minute timer | Records inactive **enabled** UM780 service units in journal; **does not** restart, email or webhook |
| `llm_benchmark` | Existing locally built `llama-bench` and existing GGUF; compares CPU `-ngl 0` with Vulkan `-ngl 99` | Manual run; saves benchmark report; requires GGUF |
| `backup_restore` | Restic CLI; optional encrypted daily config backups | Installs Restic only until a verified mounted `backup_repository` is supplied |

## Backup configuration

Specify a pre-existing **separately mounted** local or NAS-backed path under `/mnt/`, `/media/` or `/srv/backups/`:

```json
"backup_repository": "/mnt/nas/um780-restic"
```

The installer refuses a path that is not mounted elsewhere, is inside the source directories, or looks unsafe. It generates a root-only password at `/etc/llm-postinstall/restic-password`. **The initial repository is not automatically initialized**: use Restic's normal initialization workflow with `RESTIC_REPOSITORY` and `RESTIC_PASSWORD_FILE` set, then rerun the module to enable the daily timer. Existing repositories must use exactly that password. Never delete/rotate it before testing recovery. Backup sources are **configuration/state only**: `/etc/llm-postinstall`, `/etc/cockpit`, and `/var/lib/llm-postinstall`. LLM weights, SSD images, Jupyter workspaces and other application data are not covered.

A successful timer configuration does **not** prove a restorable backup. Perform a test backup, `restic check`, a restore into a temporary directory and inspect restored permissions. Do not confuse restic's encrypted snapshots with installer rollback.

## Watchdog

Use `sudo systemctl status llm-service-watchdog.timer` and `sudo journalctl -u llm-service-watchdog.service`. Inactive services that are deliberately disabled are ignored. The watchdog does not automatically repair service failures or send notifications. This conservative default prevents a recovery loop hiding a deeper hardware or authentication problem.

## Benchmark

A completed `llama` build and selected GGUF are required. The report is saved at `/var/log/llm-postinstall/llm-benchmark.txt`. CPU and Vulkan runs each use the same token/prompt dimensions and repetitions. The report may contain stdout error information; inspect exit status and offload log before reporting throughput. On the Radeon 780M, results depend on GGUF size and available shared memory.

## Other limitations

- No SSD SMART auto-selftest or predictive failure alert is scheduled by `hardware_health`; the first phase is non-destructive discovery.
- `cockpit_storage` is a powerful administrative UI: make sure Cockpit access and privilege escalation are protected.
- This is pre-release until tested on Debian 13 / UM780 physical hardware.
- No module offers a universal uninstall or transaction-wide rollback; see [Known Issues](KNOWN_ISSUES.md).
