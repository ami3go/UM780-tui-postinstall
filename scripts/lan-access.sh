#!/bin/sh
# Expose the UM780 LLM stack services on all interfaces (LAN) via systemd
# drop-ins. The installer rewrites the main unit files on reruns but never
# touches these drop-ins, so the setting survives reinstalls.
#
#   sudo sh lan-access.sh enable        # listen on 0.0.0.0 and restart services
#   sudo sh lan-access.sh disable       # remove drop-ins, back to localhost only (and logins on)
#   sudo sh lan-access.sh nologin on    # LAN access without logins where the app supports it
#   sudo sh lan-access.sh nologin off   # LAN access with logins again
#   sh lan-access.sh status             # show listening addresses and login mode
#
# nologin covers Open WebUI, code-server and FileBrowser. Ollama has no login
# anyway; noVNC can take its password in the bookmark URL (see
# cockpit-bookmarks-lan.py --novnc-password); Cockpit always needs a login.
#
# Re-run "enable" after an installer rerun that changes a service's ExecStart
# (e.g. a new FileBrowser version path), so the override picks up the new path.
set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
UNIT_DIR=${UNIT_DIR:-/etc/systemd/system}
CONF=${CONF:-/etc/llm-postinstall}
DRY_RUN=${DRY_RUN:-0}
DROPIN=zz-lan-access.conf
OLLAMA_ENV=$CONF/lan-ollama.env
WEBUI_ENV=$CONF/lan-webui.env
NOLOGIN_FLAG=$CONF/lan-nologin
FB_HELPER=${FB_HELPER:-/usr/local/libexec/um780-lan-filebrowser-config}
SERVICES="llm-ollama llm-webui llm-codeserver llm-filebrowser llm-novnc"
PORTS='11434|3000|8443|8082|6080|9090'

sysctl_() { [ "$DRY_RUN" = 1 ] && echo "would run: systemctl $*" || systemctl "$@"; }
webui_user() { [ "$DRY_RUN" = 1 ] && echo "would run: webui-lan-user.py $1" || python3 "$SCRIPT_DIR/webui-lan-user.py" "$1"; }

# Replace $2 with $3 in stdin; fail if $2 is absent.
must_sub() {
    line=$(cat)
    case $line in *"$1"*) ;; *) echo "'$1' not found in: $line" >&2; exit 1 ;; esac
    printf '%s\n' "$line" | sed "s|$1|$2|"
}

exec_start() {  # $1 unit name; prints its ExecStart line
    grep '^ExecStart=' "$UNIT_DIR/$1.service" || { echo "No ExecStart in $1" >&2; exit 1; }
}

write_dropin() {  # $1 unit name (with suffix), stdin = content
    mkdir -p "$UNIT_DIR/$1.d"
    cat > "$UNIT_DIR/$1.d/$DROPIN"
    chmod 644 "$UNIT_DIR/$1.d/$DROPIN"
    echo "wrote $UNIT_DIR/$1.d/$DROPIN"
}

# Runs as the filebrowser user before each start: copies the installer's
# config.yaml to /run with listen 0.0.0.0, plus no-login when given "nologin".
install_fb_helper() {
    mkdir -p "$(dirname "$FB_HELPER")"
    cat > "$FB_HELPER" <<'EOF'
#!/bin/sh
set -eu
src=/var/lib/filebrowser/config.yaml
dst=/run/llm-filebrowser-lan/config.yaml
umask 077
awk -v nologin="${1:-}" '
    /^  listen:/ { print "  listen: 0.0.0.0"; next }
    /^    [a-z]/ { inpw = ($0 == "    password:") }
    nologin == "nologin" && inpw && $0 == "      enabled: true" { print "      enabled: false"; next }
    { print }
    nologin == "nologin" && $0 == "  methods:" { print "    noauth: true" }
' "$src" > "$dst"
grep -q '^  listen: 0.0.0.0$' "$dst"
if [ "${1:-}" = nologin ]; then grep -q '^    noauth: true$' "$dst"; fi
EOF
    chmod 755 "$FB_HELPER"
}

