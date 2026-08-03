#!/bin/sh
set -eu

CONFIG_DIR="${FDM_CONFIG_DIR:-/app/config}"
CONF_FILE="$CONFIG_DIR/fdm.conf"
TRIGGER_FILE="$CONFIG_DIR/.run_now"
LOCK_FILE="$CONFIG_DIR/.fdm.lock"
CRON_SCHEDULE="${CRON_SCHEDULE:-*/5 * * * *}"
POLL_INTERVAL="${TRIGGER_POLL_INTERVAL:-5}"

log() {
    echo "$(date -Iseconds) [fdm-runner] $*"
}

VERSION="$(cat /VERSION 2>/dev/null || echo unknown)"
log "fdm-runner Version: $VERSION"

# Fuehrt fdm einmal aus, Konto fuer Konto nacheinander (statt alle parallel,
# was fdm standardmaessig tut). Einige IMAP-Server antworten bei vielen
# gleichzeitigen Verbindungen von fdm mit "BAD Could not parse command";
# sequentielles Abarbeiten per "-a <konto>" umgeht das.
run_fdm() {
    if [ ! -f "$CONF_FILE" ]; then
        log "Keine fdm.conf unter $CONF_FILE gefunden, ueberspringe Lauf."
        return 0
    fi

    log "Starte fdm-Lauf ..."
    accounts=$(awk -F'"' '/^account /{print $2}' "$CONF_FILE")
    if [ -z "$accounts" ]; then
        log "Keine Accounts in $CONF_FILE gefunden."
        return 0
    fi

    echo "$accounts" | while IFS= read -r acct; do
        [ -n "$acct" ] || continue
        fdm -f "$CONF_FILE" -a "$acct" fetch || log "  Fehler bei Konto \"$acct\" (siehe Ausgabe oben)."
    done
    log "Lauf abgeschlossen."
}

if [ "${1:-}" = "--run-once" ]; then
    mkdir -p "$CONFIG_DIR"
    exec 9>"$LOCK_FILE"
    if flock -n 9; then
        run_fdm
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
# Standard-PATH ohne /usr/local/bin, wo "make install" fdm hinlegt - ohne
# das schlaegt jeder Cron-Lauf mit "fdm: not found" fehl (der manuelle
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
        log "Trigger-Datei gefunden, fuehre fdm sofort aus."
        /entrypoint.sh --run-once
    fi
    sleep "$POLL_INTERVAL"
done
