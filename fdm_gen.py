"""Erzeugt fdm.conf-Dateien aus dem gespeicherten Konfigurationsmodell."""
import re


def _q(value):
    """Bettet einen String sicher in doppelte fdm-Anführungszeichen ein."""
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def account_variant_name(account, folder):
    """Eindeutiger fdm-Accountname fuer ein einzelnes Postfach+Ordner-Paar.

    Ohne Leerzeichen/Sonderzeichen, damit re.escape() beim Erzeugen der
    "match account"-Regel keine Escape-Sequenzen erzeugt, die von einer
    strikten POSIX-ERE-Implementierung (regcomp) abgelehnt werden koennten.
    """
    return f'{account["name"]}::{folder}'


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
    accounts_by_id = {a["id"]: a for a in accounts}

    lines = []

    lines.append("# --- ACCOUNTS ---")
    if not accounts:
        lines.append("# (keine Accounts konfiguriert)")
    for acc in accounts:
        folders = acc.get("source_folders") or []
        if not folders:
            lines.append(
                f'account {_q(acc["name"])} {acc["type"]} '
                f'server {_q(acc["server"])} port {acc["port"]} '
                f'user {_q(acc["user"])} pass {_q(acc["pass"])}'
            )
            continue
        for folder in folders:
            lines.append(
                f'account {_q(account_variant_name(acc, folder))} {acc["type"]} '
                f'server {_q(acc["server"])} port {acc["port"]} '
                f'user {_q(acc["user"])} pass {_q(acc["pass"])} '
                f'folder {_q(folder)}'
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

        if rule.get("field") == "source":
            source_account = accounts_by_id.get(rule.get("source_account_id"))
            folder = rule.get("source_folder")
            if not source_account or not folder:
                continue
            variant_name = account_variant_name(source_account, folder)
            pattern = f"^{re.escape(variant_name)}$"
            lines.append(
                f'match account {_q(pattern)} action {_q(action_name)}'
            )
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
    accounts_by_id = {a["id"]: a for a in config.get("accounts", [])}

    if len(account_names) != len(set(account_names)):
        warnings.append("Es gibt Accounts mit doppeltem Namen.")

    action_names = [a["name"] for a in config.get("actions", [])]
    if len(action_names) != len(set(action_names)):
        warnings.append("Es gibt Actions mit doppeltem Namen.")

    for rule in config.get("rules", []):
        if rule.get("action_id") not in action_ids:
            warnings.append(
                "Regel verweist auf eine nicht existierende Action."
            )
        if rule.get("field") == "header" and not rule.get("header_name", "").strip():
            warnings.append("Eine Header-Regel hat keinen Headernamen gesetzt.")
        if rule.get("field") == "source":
            source_account = accounts_by_id.get(rule.get("source_account_id"))
            folder = rule.get("source_folder")
            if not source_account:
                warnings.append("Eine Quell-Ordner-Regel verweist auf ein nicht existierendes Konto.")
            elif folder not in (source_account.get("source_folders") or []):
                warnings.append(
                    f'Eine Regel verweist auf den Ordner "{folder}", der bei '
                    f'"{source_account["name"]}" nicht mehr konfiguriert ist.'
                )

    catchalls = [r for r in config.get("rules", []) if r.get("field") == "all"]
    if len(catchalls) > 1:
        warnings.append("Es gibt mehr als eine Catch-All-Regel.")
    if not catchalls and config.get("rules"):
        warnings.append("Keine Catch-All-Regel vorhanden (optional, aber empfohlen).")

    return warnings
