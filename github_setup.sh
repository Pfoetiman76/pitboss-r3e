#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
command -v git >/dev/null || { echo "[FEHLER] git fehlt: https://git-scm.com/downloads"; exit 1; }
command -v gh  >/dev/null || { echo "[FEHLER] GitHub CLI fehlt: https://cli.github.com/"; exit 1; }
gh auth status >/dev/null 2>&1 || gh auth login
[ -d .git ] || git init
git config user.name  >/dev/null 2>&1 || git config user.name  "Pfoetiman76"
git config user.email >/dev/null 2>&1 || git config user.email "Pfoetiman76@users.noreply.github.com"
git branch -M main
git add -A
git commit -m "PitBoss R3E 0.1.1" || true
git rev-parse HEAD >/dev/null 2>&1 || { echo "[FEHLER] Kein Commit - git-Identitaet pruefen."; exit 1; }
gh repo view Pfoetiman76/pitboss-r3e >/dev/null 2>&1 || gh repo create pitboss-r3e --public --disable-wiki
git remote get-url origin >/dev/null 2>&1 || git remote add origin https://github.com/Pfoetiman76/pitboss-r3e.git
git push -u origin main
git tag v0.1.1 2>/dev/null || true
git push origin v0.1.1
echo "Fertig. Actions: https://github.com/Pfoetiman76/pitboss-r3e/actions"