enable() {
    nologin=; [ -f "$NOLOGIN_FLAG" ] && nologin=nologin
    # Compute every override first, so a layout mismatch aborts before any change.
    webui=$(exec_start llm-webui | must_sub '--host 127.0.0.1' '--host 0.0.0.0')
    code=$(exec_start llm-codeserver | must_sub '--bind-addr 127.0.0.1:8443' '--bind-addr 0.0.0.0:8443')
    [ -n "$nologin" ] && code=$(printf '%s\n' "$code" | must_sub '--auth password' '--auth none')
    novnc=$(exec_start llm-novnc | must_sub ' 127.0.0.1:6080 ' ' 0.0.0.0:6080 ')
    fb=$(exec_start llm-filebrowser | must_sub ' -c /var/lib/filebrowser/config.yaml' ' -c /run/llm-filebrowser-lan/config.yaml')

    # Ollama: EnvironmentFile entries override Environment=, and later files win.
    mkdir -p "$CONF"
    printf 'OLLAMA_HOST=0.0.0.0:11434\n' > "$OLLAMA_ENV"
    chmod 640 "$OLLAMA_ENV"
    printf '[Service]\nEnvironmentFile=%s\n' "$OLLAMA_ENV" | write_dropin llm-ollama.service

    if [ -n "$nologin" ]; then
        printf 'WEBUI_AUTH=False\n' > "$WEBUI_ENV"
        chmod 640 "$WEBUI_ENV"
        printf '[Service]\nEnvironmentFile=%s\nExecStart=\n%s\n' "$WEBUI_ENV" "$webui" | write_dropin llm-webui.service
    else
        rm -f "$WEBUI_ENV"
        printf '[Service]\nExecStart=\n%s\n' "$webui" | write_dropin llm-webui.service
    fi
    printf '[Service]\nExecStart=\n%s\n' "$code" | write_dropin llm-codeserver.service
    printf '[Service]\nExecStart=\n%s\n' "$novnc" | write_dropin llm-novnc.service

    # FileBrowser binds from its YAML, which the installer owns and inventory
    # checks; serve a runtime copy instead.
    install_fb_helper
    printf '[Service]\nRuntimeDirectory=llm-filebrowser-lan\nRuntimeDirectoryMode=0700\nExecStartPre=%s%s\nExecStart=\n%s\n' \
        "$FB_HELPER" "${nologin:+ $nologin}" "$fb" | write_dropin llm-filebrowser.service

    # Cockpit: reset the installer's loopback-only listener (sorted after it).
    printf '[Socket]\nListenStream=\nListenStream=9090\n' | write_dropin cockpit.socket

    sysctl_ daemon-reload
    sysctl_ restart $SERVICES
    sysctl_ restart cockpit.socket
    echo "LAN access enabled${nologin:+ (no login for Open WebUI, code-server, FileBrowser)}."
}

disable() {
    was_nologin=; [ -f "$NOLOGIN_FLAG" ] && was_nologin=1
    for u in $SERVICES; do rm -f "$UNIT_DIR/$u.service.d/$DROPIN"; done
    rm -f "$UNIT_DIR/cockpit.socket.d/$DROPIN" "$OLLAMA_ENV" "$WEBUI_ENV" "$NOLOGIN_FLAG" "$FB_HELPER"
    sysctl_ daemon-reload
    sysctl_ restart $SERVICES
    sysctl_ restart cockpit.socket
    [ -z "$was_nologin" ] || webui_user lock
    echo "LAN access disabled; services are localhost-only with logins."
}

nologin() {
    case ${1:-} in
        on)
            webui_user ensure  # needs Open WebUI running with login on
            mkdir -p "$CONF"; touch "$NOLOGIN_FLAG"; chmod 600 "$NOLOGIN_FLAG"
            enable ;;
        off)
            rm -f "$NOLOGIN_FLAG"
            enable
            webui_user lock ;;
        *) echo "usage: $0 nologin on|off" >&2; exit 2 ;;
    esac
}

status() {
    ss -ltn | awk -v p=":($PORTS)\$" 'NR==1 || $4 ~ p {print $4}'
    if [ -f "$UNIT_DIR/llm-codeserver.service.d/$DROPIN" ] && grep -q -- '--auth none' "$UNIT_DIR/llm-codeserver.service.d/$DROPIN"; then
        echo "Login mode: no login (Open WebUI, code-server, FileBrowser)"
    else
        echo "Login mode: logins required"
    fi
}

case ${1:-} in
    enable) enable; [ "$DRY_RUN" = 1 ] || { sleep 3; status; } ;;
    disable) disable ;;
    nologin) nologin "${2:-}"; [ "$DRY_RUN" = 1 ] || { sleep 3; status; } ;;
    status) status ;;
    *) echo "usage: $0 enable|disable|nologin on|off|status" >&2; exit 2 ;;
esac
