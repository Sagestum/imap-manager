"""Erzeugt fdm.conf-Dateien aus dem gespeicherten Konfigurationsmodell."""
import re


def _q(value):
    """Bettet einen String sicher in doppelte fdm-Anführungszeichen ein."""
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def pattern_for_rule(rule):
    """Baut aus Matching-Art + Eingabe den regulären Ausdruck fuer die Regel."""
    match_type = rule.get("match_type")
    value = rule.get("value", "")
    if match_type == "regex":
        return value
    escaped = re.escape(value)
    if match_type == "exact":
        return f"^{escaped}$"
    # "contains" (Standard)
    return escaped


def header_name_for_rule(rule):
    field = rule.get("field")
    if field == "from":
        return "From"
    if field == "subject":
        return "Subject"
    if field == "header":
        return rule.get("header_name", "").strip() or "X-Custom"
    return None


def generate_conf(config):
    accounts = config.get("accounts", [])
    actions = config.get("actions", [])
    rules = config.get("rules", [])

    action_names = {a["id"]: a["name"] for a in actions}

    lines = []

    lines.append("# --- ACCOUNTS ---")
    if not accounts:
        lines.append("# (keine Accounts konfiguriert)")
    for acc in accounts:
        lines.append(
            f'account {_q(acc["name"])} {acc["type"]} '
            f'server {_q(acc["server"])} port {acc["port"]} '
            f'user {_q(acc["user"])} pass {_q(acc["pass"])}'
        )
    lines.append("")

    lines.append("# --- ACTIONS ---")
    if not actions:
        lines.append("# (keine Actions konfiguriert)")
    for act in actions:
        lines.append(
            f'action {_q(act["name"])} {act["type"]} '
            f'server {_q(act["server"])} port {act["port"]} '
            f'user {_q(act["user"])} pass {_q(act["pass"])} '
            f'folder {_q(act["folder"])}'
        )
    lines.append("")

    lines.append("# --- RULES ---")
    normal_rules = [r for r in rules if r.get("field") != "all"]
    catchall_rules = [r for r in rules if r.get("field") == "all"]

    if not normal_rules and not catchall_rules:
        lines.append("# (keine Regeln konfiguriert)")

    for rule in normal_rules:
        action_name = action_names.get(rule.get("action_id"))
        if not action_name:
            continue
        header = header_name_for_rule(rule)
        pattern = pattern_for_rule(rule)
        lines.append(
            f'match header {_q(header)} regex {_q(pattern)} action {_q(action_name)}'
        )

    for rule in catchall_rules:
        action_name = action_names.get(rule.get("action_id"))
        if not action_name:
            continue
        lines.append("")
        lines.append("# Fallback Rule")
        lines.append(f'match all action {_q(action_name)}')

    lines.append("")
    return "\n".join(lines)


def validate_config(config):
    """Einfache Konsistenzpruefung; gibt Liste von Warnungen zurueck."""
    warnings = []
    account_names = [a["name"] for a in config.get("accounts", [])]
    action_ids = {a["id"] for a in config.get("actions", [])}

    if len(account_names) != len(set(account_names)):
        warnings.append("Es gibt Accounts mit doppeltem Namen.")

    action_names = [a["name"] for a in config.get("actions", [])]
    if len(action_names) != len(set(action_names)):
        warnings.append("Es gibt Actions mit doppeltem Namen.")

    for rule in config.get("rules", []):
        if rule.get("action_id") not in action_ids:
            warnings.append(
                f"Regel verweist auf eine nicht existierende Action."
            )
        if rule.get("field") == "header" and not rule.get("header_name", "").strip():
            warnings.append("Eine Header-Regel hat keinen Headernamen gesetzt.")

    catchalls = [r for r in config.get("rules", []) if r.get("field") == "all"]
    if len(catchalls) > 1:
        warnings.append("Es gibt mehr als eine Catch-All-Regel.")
    if not catchalls and config.get("rules"):
        warnings.append("Keine Catch-All-Regel vorhanden (optional, aber empfohlen).")

    return warnings
