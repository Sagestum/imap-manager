"""Erzeugt fdm.conf-Dateien aus dem gespeicherten Konfigurationsmodell."""
import re


def _q(value):
    """Bettet einen String sicher in doppelte fdm-Anführungszeichen ein."""
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def account_variant_name(account, folder):
    """Eindeutiger fdm-Accountname fuer ein einzelnes Postfach+Ordner-Paar."""
    return f'{account["name"]}::{folder}'


def action_variant_name(action, folder):
    """Eindeutiger fdm-Actionname fuer ein einzelnes Ziel-Server+Ordner-Paar."""
    return f'{action["name"]}::{folder}'


_GLOB_SPECIAL = set("*?[]\\")


def escape_glob(value):
    """Escaped einen String fuer "match account", das laut fdm.conf(5) shell-
    glob-Wildcards verwendet (kein Regex - anders als "match header ... regex").
    """
    return "".join(f"\\{c}" if c in _GLOB_SPECIAL else c for c in value)


def header_name_for_rule(rule):
    field = rule.get("field")
    if field == "from":
        return "From"
    if field == "subject":
        return "Subject"
    if field == "header":
        return rule.get("header_name", "").strip() or "X-Custom"
    return None


def header_match_pattern(rule):
    """Baut den vollstaendigen Regex, der eine einzelne Kopfzeile (z. B. "From") matcht.

    fdm kennt kein eigenes "match header <name> ..."-Statement - "header" ist zwar ein
    reserviertes Lexer-Token, hat in parse.y aber keine Grammatikregel und fuehrt daher
    IMMER zu einem Syntax-Fehler. Regulaere Ausdruecke lassen sich nur gegen den
    gesamten Header-Block pruefen ("in headers", siehe fdm.conf(5)). Um trotzdem gezielt
    eine Kopfzeile zu treffen, wird ihr Name als Zeilenanfang-Anker vorangestellt - fdm
    compiliert Regexe mit REG_NEWLINE, wodurch "^"/"$" bei jeder Zeile im Block greifen,
    nicht nur am Anfang/Ende des gesamten Blocks.
    """
    header = header_name_for_rule(rule)
    match_type = rule.get("match_type")
    value = rule.get("value", "")
    value_pattern = value if match_type == "regex" else re.escape(value)
    prefix = f"^{re.escape(header)}:"
    if match_type == "exact":
        # [[:space:]] statt \s/\t: fdm entwertet Backslash-Escapes wie \t beim
        # Einlesen des Strings, bevor der Rest ueberhaupt an regcomp geht - die
        # POSIX-Zeichenklasse kommt ganz ohne Backslash aus und ist eindeutig.
        return f"{prefix}[[:space:]]*{value_pattern}$"
    # "contains" (Standard) und "regex"
    return f"{prefix}.*{value_pattern}"


def _dest_name_for_rule(rule, actions_by_id):
    dest_action = actions_by_id.get(rule.get("dest_action_id"))
    dest_folder = rule.get("dest_folder")
    if not dest_action or not dest_folder:
        return None
    if dest_folder not in (dest_action.get("dest_folders") or []):
        return None
    return action_variant_name(dest_action, dest_folder)


