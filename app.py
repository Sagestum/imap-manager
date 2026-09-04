"""Leichtgewichtiges Webinterface zur visuellen Verwaltung von imapsync-Ordner-Zuordnungen."""
import email
import email.policy
import imaplib
import os
import re
import socket
import stat
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, request, render_template, abort
from werkzeug.exceptions import HTTPException

from imapsync_gen import resolve_mappings
import stats_store

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "config.json"

try:
    VERSION = (BASE_DIR / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    VERSION = "unknown"

# Laeuft auch unter gunicorn (kein "if __name__" noetig), damit sich beim
# Deploy pruefen laesst, ob wirklich das neu gebaute Image aktiv ist.
print(f"[imap-manager] Version: {VERSION}", flush=True)

app = Flask(__name__)

import json


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    response = exc.get_response()
    response.data = json.dumps({"description": exc.description})
    response.content_type = "application/json"
    return response

_LOCK_FREE_DEFAULT = {"accounts": [], "actions": [], "rules": [], "filters": []}


def migrate_config(data):
    """Hebt aeltere Datenstaende auf das aktuelle Schema (dest_folders/dest_action_id)."""
    # Ausnahmeregeln (From/Subject/Header) gibt es seit dem Umstieg auf imapsync nicht mehr -
    # imapsync kennt keine Regel-Engine, Sonderfaelle werden ueber die Ordnerauswahl im
    # Quell-Konto abgebildet. Altbestand wird beim Laden stillschweigend verworfen.
    data["rules"] = [r for r in data["rules"] if r.get("field") in ("source", "all")]

    for account in data["accounts"]:
        account.setdefault("source_folders", [])

    for action in data["actions"]:
        if "dest_folders" not in action:
            legacy_folder = action.pop("folder", None)
            action["dest_folders"] = [legacy_folder] if legacy_folder else []
        else:
            action.pop("folder", None)

    actions_by_id = {a["id"]: a for a in data["actions"]}
    for rule in data["rules"]:
        if "dest_action_id" not in rule:
            legacy_action_id = rule.pop("action_id", None)
            rule["dest_action_id"] = legacy_action_id
            dest_action = actions_by_id.get(legacy_action_id)
            if dest_action and dest_action.get("dest_folders"):
                rule["dest_folder"] = dest_action["dest_folders"][0]
            else:
                rule.setdefault("dest_folder", "")
        else:
            rule.pop("action_id", None)

    return data


def load_config():
    if not DATA_FILE.exists():
        return dict(_LOCK_FREE_DEFAULT)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("accounts", [])
    data.setdefault("actions", [])
    data.setdefault("rules", [])
    data.setdefault("filters", [])
    return migrate_config(data)


def save_config(config):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_file = DATA_FILE.with_suffix(".json.tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    tmp_file.replace(DATA_FILE)
    try:
        os.chmod(DATA_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 600, enthaelt Passwoerter
    except OSError:
        pass


def new_id():
    return uuid.uuid4().hex[:12]


ACCOUNT_TYPES = {"pop3", "pop3s", "imap", "imaps"}
ACTION_TYPES = {"imap", "imaps"}
FIELD_TYPES = {"source", "all"}
FILTER_HEADERS = {"from", "subject"}


def require_fields(payload, fields):
    missing = [f for f in fields if not str(payload.get(f, "")).strip()]
    if missing:
        abort(400, description=f"Fehlende Felder: {', '.join(missing)}")


def parse_port(payload):
    try:
        port = int(payload.get("port"))
    except (TypeError, ValueError):
        abort(400, description="Port muss eine Zahl sein.")
    if not (1 <= port <= 65535):
        abort(400, description="Port muss zwischen 1 und 65535 liegen.")
    return port


def parse_source_folders(payload, account_type):
    folders = payload.get("source_folders", [])
    if not isinstance(folders, list):
        abort(400, description="source_folders muss eine Liste sein.")
    cleaned = []
    seen = set()
    for raw in folders:
        folder = str(raw).strip()
        if not folder or folder in seen:
            continue
        seen.add(folder)
        cleaned.append(folder)
    if cleaned and account_type not in ("imap", "imaps"):
        abort(400, description="Nur IMAP/IMAPS-Konten unterstuetzen mehrere Quell-Ordner.")
    return cleaned


def parse_dest_folders(payload):
    folders = payload.get("dest_folders", [])
    if not isinstance(folders, list):
        abort(400, description="dest_folders muss eine Liste sein.")
    cleaned = []
    seen = set()
    for raw in folders:
        folder = str(raw).strip()
        if not folder or folder in seen:
            continue
        seen.add(folder)
        cleaned.append(folder)
    return cleaned


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(load_config())


@app.route("/api/version", methods=["GET"])
def version():
    return jsonify({"version": VERSION})


# ---------- Accounts ----------

@app.route("/api/accounts", methods=["POST"])
def create_account():
    payload = request.get_json(force=True) or {}
    require_fields(payload, ["name", "type", "server", "user", "pass"])
    if payload["type"] not in ACCOUNT_TYPES:
        abort(400, description="Ungueltiger Account-Typ.")
    port = parse_port(payload)

    config = load_config()
    if any(a["name"] == payload["name"] for a in config["accounts"]):
        abort(400, description="Ein Account mit diesem Namen existiert bereits.")
    source_folders = parse_source_folders(payload, payload["type"])

    account = {
        "id": new_id(),
        "name": payload["name"].strip(),
        "type": payload["type"],
        "server": payload["server"].strip(),
        "port": port,
        "user": payload["user"].strip(),
        "pass": payload["pass"],
        "source_folders": source_folders,
    }
    config["accounts"].append(account)
    save_config(config)
    return jsonify(account), 201


@app.route("/api/accounts/<account_id>", methods=["PUT"])
def update_account(account_id):
    payload = request.get_json(force=True) or {}
    require_fields(payload, ["name", "type", "server", "user", "pass"])
    if payload["type"] not in ACCOUNT_TYPES:
        abort(400, description="Ungueltiger Account-Typ.")
    port = parse_port(payload)

    config = load_config()
    account = next((a for a in config["accounts"] if a["id"] == account_id), None)
    if not account:
        abort(404, description="Account nicht gefunden.")
    if any(a["name"] == payload["name"] and a["id"] != account_id for a in config["accounts"]):
        abort(400, description="Ein Account mit diesem Namen existiert bereits.")
    source_folders = parse_source_folders(payload, payload["type"])

    account.update({
        "name": payload["name"].strip(),
        "type": payload["type"],
        "server": payload["server"].strip(),
        "port": port,
        "user": payload["user"].strip(),
        "pass": payload["pass"],
        "source_folders": source_folders,
    })
    save_config(config)
    return jsonify(account)


@app.route("/api/accounts/<account_id>", methods=["DELETE"])
def delete_account(account_id):
    config = load_config()
    in_use = any(r.get("source_account_id") == account_id for r in config["rules"])
    if in_use:
        abort(400, description="Konto wird noch von mindestens einer Regel als Quelle verwendet.")
    before = len(config["accounts"])
    config["accounts"] = [a for a in config["accounts"] if a["id"] != account_id]
    if len(config["accounts"]) == before:
        abort(404, description="Account nicht gefunden.")
    save_config(config)
    return "", 204


# ---------- Ziel-Server (Actions) ----------

@app.route("/api/actions", methods=["POST"])
def create_action():
    payload = request.get_json(force=True) or {}
    require_fields(payload, ["name", "type", "server", "user", "pass"])
    if payload["type"] not in ACTION_TYPES:
        abort(400, description="Ungueltiger Ziel-Server-Typ.")
    port = parse_port(payload)

    config = load_config()
    if any(a["name"] == payload["name"] for a in config["actions"]):
        abort(400, description="Ein Ziel-Server mit diesem Namen existiert bereits.")
    dest_folders = parse_dest_folders(payload)

    action = {
        "id": new_id(),
        "name": payload["name"].strip(),
        "type": payload["type"],
        "server": payload["server"].strip(),
        "port": port,
        "user": payload["user"].strip(),
        "pass": payload["pass"],
        "dest_folders": dest_folders,
    }
    config["actions"].append(action)
    save_config(config)
    return jsonify(action), 201


@app.route("/api/actions/<action_id>", methods=["PUT"])
def update_action(action_id):
    payload = request.get_json(force=True) or {}
    require_fields(payload, ["name", "type", "server", "user", "pass"])
    if payload["type"] not in ACTION_TYPES:
        abort(400, description="Ungueltiger Ziel-Server-Typ.")
    port = parse_port(payload)

    config = load_config()
    action = next((a for a in config["actions"] if a["id"] == action_id), None)
    if not action:
        abort(404, description="Ziel-Server nicht gefunden.")
    if any(a["name"] == payload["name"] and a["id"] != action_id for a in config["actions"]):
        abort(400, description="Ein Ziel-Server mit diesem Namen existiert bereits.")
    dest_folders = parse_dest_folders(payload)

    action.update({
        "name": payload["name"].strip(),
        "type": payload["type"],
        "server": payload["server"].strip(),
        "port": port,
        "user": payload["user"].strip(),
        "pass": payload["pass"],
        "dest_folders": dest_folders,
    })
    save_config(config)
    return jsonify(action)


@app.route("/api/actions/<action_id>", methods=["DELETE"])
def delete_action(action_id):
    config = load_config()
    in_use = any(r.get("dest_action_id") == action_id for r in config["rules"])
    in_use = in_use or any(f.get("dest_action_id") == action_id for f in config["filters"])
    if in_use:
        abort(400, description="Ziel-Server wird noch von mindestens einer Regel oder einem Filter verwendet.")
    before = len(config["actions"])
    config["actions"] = [a for a in config["actions"] if a["id"] != action_id]
    if len(config["actions"]) == before:
        abort(404, description="Ziel-Server nicht gefunden.")
    save_config(config)
    return "", 204


# ---------- IMAP-Ordner durchsuchen ----------

IMAP_LIST_RE = re.compile(
    rb'^\((?P<flags>[^)]*)\)\s+(?:"(?P<delim>[^"]*)"|NIL)\s+(?P<name>.+)$'
)


def _decode_mailbox_name(raw):
    name = raw.strip()
    if name.startswith(b'"') and name.endswith(b'"'):
        name = name[1:-1]
    return name.decode("utf-8", errors="replace")


def _parse_list_line(raw):
    if raw is None:
        return None
    if isinstance(raw, tuple):
        raw = raw[0]
    match = IMAP_LIST_RE.match(raw)
    if not match:
        return None
    delim = match.group("delim")
    return {
        "name": _decode_mailbox_name(match.group("name")),
        "delimiter": delim.decode(errors="replace") if delim is not None else "",
        "flags": match.group("flags").decode(errors="replace"),
    }


def list_imap_folders(conn_type, server, port, user, password):
    if conn_type == "imaps":
        conn = imaplib.IMAP4_SSL(server, port, timeout=10)
    else:
        conn = imaplib.IMAP4(server, port, timeout=10)
        try:
            conn.starttls()
        except imaplib.IMAP4.error:
            pass  # Server bietet kein STARTTLS an, weiter mit Klartextverbindung

    try:
        conn.login(user, password)
        typ, data = conn.list()
        if typ != "OK":
            raise imaplib.IMAP4.error("IMAP LIST fehlgeschlagen.")
        folders = [f for f in (_parse_list_line(raw) for raw in data) if f]
        folders.sort(key=lambda f: f["name"].lower())
        return folders
    finally:
        try:
            conn.logout()
        except Exception:
            pass


@app.route("/api/imap/folders", methods=["POST"])
def imap_folders():
    payload = request.get_json(force=True) or {}
    require_fields(payload, ["type", "server", "user", "pass"])
    if payload["type"] not in ACTION_TYPES:
        abort(400, description="Ungueltiger IMAP-Typ.")
    port = parse_port(payload)

    try:
        folders = list_imap_folders(
            payload["type"], payload["server"].strip(), port,
            payload["user"].strip(), payload["pass"],
        )
    except imaplib.IMAP4.error as exc:
        abort(502, description=f"IMAP-Anmeldung fehlgeschlagen: {exc}")
    except (socket.timeout, TimeoutError):
        abort(502, description="Zeitueberschreitung bei der Verbindung zum IMAP-Server.")
    except (socket.gaierror, ConnectionRefusedError, OSError) as exc:
        abort(502, description=f"Verbindung zum IMAP-Server fehlgeschlagen: {exc}")

    return jsonify({"folders": folders})


app.add_url_rule("/api/test-and-fetch-folders", view_func=imap_folders, methods=["POST"])


# ---------- Verlauf (live IMAP-Abfrage der Ziel-Ordner) ----------
#
# Es gibt bewusst kein eigenes Protokoll-Parsing der fdm-Laufausgabe: das
# genaue Log-Format von fdm bei "-v" ist nicht zuverlaessig verifizierbar.
# Stattdessen wird direkt der aktuelle Inhalt der Ziel-Ordner abgefragt -
# das ist mit Standard-IMAP (FETCH ENVELOPE) robust und aussagekraeftig,
# zeigt aber den *aktuellen* Ordnerinhalt, kein unveraenderliches Log. Sind
# mehrere Regeln auf denselben Ziel-Ordner gemappt, ist die Zuordnung
# "diese Mail kam durch genau diese Regel" nicht eindeutig auflösbar.

def fetch_recent_messages(conn_type, server, port, user, password, folder, limit=15):
    if conn_type == "imaps":
        conn = imaplib.IMAP4_SSL(server, port, timeout=10)
    else:
        conn = imaplib.IMAP4(server, port, timeout=10)
        try:
            conn.starttls()
        except imaplib.IMAP4.error:
            pass

    try:
        conn.login(user, password)
        typ, _ = conn.select(f'"{folder}"', readonly=True)
        if typ != "OK":
            raise imaplib.IMAP4.error(f'Ordner "{folder}" konnte nicht geoeffnet werden.')
        typ, data = conn.search(None, "ALL")
        if typ != "OK":
            raise imaplib.IMAP4.error("IMAP SEARCH fehlgeschlagen.")

        ids = data[0].split()
        messages = []
        for msg_id in reversed(ids[-limit:]):
            typ, msg_data = conn.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            headers = email.message_from_bytes(msg_data[0][1], policy=email.policy.default)
            messages.append({
                "from": str(headers.get("From", "")),
                "subject": str(headers.get("Subject", "")),
                "date": str(headers.get("Date", "")),
            })
        return messages
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def describe_rule(rule, accounts_by_id):
    if rule.get("field") == "all":
        return "Catch-All (Fallback)"
    acc = accounts_by_id.get(rule.get("source_account_id"))
    return f'Zuordnung: {acc["name"] if acc else "?"} / {rule.get("source_folder", "?")}'


@app.route("/api/history", methods=["GET"])
def history():
    config = load_config()
    actions_by_id = {a["id"]: a for a in config["actions"]}
    accounts_by_id = {a["id"]: a for a in config["accounts"]}

    dest_groups = {}
    for rule in config["rules"]:
        key = (rule.get("dest_action_id"), rule.get("dest_folder"))
        if not key[0] or not key[1]:
            continue
        dest_groups.setdefault(key, []).append(describe_rule(rule, accounts_by_id))

    results = []
    for (action_id, folder), rule_descriptions in dest_groups.items():
        action = actions_by_id.get(action_id)
        entry = {
            "action_name": action["name"] if action else "?",
            "folder": folder,
            "rules": rule_descriptions,
            "messages": [],
            "error": None,
        }
        if not action:
            entry["error"] = "Ziel-Server existiert nicht mehr."
        else:
            try:
                entry["messages"] = fetch_recent_messages(
                    action["type"], action["server"], action["port"],
                    action["user"], action["pass"], folder,
                )
            except imaplib.IMAP4.error as exc:
                entry["error"] = f"IMAP-Fehler: {exc}"
            except (socket.timeout, TimeoutError):
                entry["error"] = "Zeitueberschreitung bei der Verbindung."
            except (socket.gaierror, ConnectionRefusedError, OSError) as exc:
                entry["error"] = f"Verbindungsfehler: {exc}"
        results.append(entry)

    results.sort(key=lambda e: (e["action_name"], e["folder"]))
    return jsonify({"folders": results})


# ---------- Rules ----------

def resolve_source_selection(payload, config):
    source_account_id = payload.get("source_account_id")
    source_account = next(
        (a for a in config["accounts"] if a["id"] == source_account_id), None
    )
    if not source_account:
        abort(400, description="Unbekanntes Quell-Konto.")
    source_folder = str(payload.get("source_folder", "")).strip()
    if source_folder not in (source_account.get("source_folders") or []):
        abort(400, description="Der gewaehlte Quell-Ordner ist bei diesem Konto nicht konfiguriert.")
    return source_account_id, source_folder


def resolve_dest_selection(payload, config):
    dest_action_id = payload.get("dest_action_id")
    dest_action = next(
        (a for a in config["actions"] if a["id"] == dest_action_id), None
    )
    if not dest_action:
        abort(400, description="Unbekannter Ziel-Server.")
    dest_folder = str(payload.get("dest_folder", "")).strip()
    if dest_folder not in (dest_action.get("dest_folders") or []):
        abort(400, description="Der gewaehlte Ziel-Ordner ist bei diesem Ziel-Server nicht konfiguriert.")
    return dest_action_id, dest_folder


def check_duplicate_mapping(config, source_account_id, source_folder, exclude_rule_id=None):
    duplicate = any(
        r.get("field") == "source"
        and r.get("id") != exclude_rule_id
        and r.get("source_account_id") == source_account_id
        and r.get("source_folder") == source_folder
        for r in config["rules"]
    )
    if duplicate:
        abort(400, description="Fuer dieses Quell-Konto und diesen Quell-Ordner existiert bereits eine Zuordnung.")


@app.route("/api/rules", methods=["POST"])
def create_rule():
    payload = request.get_json(force=True) or {}
    field = payload.get("field")
    if field not in FIELD_TYPES:
        abort(400, description="Ungueltiges Regel-Feld.")

    config = load_config()
    dest_action_id, dest_folder = resolve_dest_selection(payload, config)

    rule = {
        "id": new_id(),
        "field": field,
        "dest_action_id": dest_action_id,
        "dest_folder": dest_folder,
    }

    if field == "all":
        if any(r["field"] == "all" for r in config["rules"]):
            abort(400, description="Es existiert bereits eine Catch-All-Regel.")
    else:
        source_account_id, source_folder = resolve_source_selection(payload, config)
        check_duplicate_mapping(config, source_account_id, source_folder)
        rule["source_account_id"] = source_account_id
        rule["source_folder"] = source_folder

    config["rules"].append(rule)
    save_config(config)
    return jsonify(rule), 201


@app.route("/api/rules/<rule_id>", methods=["PUT"])
def update_rule(rule_id):
    payload = request.get_json(force=True) or {}
    field = payload.get("field")
    if field not in FIELD_TYPES:
        abort(400, description="Ungueltiges Regel-Feld.")

    config = load_config()
    rule = next((r for r in config["rules"] if r["id"] == rule_id), None)
    if not rule:
        abort(404, description="Regel nicht gefunden.")

    dest_action_id, dest_folder = resolve_dest_selection(payload, config)

    new_rule = {
        "id": rule_id,
        "field": field,
        "dest_action_id": dest_action_id,
        "dest_folder": dest_folder,
    }

    if field == "all":
        if any(r["field"] == "all" and r["id"] != rule_id for r in config["rules"]):
            abort(400, description="Es existiert bereits eine Catch-All-Regel.")
    else:
        source_account_id, source_folder = resolve_source_selection(payload, config)
        check_duplicate_mapping(config, source_account_id, source_folder, exclude_rule_id=rule_id)
        new_rule["source_account_id"] = source_account_id
        new_rule["source_folder"] = source_folder

    idx = config["rules"].index(rule)
    config["rules"][idx] = new_rule
    save_config(config)
    return jsonify(new_rule)


@app.route("/api/rules/<rule_id>", methods=["DELETE"])
def delete_rule(rule_id):
    config = load_config()
    before = len(config["rules"])
    config["rules"] = [r for r in config["rules"] if r["id"] != rule_id]
    if len(config["rules"]) == before:
        abort(404, description="Regel nicht gefunden.")
    save_config(config)
    return "", 204


# ---------- Filter (Post-Sync-Absender/Betreff-Regeln) ----------
#
# Getrennt von den Ordner-Zuordnungen (rules): imapsync selbst kennt kein Content-Routing, daher
# laeuft dieser Schritt erst NACH dem Sync auf dem Zielordner (siehe mail_filter.py im Runner).
# watch_folder/target_folder werden bewusst gegen dest_action.dest_folders validiert - dieselbe
# Liste, die auch die Ordner-Zuordnungen benutzen, keine neue Ordner-Lade-Logik noetig.

def resolve_filter_folders(payload, dest_action):
    watch_folder = str(payload.get("watch_folder", "")).strip()
    target_folder = str(payload.get("target_folder", "")).strip()
    dest_folders = dest_action.get("dest_folders") or []
    if watch_folder not in dest_folders:
        abort(400, description="Der beobachtete Ordner ist bei diesem Ziel-Server nicht konfiguriert.")
    if target_folder not in dest_folders:
        abort(400, description="Der Ziel-Ordner ist bei diesem Ziel-Server nicht konfiguriert.")
    if watch_folder == target_folder:
        abort(400, description="Beobachteter Ordner und Ziel-Ordner duerfen nicht identisch sein.")
    return watch_folder, target_folder


def build_filter(payload, config, filter_id=None):
    header = payload.get("header")
    if header not in FILTER_HEADERS:
        abort(400, description="Ungueltiges Filter-Feld (from/subject).")
    match = str(payload.get("match", "")).strip()
    if not match:
        abort(400, description="Muster darf nicht leer sein.")

    dest_action_id = payload.get("dest_action_id")
    dest_action = next((a for a in config["actions"] if a["id"] == dest_action_id), None)
    if not dest_action:
        abort(400, description="Unbekannter Ziel-Server.")
    watch_folder, target_folder = resolve_filter_folders(payload, dest_action)

    return {
        "id": filter_id or new_id(),
        "dest_action_id": dest_action_id,
        "watch_folder": watch_folder,
        "header": header,
        "match": match,
        "target_folder": target_folder,
    }


@app.route("/api/filters", methods=["POST"])
def create_filter():
    payload = request.get_json(force=True) or {}
    config = load_config()
    filter_ = build_filter(payload, config)
    config["filters"].append(filter_)
    save_config(config)
    return jsonify(filter_), 201


@app.route("/api/filters/<filter_id>", methods=["PUT"])
def update_filter(filter_id):
    payload = request.get_json(force=True) or {}
    config = load_config()
    if not any(f["id"] == filter_id for f in config["filters"]):
        abort(404, description="Filter nicht gefunden.")
    new_filter = build_filter(payload, config, filter_id=filter_id)
    idx = next(i for i, f in enumerate(config["filters"]) if f["id"] == filter_id)
    config["filters"][idx] = new_filter
    save_config(config)
    return jsonify(new_filter)


@app.route("/api/filters/<filter_id>", methods=["DELETE"])
def delete_filter(filter_id):
    config = load_config()
    before = len(config["filters"])
    config["filters"] = [f for f in config["filters"] if f["id"] != filter_id]
    if len(config["filters"]) == before:
        abort(404, description="Filter nicht gefunden.")
    save_config(config)
    return "", 204


RUN_CONFIG_DIR = Path(os.environ.get("FDM_CONFIG_DIR", str(BASE_DIR / "config")))
RUN_TRIGGER_FILE = RUN_CONFIG_DIR / ".run_now"
STATS_DB_PATH = RUN_CONFIG_DIR / stats_store.DB_FILENAME


@app.route("/api/stats/daily", methods=["GET"])
def stats_daily():
    """Taeglich aggregierte Nachrichten-Zahlen aus dem Runner (siehe stats_store.py), gruppiert
    pro Quell-Konto. Ueberlebt das Loeschen eines Kontos aus der Konfiguration, da nach dessen
    Namen (nicht seiner ID) geschluesselt wird."""
    try:
        days = int(request.args.get("days", 30))
    except (TypeError, ValueError):
        abort(400, description="days muss eine Zahl sein.")
    days = max(1, min(days, 730))

    rows = stats_store.query_daily_by_account(days, STATS_DB_PATH)

    today = datetime.now(timezone.utc).date()
    day_list = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    day_index = {d: i for i, d in enumerate(day_list)}

    accounts = sorted({r["source_account"] for r in rows})
    series = {name: [0] * len(day_list) for name in accounts}
    totals = {name: 0 for name in accounts}
    deleted_totals = {name: 0 for name in accounts}
    for r in rows:
        idx = day_index.get(r["date"])
        if idx is None:
            continue
        name = r["source_account"]
        series[name][idx] += r["messages_transferred"]
        totals[name] += r["messages_transferred"]
        deleted_totals[name] += r["messages_deleted"]

    return jsonify({
        "days": day_list,
        "accounts": accounts,
        "series": series,
        "totals": totals,
        "deleted_totals": deleted_totals,
    })


def _serialize_mapping(mapping):
    acc, act = mapping["source_account"], mapping["dest_action"]
    return {
        "source_account": {
            "name": acc["name"], "type": acc["type"], "server": acc["server"],
            "port": acc["port"], "user": acc["user"], "pass": acc["pass"],
        },
        "source_folder": mapping["source_folder"],
        "dest_action": {
            "name": act["name"], "type": act["type"], "server": act["server"],
            "port": act["port"], "user": act["user"], "pass": act["pass"],
        },
        "dest_folder": mapping["dest_folder"],
    }


def _serialize_filter(filter_, actions_by_id):
    act = actions_by_id.get(filter_["dest_action_id"])
    if not act:
        return None
    return {
        "dest_action": {
            "name": act["name"], "type": act["type"], "server": act["server"],
            "port": act["port"], "user": act["user"], "pass": act["pass"],
        },
        "watch_folder": filter_["watch_folder"],
        "header": filter_["header"],
        "match": filter_["match"],
        "target_folder": filter_["target_folder"],
    }


@app.route("/api/run-now", methods=["POST"])
def run_now():
    """Schreibt die aufgeloesten Ordner-Zuordnungen als sync_plan.json und die Filter als
    filter_plan.json ins geteilte Volume und legt eine Trigger-Datei an, die der
    fdm-runner-Container abfragt (siehe docker-compose.yml).
    """
    config = load_config()
    actions_by_id = {a["id"]: a for a in config["actions"]}

    mappings = resolve_mappings(config)
    plan = [_serialize_mapping(m) for m in mappings]
    dest = RUN_CONFIG_DIR / "sync_plan.json"

    filter_plan = [
        f for f in (_serialize_filter(flt, actions_by_id) for flt in config["filters"]) if f
    ]
    filter_dest = RUN_CONFIG_DIR / "filter_plan.json"

    try:
        RUN_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
        os.chmod(dest, stat.S_IRUSR | stat.S_IWUSR)  # 600, enthaelt Klartext-Passwoerter
        with open(filter_dest, "w", encoding="utf-8") as f:
            json.dump(filter_plan, f, indent=2, ensure_ascii=False)
        os.chmod(filter_dest, stat.S_IRUSR | stat.S_IWUSR)  # 600, enthaelt Klartext-Passwoerter
        RUN_TRIGGER_FILE.touch()
    except OSError as exc:
        abort(500, description=f"Fehler beim Speichern/Ausloesen: {exc}")

    return jsonify({
        "saved_to": str(dest), "triggered": True, "mappings": len(plan), "filters": len(filter_plan),
    })


if __name__ == "__main__":
    # Standardmaessig nur localhost: die Konfiguration enthaelt Klartext-Passwoerter.
    # In Docker per FDM_WEBUI_HOST=0.0.0.0 ueberschrieben (Netzwerkisolation uebernimmt der Container).
    host = os.environ.get("FDM_WEBUI_HOST", "127.0.0.1")
    port = int(os.environ.get("FDM_WEBUI_PORT", "5000"))
    app.run(host=host, port=port, debug=False)
