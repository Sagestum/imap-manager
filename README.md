# imap-manager

Webinterface zur visuellen Verwaltung einer [`fdm`](https://github.com/nicm/fdm)-Konfiguration
(*Fetch & Deliver Mail*): Quell-Postfächer und Ziel-Server per Formular anlegen, Ordner live per
IMAP durchsuchen statt Pfade zu raten, Filter-/Verschieberegeln zusammenklicken — und daraus wird
automatisch eine gültige `fdm.conf` erzeugt, gespeichert und optional direkt ausgeführt.

## Was das Tool tut

- **Quell-Konten**: POP3/POP3S/IMAP/IMAPS-Postfächer anlegen. Bei IMAP/IMAPS können beliebig viele
  Quell-Ordner per Live-Verbindung ausgewählt werden (z. B. `INBOX` und der providerspezifische
  Spam-Ordner), statt den Ordnernamen zu erraten.
- **Ziel-Server**: IMAP/IMAPS-Zielserver anlegen, ebenfalls mit live durchsuchbaren Ordnern. Ein
  Zugangsdaten-Satz deckt beliebig viele Zielordner ab (z. B. `INBOX` und `Archiv/Rechnungen` im
  selben Gmail-Konto), ohne die Zugangsdaten mehrfach einzutragen.
- **Ausnahmeregeln**: greifen zuerst, unabhängig vom Quell-Ordner — z. B. "wenn `From` einen
  bestimmten String/Regex enthält, verschiebe nach X", per Drag & Drop priorisierbar.
- **Ordner-Zuordnungen**: Standard-Verarbeitung danach — "alles aus Quelle A / Ordner B nach
  Ziel C / Ordner D", ausgewählt per Dropdown statt getippt.
- **Catch-All**: optionaler Fallback für alles, was sonst nicht zutrifft.
- **Verlauf**: fragt auf Wunsch live per IMAP die zuletzt in den Zielordnern angekommenen Mails ab
  (Datum/Von/Betreff), um zu sehen, was tatsächlich zugestellt wurde.

Die Anwendung generiert daraus eine `fdm.conf`, die man herunterladen, ins Export-Verzeichnis, nach
`~/.fdm.conf` oder `/etc/fdm.conf` speichern kann — oder per "Speichern & Jetzt ausführen" direkt
in einem zweiten Container ausführen lässt (siehe unten).

## Architektur: zwei Container

| Service | Zweck |
|---|---|
| `imap-manager` | Flask-Webinterface, generiert `fdm.conf` aus der gespeicherten Konfiguration |
| `fdm-runner` | Führt `fdm` regelmäßig (Cron) und/oder auf Trigger aus |

Beide teilen sich ein Volume (`imap_manager_config`, gemountet unter `/app/config`). Der
Web-Container schreibt dort `fdm.conf` und bei Bedarf eine `.run_now`-Trigger-Datei hinein; der
Runner-Container pollt darauf und führt zusätzlich per Cron (Standard: alle 5 Minuten,
`FDM_CRON_SCHEDULE` überschreibbar) einen Lauf aus. Beide Wege laufen über denselben Lock, damit
sie sich nicht überschneiden, und verarbeiten die Konten nacheinander statt parallel.

`fdm-runner` baut `fdm` aus einem gepinnten Upstream-Commit selbst (siehe
[`runner/Dockerfile`](runner/Dockerfile)), **nicht** aus dem Debian/Ubuntu-Paket — das ist ein
Snapshot von Dezember 2018 mit einem bekannten Bug bei der IMAP-`APPEND`-Größenberechnung, der bei
echten Zustellungen zu `BAD Could not parse command`-Fehlern führt.

## Starten

Vorgesehen für den Betrieb hinter [nginx-proxy](https://github.com/nginx-proxy/nginx-proxy)
(optional mit `acme-companion` für automatische Zertifikate) in einem externen Docker-Netzwerk,
z. B. über Portainer per Git-Repository-Stack:

```bash
docker compose up -d --build
```

Relevante Umgebungsvariablen (als Stack-Env-Vars überschreibbar, siehe `docker-compose.yml`):

| Variable | Standard | Bedeutung |
|---|---|---|
| `VIRTUAL_HOST` | `imap-manager.example.com` | vhost für nginx-proxy |
| `LETSENCRYPT_HOST` / `LETSENCRYPT_EMAIL` | s. o. / leer | nur relevant mit `acme-companion` |
| `PROXY_NETWORK` | `nginx-proxy` | Name des externen Docker-Netzwerks |
| `FDM_CRON_SCHEDULE` | `*/5 * * * *` | Cron-Zeitplan für automatische fdm-Läufe |
| `FDM_TRIGGER_POLL_INTERVAL` | `5` | Sekunden zwischen Prüfungen auf `.run_now` |

Ohne Reverse-Proxy lässt sich `imap-manager` auch direkt mit `ports: ["5000:5000"]` statt `expose`
betreiben; Standardmäßig bindet der Flask-Dev-Server (`python app.py` statt gunicorn) nur an
`127.0.0.1`, da die gespeicherte Konfiguration Klartext-Passwörter enthält.

## Wichtige Hinweise

- **Passwörter liegen im Klartext** in `data/config.json` (Volume `imap_manager_data`) — fdm
  braucht sie so. Die Datei wird mit `chmod 600` angelegt; das Volume entsprechend absichern.
- **Kein Outlook/Office365-OAuth2** aktuell unterstützt (Microsoft verlangt dafür eine eigene
  Azure-App-Registrierung plus Token-Refresh-Logik oder einen vorgeschalteten OAuth2-Proxy — bisher
  zurückgestellt).
- **"Verlauf"** ist eine Live-Momentaufnahme der Zielordner per IMAP, kein dauerhaftes Protokoll.
  Zeigen mehrere Regeln auf denselben Zielordner, lässt sich pro Mail nicht eindeutig sagen, welche
  Regel genau gegriffen hat.
- Die `VERSION`-Datei wird bei jeder relevanten Änderung hochgezählt und beim Start beider
  Container geloggt (`docker logs`) sowie unter `GET /api/version` bereitgestellt — nützlich, um zu
  prüfen, ob ein Redeploy tatsächlich das neue Image verwendet.

## API (Auswahl)

| Endpunkt | Zweck |
|---|---|
| `GET /api/config` | gespeicherte Konfiguration |
| `POST /api/imap/folders` (Alias `/api/test-and-fetch-folders`) | Verbindung testen + Ordner live abrufen |
| `GET /api/preview` | generierte `fdm.conf` + Validierungswarnungen |
| `GET /api/download` | `fdm.conf` herunterladen |
| `POST /api/save` | in `~/.fdm.conf`, `/etc/fdm.conf` oder Export-Verzeichnis schreiben |
| `POST /api/run-now` | `fdm.conf` ins geteilte Volume schreiben + `fdm-runner` sofort auslösen |
| `GET /api/history` | zuletzt zugestellte Mails je Zielordner live per IMAP abfragen |
| `GET /api/version` | aktuell laufende Version |
