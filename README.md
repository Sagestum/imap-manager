# imap-manager

Webinterface zur visuellen Verwaltung einer [`imapsync`](https://github.com/imapsync/imapsync)-
Konfiguration: Quell-Postfächer und Ziel-Server per Formular anlegen, Ordner live per IMAP
durchsuchen statt Pfade zu raten, Ordner-Zuordnungen zusammenklicken — und daraus wird automatisch
ein Satz `imapsync`-Aufrufe erzeugt und optional direkt ausgeführt.

## Was das Tool tut

- **Quell-Konten**: IMAP/IMAPS-Postfächer anlegen (POP3/POP3S bleiben zwar als Kontotyp waehlbar,
  werden aber beim Sync uebersprungen - `imapsync` synchronisiert nur IMAP<->IMAP). Beliebig viele
  Quell-Ordner per Live-Verbindung auswaehlen (z. B. `INBOX` und der providerspezifische
  Spam-Ordner), statt den Ordnernamen zu erraten.
- **Ziel-Server**: IMAP/IMAPS-Zielserver anlegen, ebenfalls mit live durchsuchbaren Ordnern. Ein
  Zugangsdaten-Satz deckt beliebig viele Zielordner ab (z. B. `INBOX` und `Archiv/Rechnungen` im
  selben Gmail-Konto), ohne die Zugangsdaten mehrfach einzutragen.
- **Ordner-Zuordnungen**: "alles aus Quelle A / Ordner B nach Ziel C / Ordner D", ausgewählt per
  Dropdown statt getippt. Sonderfälle (z. B. "Newsletter landet in Spam") werden ueber die
  Ordnerauswahl im Quell-Konto abgebildet, nicht ueber eine eigene Regel-Engine - z. B. den
  Spam-Ordner des Anbieters als eigenen Quell-Ordner mappen.
- **Catch-All**: optionaler Fallback für Quell-Ordner ohne eigene Zuordnung.
- **Verlauf**: fragt auf Wunsch live per IMAP die zuletzt in den Zielordnern angekommenen Mails ab
  (Datum/Von/Betreff), um zu sehen, was tatsächlich zugestellt wurde.

Die Anwendung baut daraus pro Ordner-Zuordnung einen `imapsync`-Aufruf (keine Text-Config, die ein
externer Parser neu einliest - direkt eine Argument-Liste), der sich per "Speichern & Jetzt
ausführen" direkt in einem zweiten Container ausführen lässt (siehe unten).

## Architektur: zwei Container

| Service | Zweck |
|---|---|
| `imap-manager` | Flask-Webinterface, löst Ordner-Zuordnungen zu `imapsync`-Aufrufen auf |
| `fdm-runner` | Führt die Aufrufe regelmäßig (Cron) und/oder auf Trigger aus |

Beide teilen sich ein Volume (`imap_manager_config`, gemountet unter `/app/config`). Der
Web-Container schreibt dort `sync_plan.json` (die aufgelösten Ordner-Zuordnungen inkl.
Zugangsdaten) und bei Bedarf eine `.run_now`-Trigger-Datei hinein; der Runner-Container pollt
darauf und führt zusätzlich per Cron (Standard: alle 5 Minuten, `FDM_CRON_SCHEDULE`
überschreibbar) einen Lauf aus. Beide Wege laufen über denselben Lock, damit sie sich nicht
überschneiden, und verarbeiten die Ordner-Zuordnungen nacheinander statt parallel (manche
IMAP-Server reagieren empfindlich auf viele gleichzeitige Verbindungen).

`fdm-runner` installiert `imapsync` von einem gepinnten Upstream-Commit (siehe
[`runner/Dockerfile`](runner/Dockerfile)) statt aus einem Debian-Paket - `imapsync` wurde 2011 aus
Debian entfernt (Lizenzdiskussion, siehe `tracker.debian.org/pkg/imapsync`) und ist dort bis heute
nicht wieder gelistet. Nach dem erfolgreichen Transfer wird die Mail im Quell-Postfach gelöscht
(`--delete1`, impliziert automatisch ein Expunge) - das entspricht dem Verhalten des frueheren
`fdm`-basierten Aufbaus dieses Projekts. Datum-Erhalt und Gmail-Kompatibilität sind eingebaute
`imapsync`-Funktionen (`--syncinternaldates` bzw. `--gmail1`/`--gmail2`, automatisch gesetzt wenn
Quelle/Ziel `gmail.com` ist) - anders als beim vorherigen `fdm`-Aufbau sind dafür keine eigenen
Patches mehr nötig.

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
| `FDM_CRON_SCHEDULE` | `*/5 * * * *` | Cron-Zeitplan für automatische Sync-Läufe |
| `FDM_TRIGGER_POLL_INTERVAL` | `5` | Sekunden zwischen Prüfungen auf `.run_now` |
| `FDM_SECRET_KEY` | – (Pflicht) | Fernet-Schlüssel zum Ver-/Entschlüsseln der Passwörter in `config.json`, nur beim `imap-manager`-Service nötig - erzeugen mit `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`, getrennt vom Config-Volume aufbewahren (z. B. `.env` neben der `docker-compose.yml`, nicht im Git-Repo) |

(Die `FDM_`-Praefixe stammen noch vom fruehen `fdm`-basierten Aufbau und wurden bewusst nicht
umbenannt, um bereits konfigurierte Stack-Env-Vars nicht zu invalidieren.)

Ohne Reverse-Proxy lässt sich `imap-manager` auch direkt mit `ports: ["5000:5000"]` statt `expose`
betreiben; Standardmäßig bindet der Flask-Dev-Server (`python app.py` statt gunicorn) nur an
`127.0.0.1`, da die gespeicherte Konfiguration Klartext-Passwörter enthält.

## Wichtige Hinweise

- **Passwörter**: in `data/config.json` (Volume `imap_manager_data`) mit Fernet
  (`FDM_SECRET_KEY`, siehe oben) verschlüsselt abgelegt. In `sync_plan.json`/`filter_plan.json` im
  geteilten Config-Volume liegen sie dagegen im Klartext - `imapsync` und der Post-Sync-Filter
  brauchen sie dort direkt verwertbar. Alle drei Dateien werden mit `chmod 600` angelegt; die
  Volumes entsprechend absichern. Beim tatsächlichen `imapsync`-Aufruf werden die Passwörter per
  `--passfile1`/`--passfile2` übergeben (temporäre Datei, sofort nach dem Aufruf gelöscht), nicht
  als Klartext-Argument - so tauchen sie nicht in `ps aux` auf.
- **Kein Outlook/Office365-OAuth2** aktuell unterstützt (Microsoft verlangt dafür eine eigene
  Azure-App-Registrierung plus Token-Refresh-Logik oder einen vorgeschalteten OAuth2-Proxy — bisher
  zurückgestellt).
- **"Verlauf"** ist eine Live-Momentaufnahme der Zielordner per IMAP, kein dauerhaftes Protokoll.
  Zeigen mehrere Zuordnungen auf denselben Zielordner, lässt sich pro Mail nicht eindeutig sagen,
  welche Zuordnung genau gegriffen hat.
- Die `VERSION`-Datei wird bei jeder relevanten Änderung hochgezählt und beim Start beider
  Container geloggt (`docker logs`) sowie unter `GET /api/version` bereitgestellt — nützlich, um zu
  prüfen, ob ein Redeploy tatsächlich das neue Image verwendet.

## API (Auswahl)

| Endpunkt | Zweck |
|---|---|
| `GET /api/config` | gespeicherte Konfiguration |
| `POST /api/imap/folders` (Alias `/api/test-and-fetch-folders`) | Verbindung testen + Ordner live abrufen |
| `POST /api/run-now` | `sync_plan.json` ins geteilte Volume schreiben + `fdm-runner` sofort auslösen |
| `GET /api/history` | zuletzt zugestellte Mails je Zielordner live per IMAP abfragen |
| `GET /api/version` | aktuell laufende Version |
