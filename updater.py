"""
PitBoss — Update-Pruefung ueber GitHub Releases  (additiv, 0.4.7.5)
================================================================================

Fragt die GitHub-Releases-API des Projekts nach dem neuesten Release und
vergleicht dessen Tag (z.B. v0.4.7.6) mit der installierten Version. Kein Token
noetig (oeffentliches Repo, 60 Anfragen/Stunde unauthentifiziert reichen fuer
manuelle Pruefungen).

EINMALIG SETZEN: GITHUB_REPO auf dein "benutzer/repo" aendern.
"""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error

# >>> EINMALIG anpassen: dein GitHub-Repo als "benutzer/repo" <<<
GITHUB_REPO = "Pfoetiman76/pitboss-r3e"

_API = "https://api.github.com/repos/{repo}/releases/latest"


def _ver(s: str) -> tuple:
    """'v0.4.7.6 Beta' -> (0,4,7,6). Robust gegen Suffixe/Praefixe."""
    nums = re.findall(r"\d+", s or "")
    return tuple(int(n) for n in nums[:4]) if nums else (0,)


def check_for_update(current_version: str, repo: str | None = None, timeout: int = 8) -> dict | None:
    """Gibt Info-Dict zurueck, wenn ein neueres Release existiert, sonst None.
    Wirft bei Netz-/Konfigurationsfehlern eine Exception (vom Aufrufer zu fangen)."""
    repo = repo or GITHUB_REPO
    if "DEIN-" in repo or "/" not in repo:
        raise ValueError("GITHUB_REPO in updater.py ist noch nicht gesetzt (benutzer/repo).")
    req = urllib.request.Request(
        _API.format(repo=repo),
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "PitBoss-R3E-Updater"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tag = data.get("tag_name", "") or ""
    if _ver(tag) <= _ver(current_version):
        return None
    asset_url = ""
    for a in data.get("assets", []) or []:
        name = (a.get("name") or "").lower()
        if name.endswith(".exe") or "setup" in name:
            asset_url = a.get("browser_download_url", "") or ""
            break
    return {
        "version": tag.lstrip("vV"),
        "url": data.get("html_url", "") or f"https://github.com/{repo}/releases/latest",
        "asset_url": asset_url,
        "notes": (data.get("body", "") or "").strip(),
    }


def download_asset(url: str, dest_path: str, progress_cb=None, timeout: int = 30) -> str:
    """Laedt eine Release-Asset-Datei (z.B. den Installer) nach dest_path.
    progress_cb(done_bytes, total_bytes) wird waehrend des Downloads aufgerufen.
    Reine stdlib, kein Zusatzpaket. Gibt den Zielpfad zurueck; wirft bei Fehlern."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "PitBoss-R3E-Updater",
                      "Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb is not None:
                    try:
                        progress_cb(done, total)
                    except Exception:
                        pass
    return dest_path


if __name__ == "__main__":
    import sys
    cur = sys.argv[1] if len(sys.argv) > 1 else "0.0.0"
    repo = sys.argv[2] if len(sys.argv) > 2 else None
    try:
        info = check_for_update(cur, repo=repo)
        print("Update:", info if info else "keins (aktuell)")
    except Exception as e:
        print("Fehler:", e)
