"""Loest Ordner-Zuordnungen zu imapsync-Aufrufen auf (ersetzt die alte fdm.conf-Text-DSL).

Statt eine Text-Config zu generieren, die ein Fremdprogramm neu parst (Fehlerquelle der
fdm-Variante), baut dieses Modul direkt argv-Listen fuer "imapsync" - kein Shell-String, keine
Quoting-/Escaping-Fragen.
"""

IMAP_ACCOUNT_TYPES = {"imap", "imaps"}


def _ssl_flags(prefix, account_type):
    """--sslN/--nosslN je nach imap/imaps. account_type ist bereits validiert (imap/imaps)."""
    return [f"--ssl{prefix}"] if account_type == "imaps" else [f"--nossl{prefix}"]


def _is_gmail(server):
    return "gmail.com" in (server or "").lower()


def resolve_mappings(config):
    """Loest fuer jeden konfigurierten Quell-Ordner die effektive Zuordnung auf.

    Reihenfolge wie bisher bei fdm: explizite Ordner-Zuordnung schlaegt Catch-All, kein Treffer
    heisst der Ordner wird schlicht nicht synchronisiert (kein Fehler). POP3/POP3S-Konten werden
    uebersprungen (imapsync kann nur IMAP<->IMAP) - die dazugehoerige Warnung liefert
    validate_config(), hier wird nur gefiltert.

    Gibt eine Liste von dicts zurueck: {source_account, source_folder, dest_action, dest_folder}
    """
    accounts = config.get("accounts", [])
    actions = config.get("actions", [])
    rules = config.get("rules", [])

    actions_by_id = {a["id"]: a for a in actions}

    source_rules_by_key = {}
    for r in rules:
        if r.get("field") != "source":
            continue
        key = (r.get("source_account_id"), r.get("source_folder"))
        source_rules_by_key[key] = r

    catchall_rule = next((r for r in rules if r.get("field") == "all"), None)

    def _dest_for_rule(rule):
        if not rule:
            return None, None
        dest_action = actions_by_id.get(rule.get("dest_action_id"))
        dest_folder = rule.get("dest_folder")
        if not dest_action or not dest_folder:
            return None, None
        if dest_folder not in (dest_action.get("dest_folders") or []):
            return None, None
        return dest_action, dest_folder

    mappings = []
    for acc in accounts:
        folders = acc.get("source_folders") or []
        if not folders:
            continue
        if acc["type"] not in IMAP_ACCOUNT_TYPES:
            continue
        for folder in folders:
            rule = source_rules_by_key.get((acc["id"], folder))
            dest_action, dest_folder = _dest_for_rule(rule)
            if not dest_action:
                dest_action, dest_folder = _dest_for_rule(catchall_rule)
            if not dest_action:
                continue
            mappings.append({
                "source_account": acc,
                "source_folder": folder,
                "dest_action": dest_action,
                "dest_folder": dest_folder,
            })

    return mappings


def passfile_auth(prefix, passfile_path):
    """Auth-Argumente fuer den Echtlauf: Passwort kommt aus einer Datei, nicht aus argv (argv ist
    ueber "ps aux" fuer jeden lokalen Nutzer einsehbar, eine Passfile mit chmod 600 nicht)."""
    return [f"--passfile{prefix}", str(passfile_path)]


def literal_auth(prefix, password):
    """Auth-Argumente fuer die Vorschau im Web-UI: Klartext-Passwort direkt im argv, wie es die
    bisherige fdm.conf-Vorschau auch schon anzeigte (keine Verhaltensaenderung an dieser Stelle)."""
    return [f"--password{prefix}", password]


def build_invocation(mapping, auth1, auth2, cache_dir):
    """Baut die imapsync-argv-Liste (ohne führendes "imapsync") fuer ein Mapping.

    auth1/auth2: je eine bereits fertige Argument-Liste, siehe passfile_auth()/literal_auth() -
    so nutzen Vorschau (Web-UI) und Echtlauf (Runner) denselben Code fuer den ganzen Rest der
    Argv-Konstruktion und koennen trotzdem unterschiedlich mit dem Passwort umgehen.
    """
    acc = mapping["source_account"]
    act = mapping["dest_action"]
    source_folder = mapping["source_folder"]
    dest_folder = mapping["dest_folder"]

    args = [
        "--host1", acc["server"], "--port1", str(acc["port"]), "--user1", acc["user"],
        *auth1,
        *_ssl_flags(1, acc["type"]),
        "--host2", act["server"], "--port2", str(act["port"]), "--user2", act["user"],
        *auth2,
        *_ssl_flags(2, act["type"]),
        "--folder", source_folder,
        "--f1f2", f"{source_folder}={dest_folder}",
        "--delete1",
        "--syncinternaldates",
        "--tmpdir", str(cache_dir),
    ]
    if _is_gmail(acc["server"]):
        args.append("--gmail1")
    if _is_gmail(act["server"]):
        args.append("--gmail2")
    return args


def preview_lines(config):
    """Menschenlesbare Vorschau der geplanten imapsync-Aufrufe (Klartext-Passwoerter wie bisher
    bei der fdm.conf-Vorschau - keine Verhaltensaenderung an dieser Stelle)."""
    mappings = resolve_mappings(config)
    lines = []
    if not mappings:
        lines.append("# (keine Ordner-Zuordnungen mit gueltigem Ziel konfiguriert)")
    for m in mappings:
        auth1 = literal_auth(1, m["source_account"]["pass"])
        auth2 = literal_auth(2, m["dest_action"]["pass"])
        args = build_invocation(m, auth1, auth2, "<cache-dir>")
        lines.append("imapsync " + " ".join(f'"{a}"' if " " in a else a for a in args))
    return lines, mappings


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

    for acc in accounts:
        if acc["type"] not in IMAP_ACCOUNT_TYPES and acc.get("source_folders"):
            warnings.append(
                f'Konto "{acc["name"]}" ist {acc["type"]} - imapsync unterstuetzt nur '
                f'IMAP/IMAPS als Quelle, es wird beim Sync uebersprungen.'
            )

    for rule in rules:
        if rule.get("field") not in ("source", "all"):
            continue
        dest_action = actions_by_id.get(rule.get("dest_action_id"))
        if not dest_action:
            warnings.append("Eine Regel verweist auf einen nicht existierenden Ziel-Server.")
        elif rule.get("dest_folder") not in (dest_action.get("dest_folders") or []):
            warnings.append(
                f'Eine Regel verweist auf den Ziel-Ordner "{rule.get("dest_folder")}", der bei '
                f'"{dest_action["name"]}" nicht mehr konfiguriert ist.'
            )

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