def generate_conf(config):
    accounts = config.get("accounts", [])
    actions = config.get("actions", [])
    rules = config.get("rules", [])

    accounts_by_id = {a["id"]: a for a in accounts}
    actions_by_id = {a["id"]: a for a in actions}

    lines = []

    # --- Quell-Konten: ein fdm-Account pro (Konto, Ordner) ---
    lines.append("# --- ACCOUNTS ---")
    if not accounts:
        lines.append("# (keine Quell-Konten konfiguriert)")
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

    # --- Ziel-Server: eine fdm-Action pro (Ziel-Server, Ordner) ---
    lines.append("# --- ACTIONS ---")
    has_actions = False
    if not actions:
        lines.append("# (keine Ziel-Server konfiguriert)")
    for act in actions:
        for folder in act.get("dest_folders") or []:
            has_actions = True
            lines.append(
                f'action {_q(action_variant_name(act, folder))} {act["type"]} '
                f'server {_q(act["server"])} port {act["port"]} '
                f'user {_q(act["user"])} pass {_q(act["pass"])} '
                f'folder {_q(folder)}'
            )
    if actions and not has_actions:
        lines.append("# (kein Ziel-Server hat einen Ordner konfiguriert)")
    lines.append("")

    # --- Regeln: IMMER Ausnahmeregeln -> Ordner-Zuordnungen -> Catch-All,
    #     unabhaengig von der Reihenfolge im gespeicherten Datenmodell ---
    lines.append("# --- RULES ---")
    exception_rules = [r for r in rules if r.get("field") in ("from", "subject", "header")]
    mapping_rules = [r for r in rules if r.get("field") == "source"]
    catchall_rules = [r for r in rules if r.get("field") == "all"]

    if not exception_rules and not mapping_rules and not catchall_rules:
        lines.append("# (keine Regeln konfiguriert)")

    if exception_rules:
        lines.append("# Ausnahmeregeln (greifen zuerst)")
    for rule in exception_rules:
        dest_name = _dest_name_for_rule(rule, actions_by_id)
        if not dest_name:
            continue
        pattern = header_match_pattern(rule)
        lines.append(
            f'match {_q(pattern)} in headers action {_q(dest_name)}'
        )

    if mapping_rules:
        lines.append("")
        lines.append("# Ordner-Zuordnungen")
    for rule in mapping_rules:
        dest_name = _dest_name_for_rule(rule, actions_by_id)
        source_account = accounts_by_id.get(rule.get("source_account_id"))
        folder = rule.get("source_folder")
        if not dest_name or not source_account or not folder:
            continue
        variant_name = account_variant_name(source_account, folder)
        pattern = escape_glob(variant_name)
        lines.append(f'match account {_q(pattern)} action {_q(dest_name)}')

    for rule in catchall_rules:
        dest_name = _dest_name_for_rule(rule, actions_by_id)
        if not dest_name:
            continue
        lines.append("")
        lines.append("# Fallback Rule")
        lines.append(f'match all action {_q(dest_name)}')

    lines.append("")
    return "\n".join(lines)


def validate_config(config):
    """Einfache Konsistenzpruefung; gibt Liste von Warnungen zurueck."""
    warnings = []
    accounts = config.get("accounts", [])
    actions = config.get("actions", [])
    rules = config.get("rules", [])

    account_names = [a["name"] for a in accounts]
    if len(account_names) != len(set(account_names)):
        warnings.append("Es gibt Quell-Konten mit doppeltem Namen.")

    action_names = [a["name"] for a in actions]
    if len(action_names) != len(set(action_names)):
        warnings.append("Es gibt Ziel-Server mit doppeltem Namen.")

    accounts_by_id = {a["id"]: a for a in accounts}
    actions_by_id = {a["id"]: a for a in actions}

    for action in actions:
        if not action.get("dest_folders"):
            warnings.append(f'Ziel-Server "{action["name"]}" hat keinen Ziel-Ordner konfiguriert.')

    for rule in rules:
        dest_action = actions_by_id.get(rule.get("dest_action_id"))
        if not dest_action:
            warnings.append("Eine Regel verweist auf einen nicht existierenden Ziel-Server.")
        elif rule.get("dest_folder") not in (dest_action.get("dest_folders") or []):
            warnings.append(
                f'Eine Regel verweist auf den Ziel-Ordner "{rule.get("dest_folder")}", der bei '
                f'"{dest_action["name"]}" nicht mehr konfiguriert ist.'
            )

        if rule.get("field") == "header" and not rule.get("header_name", "").strip():
            warnings.append("Eine Ausnahmeregel hat keinen Headernamen gesetzt.")

        if rule.get("field") == "source":
            source_account = accounts_by_id.get(rule.get("source_account_id"))
            folder = rule.get("source_folder")
            if not source_account:
                warnings.append("Eine Ordner-Zuordnung verweist auf ein nicht existierendes Quell-Konto.")
            elif folder not in (source_account.get("source_folders") or []):
                warnings.append(
                    f'Eine Ordner-Zuordnung verweist auf den Quell-Ordner "{folder}", der bei '
                    f'"{source_account["name"]}" nicht mehr konfiguriert ist.'
                )

    catchalls = [r for r in rules if r.get("field") == "all"]
    if len(catchalls) > 1:
        warnings.append("Es gibt mehr als eine Catch-All-Regel.")
    if not catchalls and rules:
        warnings.append("Keine Catch-All-Regel vorhanden (optional, aber empfohlen).")

    return warnings
