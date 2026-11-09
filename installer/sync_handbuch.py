#!/usr/bin/env python3
"""Haelt die Versionszeile im BENUTZERHANDBUCH automatisch aktuell.

Liest APP_VERSION aus main.py und setzt sie zwischen die AUTO:VERSION-Marken
in BENUTZERHANDBUCH.md. Wird vom Workflow "Handbuch aktuell halten" nach
jedem Push auf den Hauptzweig ausgefuehrt; der Workflow committet nur, wenn
sich etwas aendert.

Aufruf: python installer/sync_handbuch.py
Rueckgabecode 0 = Handbuch aktualisiert (oder bereits aktuell),
              1 = Fehler (z. B. Marken nicht gefunden).
"""
from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUAL = ROOT / "BENUTZERHANDBUCH.md"
START = "<!-- AUTO:VERSION:start -->"
END = "<!-- AUTO:VERSION:end -->"


def _app_version() -> str:
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', src, re.MULTILINE)
    if not m:
        raise RuntimeError("APP_VERSION nicht in main.py gefunden")
    return m.group(1)


def main() -> int:
    version = _app_version()
    text = MANUAL.read_text(encoding="utf-8")
    if START not in text or END not in text:
        print("BENUTZERHANDBUCH.md: AUTO:VERSION-Marken fehlen", file=sys.stderr)
        return 1
    stand = _dt.date.today().isoformat()
    block = (
        f"{START}\n"
        f"Dieses Handbuch beschreibt **PitBoss R3E {version}** "
        f"(Stand: {stand}, siehe [Releases](https://github.com/Pfoetiman76/pitboss-r3e/releases)).\n"
        f"{END}"
    )
    new = re.sub(re.escape(START) + r".*?" + re.escape(END),
                 lambda _m: block, text, count=1, flags=re.DOTALL)
    if new != text:
        MANUAL.write_text(new, encoding="utf-8")
        print(f"Handbuch aktualisiert: Version {version}, Stand {stand}")
    else:
        print(f"Handbuch bereits aktuell ({version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
