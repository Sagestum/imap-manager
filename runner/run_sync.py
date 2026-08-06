#!/usr/bin/env python3
"""Fuehrt einen sync_plan.json einmal aus - ein imapsync-Aufruf pro Ordner-Zuordnung.

Nutzt imapsync_gen.build_invocation() - denselben Code, der auch die Vorschau im Web-UI baut,
damit es keine zweite, potenziell abweichende Implementierung der Argv-Konstruktion gibt.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import imapsync_gen  # noqa: E402


def write_passfile(directory, name, password):
    path = directory / name
    path.write_text(password + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def run_mapping(mapping, passfile_dir, cache_dir):
    acc = mapping["source_account"]
    act = mapping["dest_action"]
    label = f'{acc["name"]}::{mapping["source_folder"]} -> {act["name"]}::{mapping["dest_folder"]}'

    passfile1 = write_passfile(passfile_dir, "pf1", acc["pass"])
    passfile2 = write_passfile(passfile_dir, "pf2", act["pass"])
    try:
        args = imapsync_gen.build_invocation(
            mapping,
            imapsync_gen.passfile_auth(1, passfile1),
            imapsync_gen.passfile_auth(2, passfile2),
            cache_dir,
        )
        print(f"--- {label} ---", flush=True)
        result = subprocess.run(["imapsync", *args])
        if result.returncode != 0:
            print(f'  Fehler bei "{label}" (siehe Ausgabe oben).', flush=True)
            return False
        return True
    finally:
        passfile1.unlink(missing_ok=True)
        passfile2.unlink(missing_ok=True)


def main():
    if len(sys.argv) != 2:
        print("Usage: run_sync.py <sync_plan.json>", file=sys.stderr)
        return 1

    plan_path = Path(sys.argv[1])
    if not plan_path.exists():
        print(f"Kein sync_plan.json unter {plan_path} gefunden, ueberspringe Lauf.", flush=True)
        return 0

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not plan:
        print("Keine Ordner-Zuordnungen in sync_plan.json gefunden.", flush=True)
        return 0

    cache_dir = plan_path.parent / "imapsync_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    passfile_dir = Path(tempfile.mkdtemp(prefix="imapsync-auth-"))
    os.chmod(passfile_dir, 0o700)
    try:
        for mapping in plan:
            run_mapping(mapping, passfile_dir, cache_dir)
    finally:
        shutil.rmtree(passfile_dir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
