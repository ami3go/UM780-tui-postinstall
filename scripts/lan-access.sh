#!/bin/sh
# Expose the UM780 LLM stack services on all interfaces (LAN) via systemd
# drop-ins. The installer rewrites the main unit files on reruns but never
# touches these drop-ins, so the setting survives reinstalls.
#
#   sudo sh lan-access.sh enable    # listen on 0.0.0.0 and restart services
#   sudo sh lan-access.sh disable   # remove drop-ins, back to localhost only
#   sh lan-access.sh status         # show listening addresses
#
# Re-run "enable" after an installer rerun that changes a service's ExecStart
# (e.g. a new FileBrowser version path), so the override picks up the new path.
set -eu

UNIT_DIR=${UNIT_DIR:-/etc/systemd/system}
DRY_RUN=${DRY_RUN:-0}
DROPIN=zz-lan-access.conf
OLLAMA_ENV=${OLLAMA_ENV:-/etc/llm-postinstall/lan-ollama.env}
SERVICES="llm-ollama llm-webui llm-codeserver llm-filebrowser llm-novnc"
PORTS='11434|3000|8443|8082|6080|9090'

sysctl_() { [ "$DRY_RUN" = 1 ] && echo "would run: systemctl $*" || systemctl "$@"; }

# Print the unit's ExecStart with $1 replaced by $2; fail if $1 is absent.
exec_start() {
    unit=$UNIT_DIR/$1.service
    line=$(grep '^ExecStart=' "$unit") || { echo "No ExecStart in $unit" >&2; exit 1; }
    case $line in *"$2"*) ;; *) echo "'$2' not found in $unit ExecStart; installer layout changed?" >&2; exit 1 ;; esac
    printf '%s\n' "$line" | sed "s|$2|$3|"
}

write_dropin() {  # $1 unit name (with suffix), stdin = content
    mkdir -p "$UNIT_DIR/$1.d"
    cat > "$UNIT_DIR/$1.d/$DROPIN"
    chmod 644 "$UNIT_DIR/$1.d/$DROPIN"
    echo "wrote $UNIT_DIR/$1.d/$DROPIN"
}

enable() {
    # Compute every override first, so a layout mismatch aborts before any change.
    webui=$(exec_start llm-webui '--host 127.0.0.1' '--host 0.0.0.0')
    code=$(exec_start llm-codeserver '--bind-addr 127.0.0.1:8443' '--bind-addr 0.0.0.0:8443')
    novnc=$(exec_start llm-novnc ' 127.0.0.1:6080 ' ' 0.0.0.0:6080 ')
    fb=$(exec_start llm-filebrowser ' -c /var/lib/filebrowser/config.yaml' ' -c /run/llm-filebrowser-lan/config.yaml')

    # Ollama: EnvironmentFile entries override Environment=, and later files win.
    mkdir -p "$(dirname "$OLLAMA_ENV")"
    printf 'OLLAMA_HOST=0.0.0.0:11434\n' > "$OLLAMA_ENV"
    chmod 640 "$OLLAMA_ENV"
    printf '[Service]\nEnvironmentFile=%s\n' "$OLLAMA_ENV" | write_dropin llm-ollama.service

    printf '[Service]\nExecStart=\n%s\n' "$webui" | write_dropin llm-webui.service
    printf '[Service]\nExecStart=\n%s\n' "$code" | write_dropin llm-codeserver.service
    printf '[Service]\nExecStart=\n%s\n' "$novnc" | write_dropin llm-novnc.service

    # FileBrowser binds from its YAML, which the installer owns and inventory
    # checks; serve a runtime copy with only the listen address changed.
    write_dropin llm-filebrowser.service <<EOF
[Service]
RuntimeDirectory=llm-filebrowser-lan
RuntimeDirectoryMode=0700
ExecStartPre=/bin/sh -c "umask 077; sed -e 's/^  listen: .127.0.0.1.\$\$/  listen: 0.0.0.0/' /var/lib/filebrowser/config.yaml > /run/llm-filebrowser-lan/config.yaml && grep -q '^  listen: 0.0.0.0\$\$' /run/llm-filebrowser-lan/config.yaml"
ExecStart=
$fb
EOF

    # Cockpit: reset the installer's loopback-only listener (sorted after it).
    printf '[Socket]\nListenStream=\nListenStream=9090\n' | write_dropin cockpit.socket

    sysctl_ daemon-reload
    sysctl_ restart $SERVICES
    sysctl_ restart cockpit.socket
    echo "LAN access enabled."
}

disable() {
    for u in $SERVICES; do rm -f "$UNIT_DIR/$u.service.d/$DROPIN"; done
    rm -f "$UNIT_DIR/cockpit.socket.d/$DROPIN" "$OLLAMA_ENV"
    sysctl_ daemon-reload
    sysctl_ restart $SERVICES
    sysctl_ restart cockpit.socket
    echo "LAN access disabled; services are localhost-only again."
}

status() {
    ss -ltn | awk -v p=":($PORTS)\$" 'NR==1 || $4 ~ p {print $4}'
}

case ${1:-} in
    enable) enable; [ "$DRY_RUN" = 1 ] || { sleep 3; status; } ;;
    disable) disable ;;
    status) status ;;
    *) echo "usage: $0 enable|disable|status" >&2; exit 2 ;;
esac
