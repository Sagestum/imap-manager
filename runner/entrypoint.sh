#!/bin/sh
set -eu

CONFIG_DIR="${FDM_CONFIG_DIR:-/app/config}"
CONF_FILE="$CONFIG_DIR/sync_plan.json"
TRIGGER_FILE="$CONFIG_DIR/.run_now"
LOCK_FILE="$CONFIG_DIR/.sync.lock"
CRON_SCHEDULE="${CRON_SCHEDULE:-*/5 * * * *}"
POLL_INTERVAL="${TRIGGER_POLL_INTERVAL:-5}"

log() {
    echo "$(date -Iseconds) [fdm-runner] $*"
}

VERSION="$(cat /VERSION 2>/dev/null || echo unknown)"
log "fdm-runner Version: $VERSION"

# Fuehrt imapsync einmal aus, Ordner-Zuordnung fuer Ordner-Zuordnung nacheinander (statt
# parallel). Einige IMAP-Server reagieren empfindlich auf viele gleichzeitige Verbindungen;
# sequentielles Abarbeiten in run_sync.py umgeht das, genau wie zuvor beim Konto-fuer-Konto-fdm.
run_sync() {
    log "Starte imapsync-Lauf ..."
    python3 /app/run_sync.py "$CONF_FILE"
    log "Lauf abgeschlossen."
}

if [ "${1:-}" = "--run-once" ]; then
    mkdir -p "$CONFIG_DIR"
    exec 9>"$LOCK_FILE"
    if flock -n 9; then
        run_sync
    else
        log "Lauf uebersprungen (bereits aktiv)."
    fi
    exit 0
fi

mkdir -p "$CONFIG_DIR"
touch "$LOCK_FILE"

# Cron ruft denselben Skript-Modus auf wie die Trigger-Schleife unten, damit
# beide Wege ueber denselben Lock und dieselbe sequentielle Verarbeitung
# laufen. Ausgabe geht an die stdout/stderr des Containers (PID 1), damit sie
# in "docker logs" auftaucht - cron erbt sonst keine offenen Deskriptoren.
# PATH explizit setzen: cron startet Jobs sonst mit einem minimalen
# Standard-PATH ohne /usr/local/bin, wo imapsync installiert ist - ohne das
# schlaegt jeder Cron-Lauf mit "imapsync: not found" fehl (der manuelle
# Trigger-Pfad unten ist davon nicht betroffen, da er als Kindprozess dieses
# schon laufenden Skripts dessen volles PATH erbt).
{
    echo "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    echo "$CRON_SCHEDULE root /entrypoint.sh --run-once >>/proc/1/fd/1 2>>/proc/1/fd/2"
} > /etc/cron.d/fdm-runner
chmod 0644 /etc/cron.d/fdm-runner

cron -f &
CRON_PID=$!

log "Gestartet. Zeitplan: $CRON_SCHEDULE | Trigger-Datei: $TRIGGER_FILE | Poll-Intervall: ${POLL_INTERVAL}s"

trap 'log "Beende ..."; kill "$CRON_PID" 2>/dev/null; exit 0' TERM INT

while true; do
    if [ -f "$TRIGGER_FILE" ]; then
        rm -f "$TRIGGER_FILE"
        log "Trigger-Datei gefunden, fuehre imapsync sofort aus."
        /entrypoint.sh --run-once
    fi
    sleep "$POLL_INTERVAL"
done
