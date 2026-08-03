#!/bin/sh
set -eu

CONFIG_DIR="${FDM_CONFIG_DIR:-/app/config}"
CONF_FILE="$CONFIG_DIR/fdm.conf"
TRIGGER_FILE="$CONFIG_DIR/.run_now"
LOCK_FILE="$CONFIG_DIR/.fdm.lock"
CRON_SCHEDULE="${CRON_SCHEDULE:-*/5 * * * *}"
POLL_INTERVAL="${TRIGGER_POLL_INTERVAL:-5}"

mkdir -p "$CONFIG_DIR"
touch "$LOCK_FILE"

log() {
    echo "$(date -Iseconds) [fdm-runner] $*"
}

run_fdm() {
    if [ ! -f "$CONF_FILE" ]; then
        log "Keine fdm.conf unter $CONF_FILE gefunden, ueberspringe Lauf."
        return 0
    fi
    log "Starte fdm-Lauf ..."
    if flock -n "$LOCK_FILE" fdm -f "$CONF_FILE" fetch; then
        log "Lauf abgeschlossen."
    else
        log "Lauf uebersprungen (bereits aktiv) oder fehlgeschlagen."
    fi
}

# Cron-Zeile mit bereits aufgeloesten Pfaden (cron erbt keine Umgebungsvariablen
# aus diesem Skript). Ausgabe geht an die stdout/stderr des Containers (PID 1),
# damit sie in "docker logs" auftaucht.
echo "$CRON_SCHEDULE root flock -n $LOCK_FILE fdm -f $CONF_FILE fetch >>/proc/1/fd/1 2>>/proc/1/fd/2" > /etc/cron.d/fdm-runner
chmod 0644 /etc/cron.d/fdm-runner

cron -f &
CRON_PID=$!

log "Gestartet. Zeitplan: $CRON_SCHEDULE | Trigger-Datei: $TRIGGER_FILE | Poll-Intervall: ${POLL_INTERVAL}s"

trap 'log "Beende ..."; kill "$CRON_PID" 2>/dev/null; exit 0' TERM INT

while true; do
    if [ -f "$TRIGGER_FILE" ]; then
        rm -f "$TRIGGER_FILE"
        log "Trigger-Datei gefunden, fuehre fdm sofort aus."
        run_fdm
    fi
    sleep "$POLL_INTERVAL"
done
