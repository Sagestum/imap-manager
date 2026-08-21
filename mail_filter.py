"""Post-Sync-Filter: verschiebt Mails im Zielordner anhand von Absender/Betreff-Mustern.

imapsync selbst kennt kein Content-Routing (reiner Ordner-zu-Ordner-Batch-Mirror) - dieser Schritt
laeuft daher NACH allen imapsync-Aufrufen auf dem bereits synchronisierten Zielordner, per
Standard-IMAP SEARCH/MOVE. Literale Substring-Suche (kein fnmatch/Glob wie beim alten
fdm-"match header"-Bug), IMAP-SEARCH ist laut RFC 3501 case-insensitiv.

Verarbeitet inkrementell ueber einen High-Water-Mark (UIDVALIDITY + letzte gesehene UID) pro
(Ziel-Server, beobachteter Ordner), gespeichert in stats_store.filter_state - sonst wuerde jeder
Lauf den kompletten Ordner erneut absuchen.
"""
import imaplib
import re

import stats_store

IMAP_HEADER_NAME = {"from": "FROM", "subject": "SUBJECT"}


def _connect_imap(conn_type, server, port):
    if conn_type == "imaps":
        return imaplib.IMAP4_SSL(server, port, timeout=30)
    conn = imaplib.IMAP4(server, port, timeout=30)
    try:
        conn.starttls()
    except imaplib.IMAP4.error:
        pass  # Server bietet kein STARTTLS an, weiter mit Klartextverbindung
    return conn


def _quote(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


_STATUS_UIDVALIDITY_RE = re.compile(r"UIDVALIDITY\s+(\d+)")
_STATUS_UIDNEXT_RE = re.compile(r"UIDNEXT\s+(\d+)")


def _folder_status(conn, folder):
    typ, data = conn.status(_quote(folder), "(UIDVALIDITY UIDNEXT)")
    if typ != "OK" or not data or data[0] is None:
        raise RuntimeError(f"IMAP STATUS fuer Ordner {folder!r} fehlgeschlagen: {data}")
    text = data[0].decode("utf-8", errors="replace") if isinstance(data[0], bytes) else data[0]
    uidvalidity_match = _STATUS_UIDVALIDITY_RE.search(text)
    uidnext_match = _STATUS_UIDNEXT_RE.search(text)
    if not uidvalidity_match or not uidnext_match:
        raise RuntimeError(f"Unerwartete STATUS-Antwort fuer Ordner {folder!r}: {text!r}")
    return int(uidvalidity_match.group(1)), int(uidnext_match.group(1))


def _search_uids(conn, header, match, uid_start, uid_end):
    header_name = IMAP_HEADER_NAME[header]
    typ, data = conn.uid(
        "SEARCH", "UID", f"{uid_start}:{uid_end}", "HEADER", header_name, _quote(match),
    )
    if typ != "OK":
        raise RuntimeError(f"IMAP SEARCH fehlgeschlagen: {data}")
    if not data or not data[0]:
        return []
    return data[0].split()


def _move_uids(conn, uids, target_folder, has_move):
    uid_set = b",".join(uids).decode("ascii")
    if has_move:
        typ, data = conn.uid("MOVE", uid_set, _quote(target_folder))
        if typ != "OK":
            raise RuntimeError(f"IMAP MOVE fehlgeschlagen: {data}")
        return

    typ, data = conn.uid("COPY", uid_set, _quote(target_folder))
    if typ != "OK":
        raise RuntimeError(f"IMAP COPY fehlgeschlagen: {data}")
    typ, data = conn.uid("STORE", uid_set, "+FLAGS", r"(\Deleted)")
    if typ != "OK":
        raise RuntimeError(f"IMAP STORE (Deleted) fehlgeschlagen: {data}")
    conn.expunge()


def _process_folder(action_name, watch_folder, account, folder_filters, db_path):
    conn = _connect_imap(account["type"], account["server"], account["port"])
    try:
        conn.login(account["user"], account["pass"])

        typ, cap_data = conn.capability()
        has_move = typ == "OK" and any(
            b"MOVE" in (line or b"") for line in cap_data
        )

        uidvalidity, uidnext = _folder_status(conn, watch_folder)
        stored_uidvalidity, stored_last_uid = stats_store.get_filter_state(
            action_name, watch_folder, db_path
        )
        last_uid = stored_last_uid if stored_uidvalidity == uidvalidity else 0

        uid_end = uidnext - 1
        uid_start = last_uid + 1
        if uid_start > uid_end:
            print(f'  Filter "{action_name}::{watch_folder}": keine neuen Mails.', flush=True)
            return

        typ, _sel = conn.select(_quote(watch_folder))
        if typ != "OK":
            raise RuntimeError(f'Ordner "{watch_folder}" konnte nicht selektiert werden.')

        for flt in folder_filters:
            uids = _search_uids(conn, flt["header"], flt["match"], uid_start, uid_end)
            label = f'{action_name}::{watch_folder} [{flt["header"]}~"{flt["match"]}"] -> {flt["target_folder"]}'
            if not uids:
                print(f'  Filter "{label}": keine Treffer.', flush=True)
                continue
            _move_uids(conn, uids, flt["target_folder"], has_move)
            print(f'  Filter "{label}": {len(uids)} Mail(s) verschoben.', flush=True)

        stats_store.set_filter_state(action_name, watch_folder, uidvalidity, uid_end, db_path)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def run_filters(filters, db_path):
    """filters: Liste von {dest_action: {name,type,server,port,user,pass}, watch_folder, header,
    match, target_folder} - Format siehe app.py:_serialize_filter()."""
    if not filters:
        return

    grouped = {}
    for flt in filters:
        account = flt["dest_action"]
        key = (account["name"], flt["watch_folder"])
        grouped.setdefault(key, {"account": account, "filters": []})["filters"].append(flt)

    for (action_name, watch_folder), group in grouped.items():
        try:
            _process_folder(action_name, watch_folder, group["account"], group["filters"], db_path)
        except Exception as exc:
            print(f'  Fehler beim Filtern von "{action_name}::{watch_folder}": {exc}', flush=True)
