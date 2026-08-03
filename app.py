"""Leichtgewichtiges Webinterface zur visuellen Verwaltung einer fdm.conf."""
import imaplib
import os
import re
import socket
import stat
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, render_template, send_file, abort
from werkzeug.exceptions import HTTPException
import io

from fdm_gen import generate_conf, validate_config

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "config.json"

app = Flask(__name__)

import json


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    response = exc.get_response()
    response.data = json.dumps({"description": exc.description})
    response.content_type = "application/json"
    return response

_LOCK_FREE_DEFAULT = {"accounts": [], "actions": [], "rules": []}


def load_config():
    if not DATA_FILE.exists():
        return dict(_LOCK_FREE_DEFAULT)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("accounts", [])
    data.setdefault("actions", [])
    data.setdefault("rules", [])
    return data


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
MATCH_TYPES = {"contains", "exact", "regex"}
FIELD_TYPES = {"from", "subject", "header", "all"}


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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(load_config())


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

    account = {
        "id": new_id(),
        "name": payload["name"].strip(),
        "type": payload["type"],
        "server": payload["server"].strip(),
        "port": port,
        "user": payload["user"].strip(),
        "pass": payload["pass"],
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

    account.update({
        "name": payload["name"].strip(),
        "type": payload["type"],
        "server": payload["server"].strip(),
        "port": port,
        "user": payload["user"].strip(),
        "pass": payload["pass"],
    })
    save_config(config)
    return jsonify(account)


@app.route("/api/accounts/<account_id>", methods=["DELETE"])
def delete_account(account_id):
    config = load_config()
    before = len(config["accounts"])
    config["accounts"] = [a for a in config["accounts"] if a["id"] != account_id]
    if len(config["accounts"]) == before:
        abort(404, description="Account nicht gefunden.")
    save_config(config)
    return "", 204


# ---------- Actions ----------

@app.route("/api/actions", methods=["POST"])
def create_action():
    payload = request.get_json(force=True) or {}
    require_fields(payload, ["name", "type", "server", "user", "pass", "folder"])
    if payload["type"] not in ACTION_TYPES:
        abort(400, description="Ungueltiger Action-Typ.")
    port = parse_port(payload)

    config = load_config()
    if any(a["name"] == payload["name"] for a in config["actions"]):
        abort(400, description="Eine Action mit diesem Namen existiert bereits.")

    action = {
        "id": new_id(),
        "name": payload["name"].strip(),
        "type": payload["type"],
        "server": payload["server"].strip(),
        "port": port,
        "user": payload["user"].strip(),
        "pass": payload["pass"],
        "folder": payload["folder"].strip(),
    }
    config["actions"].append(action)
    save_config(config)
    return jsonify(action), 201


@app.route("/api/actions/<action_id>", methods=["PUT"])
def update_action(action_id):
    payload = request.get_json(force=True) or {}
    require_fields(payload, ["name", "type", "server", "user", "pass", "folder"])
    if payload["type"] not in ACTION_TYPES:
        abort(400, description="Ungueltiger Action-Typ.")
    port = parse_port(payload)

    config = load_config()
    action = next((a for a in config["actions"] if a["id"] == action_id), None)
    if not action:
        abort(404, description="Action nicht gefunden.")
    if any(a["name"] == payload["name"] and a["id"] != action_id for a in config["actions"]):
        abort(400, description="Eine Action mit diesem Namen existiert bereits.")

    action.update({
        "name": payload["name"].strip(),
        "type": payload["type"],
        "server": payload["server"].strip(),
        "port": port,
        "user": payload["user"].strip(),
        "pass": payload["pass"],
        "folder": payload["folder"].strip(),
    })
    save_config(config)
    return jsonify(action)


@app.route("/api/actions/<action_id>", methods=["DELETE"])
def delete_action(action_id):
    config = load_config()
    in_use = any(r.get("action_id") == action_id for r in config["rules"])
    if in_use:
        abort(400, description="Action wird noch von mindestens einer Regel verwendet.")
    before = len(config["actions"])
    config["actions"] = [a for a in config["actions"] if a["id"] != action_id]
    if len(config["actions"]) == before:
        abort(404, description="Action nicht gefunden.")
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


# ---------- Rules ----------

@app.route("/api/rules", methods=["POST"])
def create_rule():
    payload = request.get_json(force=True) or {}
    field = payload.get("field")
    if field not in FIELD_TYPES:
        abort(400, description="Ungueltiges Regel-Feld.")

    config = load_config()
    action_id = payload.get("action_id")
    if not any(a["id"] == action_id for a in config["actions"]):
        abort(400, description="Unbekannte Ziel-Action.")

    rule = {"id": new_id(), "field": field, "action_id": action_id}

    if field == "all":
        if any(r["field"] == "all" for r in config["rules"]):
            abort(400, description="Es existiert bereits eine Catch-All-Regel.")
    else:
        match_type = payload.get("match_type")
        if match_type not in MATCH_TYPES:
            abort(400, description="Ungueltige Matching-Art.")
        value = payload.get("value", "").strip()
        if not value:
            abort(400, description="Wert fuer das Matching darf nicht leer sein.")
        rule["match_type"] = match_type
        rule["value"] = value
        if field == "header":
            header_name = payload.get("header_name", "").strip()
            if not header_name:
                abort(400, description="Headername darf nicht leer sein.")
            rule["header_name"] = header_name

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

    action_id = payload.get("action_id")
    if not any(a["id"] == action_id for a in config["actions"]):
        abort(400, description="Unbekannte Ziel-Action.")

    new_rule = {"id": rule_id, "field": field, "action_id": action_id}

    if field == "all":
        if any(r["field"] == "all" and r["id"] != rule_id for r in config["rules"]):
            abort(400, description="Es existiert bereits eine Catch-All-Regel.")
    else:
        match_type = payload.get("match_type")
        if match_type not in MATCH_TYPES:
            abort(400, description="Ungueltige Matching-Art.")
        value = payload.get("value", "").strip()
        if not value:
            abort(400, description="Wert fuer das Matching darf nicht leer sein.")
        new_rule["match_type"] = match_type
        new_rule["value"] = value
        if field == "header":
            header_name = payload.get("header_name", "").strip()
            if not header_name:
                abort(400, description="Headername darf nicht leer sein.")
            new_rule["header_name"] = header_name

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


@app.route("/api/rules/reorder", methods=["POST"])
def reorder_rules():
    payload = request.get_json(force=True) or {}
    order = payload.get("order")
    if not isinstance(order, list):
        abort(400, description="order muss eine Liste von Regel-IDs sein.")

    config = load_config()
    by_id = {r["id"]: r for r in config["rules"]}
    if set(order) != set(by_id.keys()):
        abort(400, description="order muss exakt alle vorhandenen Regel-IDs enthalten.")

    config["rules"] = [by_id[i] for i in order]
    save_config(config)
    return jsonify(config["rules"])


# ---------- Vorschau / Export ----------

@app.route("/api/preview", methods=["GET"])
def preview():
    config = load_config()
    return jsonify({
        "conf": generate_conf(config),
        "warnings": validate_config(config),
    })


@app.route("/api/download", methods=["GET"])
def download():
    config = load_config()
    conf_text = generate_conf(config)
    buf = io.BytesIO(conf_text.encode("utf-8"))
    return send_file(
        buf,
        mimetype="text/plain",
        as_attachment=True,
        download_name="fdm.conf",
    )


EXPORT_DIR = Path(os.environ.get("FDM_EXPORT_DIR", str(BASE_DIR / "export")))

ALLOWED_SAVE_TARGETS = {
    "~/.fdm.conf": Path.home() / ".fdm.conf",
    "/etc/fdm.conf": Path("/etc/fdm.conf"),
    "export": EXPORT_DIR / "fdm.conf",
}


@app.route("/api/save", methods=["POST"])
def save_to_disk():
    payload = request.get_json(force=True) or {}
    target = payload.get("target")
    if target not in ALLOWED_SAVE_TARGETS:
        abort(400, description="Unbekanntes Ziel. Erlaubt: ~/.fdm.conf oder /etc/fdm.conf.")

    dest = ALLOWED_SAVE_TARGETS[target]
    config = load_config()
    conf_text = generate_conf(config)

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(conf_text)
        os.chmod(dest, stat.S_IRUSR | stat.S_IWUSR)  # 600, enthaelt Klartext-Passwoerter
    except PermissionError:
        abort(403, description=f"Keine Schreibrechte fuer {dest}. Ggf. mit sudo starten.")
    except OSError as exc:
        abort(500, description=f"Fehler beim Schreiben von {dest}: {exc}")

    return jsonify({"saved_to": str(dest)})


if __name__ == "__main__":
    # Standardmaessig nur localhost: die Konfiguration enthaelt Klartext-Passwoerter.
    # In Docker per FDM_WEBUI_HOST=0.0.0.0 ueberschrieben (Netzwerkisolation uebernimmt der Container).
    host = os.environ.get("FDM_WEBUI_HOST", "127.0.0.1")
    port = int(os.environ.get("FDM_WEBUI_PORT", "5000"))
    app.run(host=host, port=port, debug=False)
