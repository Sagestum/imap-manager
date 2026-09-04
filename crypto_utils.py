"""Verschluesselung der in config.json abgelegten IMAP-Passwoerter (at rest).

Der Schluessel kommt aus der Umgebungsvariable FDM_SECRET_KEY (getrennt vom Config-Volume
gehalten, z.B. via .env neben der docker-compose.yml) und bleibt ueber Neustarts stabil - ohne
ihn lassen sich bereits verschluesselte Passwoerter nicht mehr entschluesseln.
"""
import os

from cryptography.fernet import Fernet, InvalidToken

_KEY_ENV = "FDM_SECRET_KEY"


def _fernet():
    key = os.environ.get(_KEY_ENV)
    if not key:
        raise RuntimeError(
            f"{_KEY_ENV} ist nicht gesetzt - wird zum Ver-/Entschluesseln der IMAP-Passwoerter "
            "in config.json benoetigt. Mit 'python3 -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"' einen Schluessel erzeugen und z.B. als "
            f"{_KEY_ENV} in einer .env neben der docker-compose.yml hinterlegen."
        )
    return Fernet(key.encode())


def encrypt(plaintext):
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_maybe(value):
    """Entschluesselt einen Fernet-Token. Ist `value` (noch) kein gueltiger Token - z.B. eine
    Alt-Konfiguration von vor der Verschluesselungs-Umstellung - wird der Wert unveraendert als
    Klartext zurueckgegeben; das naechste save_config() verschluesselt ihn dann automatisch."""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError):
        return value
