# Turnkey noVNC desktop for UM780 (Debian 13)

The **novnc** post-install module now installs, configures and enables a dedicated **virtual XFCE desktop** and browser noVNC proxy. No physical monitor, Xorg login screen, VNC user account login, or manual `tigervncpasswd` step is necessary for the managed noVNC desktop.

## Installation

Make sure your Cockpit Bookmarks plugin is installed if you want the card to appear. The single `novnc` module installs TigerVNC, XFCE, websockify and noVNC, configures a dedicated service account, generates the VNC credential, and starts the services.

```sh
cd UM780-tui-postinstall
git pull --ff-only

python3 install.py --plan --component novnc
sudo python3 install.py --apply --component novnc

# Optional; auto-bookmark synchronization is on by default.
sudo python3 install.py --apply --component bookmark_sync
sudo python3 install.py --health --component novnc
```

If the Cockpit Bookmarks plugin is not installed yet:

```sh
sudo python3 install.py --apply --component cockpit --component cockpit_bookmarks
sudo python3 install.py --apply --component bookmark_sync
```

The generated card is named **noVNC Desktop** in the **UM780 Web Apps** group. It links to `http://127.0.0.1:6080/vnc.html`, and its description tells administrators where to retrieve the credential. The installer **does not** embed that credential in the bookmark, its URL, a JavaScript page or service command arguments.

## Desktop credentials

The installer creates a random **eight-character VNC password** on first run and reuses it on later runs. This is not your Linux user login password. With **VncAuth**, no username is required: enter the password when noVNC asks for it.

```sh
sudo cat /etc/llm-postinstall/novnc-vnc-password
```

**Do not paste this value into the Cockpit Bookmarks configuration or GitHub issues.** The recoverable clear-text password is root-readable only (`0600`, in a root-owned `0700` directory). The VNC password file is stored at `/var/lib/llmvnc/.config/tigervnc/passwd` and is readable only by the `llmvnc` system user.

**VNC authentication limitation:** legacy VncAuth effectively uses **only eight password characters**, so a long password does not increase entropy. A random eight-character alphanumeric password is used, and both VNC and noVNC remain reachable **only through loopback and a trusted SSH port forward**. The VNC obfuscation file is not a strong password hash. <https://manpages.debian.org/trixie/tigervnc-standalone-server/tigervncserver.1.en.html>

On rerun, the installer validates existing credentials. It refuses to overwrite a manually changed VNC password or silently rotate/reset it. There is no automated reset/rotation command yet: preserve your root credentials file in protected backups.

## Access from another computer

Both services listen on the Debian host's **127.0.0.1** address. From the computer where you run Cockpit and want to use the Bookmarks card:

```sh
ssh -N -L 6080:127.0.0.1:6080 user@UM780_SERVER_IP
```

Then open **Cockpit → Bookmarks → noVNC Desktop**, or `http://127.0.0.1:6080/vnc.html` directly from the same computer/browser. Enter the VNC password retrieved above.

The browser's `127.0.0.1` is **the browser's computer**, not the server. If you access Cockpit from a phone or another laptop, you must independently provide secure forwarding/proxy access for that client. No external LAN/WAN or Tailscale Serve listener is configured by this module.

## Dedicated services and isolation

| Item | Configuration |
|---|---|
| Virtual desktop user | Dedicated restricted `llmvnc` service account; **not root** |
| Desktop environment | XFCE virtual screen, 1600 × 900 |
| VNC display | `:2` (separate from optional user-managed VNC `:1`) |
| VNC TCP | `127.0.0.1:5902` |
| Browser noVNC / websockify | `127.0.0.1:6080` |
| VNC daemon | `llm-novnc-vnc.service` (enabled, systemd) |
| Browser proxy | `llm-novnc.service` (enabled, depends on VNC daemon) |
| Web entry point | `/vnc.html` |
| Authentication | VncAuth password, no separate username |
| Plain credential | `/etc/llm-postinstall/novnc-vnc-password`, root-only |

Both services enable automatic restart on failure. They have basic systemd sandboxing. This desktop does not access your personal home directory by default; it uses the dedicated `llmvnc` home. The separate `vnc` component can still be used for a manually authenticated **user-specific** TigerVNC desktop on `:1`; it is independent of the turnkey noVNC desktop.

## Service validation and stopping

```sh
sudo systemctl status llm-novnc-vnc.service llm-novnc.service --no-pager
sudo journalctl -u llm-novnc-vnc.service -u llm-novnc.service -n 100 --no-pager
sudo ss -lntp | grep -E ':(5902|6080)\b'
sudo python3 install.py --health --component novnc
```

The displayed listeners must show `127.0.0.1`, **not** `0.0.0.0`, `::` or your LAN/Tailscale IP. If either TCP port is already occupied by an unrelated process, the installer refuses to repurpose it. This prevents noVNC from accidentally proxying to someone else's desktop.

To stop without uninstalling:

```sh
sudo systemctl disable --now llm-novnc.service
sudo systemctl disable --now llm-novnc-vnc.service
```

To restart manually:

```sh
sudo systemctl enable --now llm-novnc-vnc.service
sudo systemctl enable --now llm-novnc.service
```

Running `sudo python3 install.py --apply --component novnc` again revalidates credentials, reapplies managed units, enables services and synchronizes Bookmarks if configured. It does not erase your VNC user directory.

## Limitations and acceptance

- The module has automated unit/mocked tests; it has **not** been exercised on the physical UM780 Pro. Test XFCE session startup, clipboard and keyboard behavior, password authentication, two reboots, SSH forwarding, remote client behavior and negative external-port connectivity before declaring production ready.
- This is a dedicated low-privilege virtual desktop, **not** the currently logged-in XFCE desktop and not evidence of AMD GPU acceleration.
- Classic VncAuth alone is not adequate protection for a publicly reachable network service. Do not open or port-forward the VNC/noVNC ports on your router.
- Do not edit the Bookmarks card during an installer rescan; the external JSON merger is additive but not transactionally coordinated with Cockpit's browser config writes.
- The installer does not reset a missing/replaced password by guesswork and does not remove existing manually configured VNC sessions.
- An existing manually customized `llm-novnc.service` unit is not silently overwritten if it lacks the installer's ownership marker.

See [Auto Bookmarks](BOOKMARKS_AUTO.md), [Optional Tools](OPTIONAL_TOOLS.md) and [Security](SECURITY.md) for related behavior.
