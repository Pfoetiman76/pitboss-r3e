"""PitBoss R3E - optionale KI-Anbieter fuer den Live-Coach (0.2.1).

Der Live-Coach arbeitet immer lokal. Ist ein Anbieter eingerichtet, formuliert die KI
den Hinweis nach der Runde zu EINEM kurzen Boxenfunk-Satz um. Faellt der Aufruf aus
(kein Netz, Key ungueltig, Limit, Timeout), bleibt der lokale Satz - der Coach schweigt
also nie wegen eines Netzproblems.

Gesendet werden ausschliesslich: Rundennummer, Delta in Sekunden und der Hinweistext der
lokalen Analyse (z. B. "250-300 m +0.21s - Bremsen spaeter"). Keine Telemetrie-Rohdaten,
keine Namen, keine Pfade.

Nur Standardbibliothek (urllib), kein SDK. Anbieter: OpenAI (ChatGPT), Mistral,
Google Gemini, Anthropic Claude, DeepSeek.
"""
import base64
import json
import os
import re
import socket
import urllib.error
import urllib.request

USER_AGENT = "PitBossR3E/0.2.1"
TIMEOUT_S = 12.0

# id -> Metadaten. kind bestimmt Request-/Response-Format.
PROVIDERS = {
    "openai": {
        "label": "ChatGPT (OpenAI)",
        "kind": "openai",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
        "models": ["gpt-4o-mini", "gpt-4.1-mini", "gpt-5-mini"],
        "key_url": "https://platform.openai.com/api-keys",
    },
    "mistral": {
        "label": "Mistral",
        "kind": "chat",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "model": "mistral-small-latest",
        "models": ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"],
        "key_url": "https://console.mistral.ai/api-keys",
    },
    "gemini": {
        "label": "Gemini (Google)",
        "kind": "gemini",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "model": "gemini-flash-latest",
        "models": ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash"],
        "key_url": "https://aistudio.google.com/apikey",
    },
    "claude": {
        "label": "Claude (Anthropic)",
        "kind": "anthropic",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "model": "claude-haiku-5-5",
        "models": ["claude-haiku-5-5", "claude-sonnet-5-5"],
        "key_url": "https://console.anthropic.com/settings/keys",
    },
    "deepseek": {
        "label": "DeepSeek",
        "kind": "chat",
        "endpoint": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat",
        "models": ["deepseek-chat"],
        "key_url": "https://platform.deepseek.com/api_keys",
    },
}
LOCAL_ID = "local"
LOCAL_LABEL = "Lokal (ohne KI)"


class AIError(Exception):
    """Lesbarer Fehler fuer Log/Einstellungen (Deutsch, ohne Key)."""


# ---------------------------------------------------------------- Prompt ----
SYSTEM_PROMPT = (
    "Du bist ein erfahrener Renningenieur im Boxenfunk und coachst einen Sim-Racing-Fahrer. "
    "Antworte mit GENAU EINEM kurzen deutschen Satz im Imperativ, hoechstens 14 Woerter. "
    "Nutze nur die gegebenen Fakten, erfinde keine Kurven, Zahlen oder Ursachen. "
    "Kein Markdown, keine Anfuehrungszeichen, keine Anrede, keine Erklaerung."
)


def build_prompt(facts):
    """facts: {'lap': int, 'delta_s': float|None, 'hint': str, 'local': str}"""
    parts = [f"Runde {facts.get('lap')} beendet."]
    d = facts.get("delta_s")
    if d is not None:
        parts.append(f"Delta zur Referenz am Rundenende: {d:+.2f} s "
                     f"({'schneller' if d < 0 else 'langsamer'}).")
    hint = (facts.get("hint") or "").strip()
    if hint:
        parts.append(f"Groesster Zeitverlust laut Analyse: {hint}")
    parts.append("Formuliere daraus den Funkspruch fuer die naechste Runde.")
    return "\n".join(parts)


def clean_reply(text):
    """Macht aus der Modellantwort einen sprechbaren Satz oder None (-> lokaler Fallback)."""
    if not text:
        return None
    lines = [l.strip() for l in str(text).replace("\r", "\n").split("\n") if l.strip()]
    if not lines:
        return None
    t = lines[0]
    t = re.sub(r"^(renningenieur|engineer|funk|boxenfunk)\s*[:\-]\s*", "", t, flags=re.I)
    t = t.strip(" \t\"'`*_#>„“”‚‘’»«")
    t = re.sub(r"\s+", " ", t)
    if not t:
        return None
    if len(t.split()) > 22 or len(t) > 170:
        # erster Satz, falls das Modell trotzdem ausschweift
        m = re.match(r"(.+?[.!?])(\s|$)", t)
        t = m.group(1) if m else ""
        if not t or len(t.split()) > 22:
            return None
    return t


# --------------------------------------------------------------- Requests ---
def _body(kind, model, system, prompt, level):
    """level 0 = volle Parameter, hoeher = zunehmend minimal (bei HTTP 400 naechster Versuch)."""
    if kind == "openai":
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        if level == 0:
            return {"model": model, "messages": msgs, "temperature": 0.4,
                    "max_completion_tokens": 400}
        if level == 1:   # reine Reasoning-Modelle erlauben keine Temperatur
            return {"model": model, "messages": msgs, "max_completion_tokens": 400}
        return {"model": model, "messages": msgs, "max_tokens": 120}
    if kind == "chat":   # Mistral, DeepSeek
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        if level == 0:
            return {"model": model, "messages": msgs, "temperature": 0.4, "max_tokens": 120}
        return {"model": model, "messages": msgs}
    if kind == "gemini":
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if level == 0:   # Denkphase aus -> kurze Latenz
            body["generationConfig"] = {"temperature": 0.4, "maxOutputTokens": 200,
                                        "thinkingConfig": {"thinkingBudget": 0}}
        else:
            body["generationConfig"] = {"maxOutputTokens": 1024}
        return body
    if kind == "anthropic":
        body = {"model": model, "max_tokens": 120, "system": system,
                "messages": [{"role": "user", "content": prompt}]}
        if level == 0:
            body["temperature"] = 0.4
        return body
    raise AIError("Unbekannter Anbieter-Typ.")


_MAX_LEVEL = {"openai": 2, "chat": 1, "gemini": 1, "anthropic": 1}


def _headers(kind, key):
    h = {"Content-Type": "application/json", "Accept": "application/json",
         "User-Agent": USER_AGENT}
    if kind == "gemini":
        h["x-goog-api-key"] = key
    elif kind == "anthropic":
        h["x-api-key"] = key
        h["anthropic-version"] = "2023-06-01"
    else:
        h["Authorization"] = "Bearer " + key
    return h


def _err_message(raw):
    try:
        obj = json.loads(raw)
        e = obj.get("error", obj) if isinstance(obj, dict) else obj
        if isinstance(e, dict):
            return str(e.get("message") or e.get("status") or e)[:200]
        return str(e)[:200]
    except Exception:
        return (raw or "").strip()[:200]


def _redact(text, key):
    if key and key in text:
        text = text.replace(key, "***")
    return text


def _post(url, headers, body, timeout):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _extract(kind, obj):
    """Gibt (text, abgeschnitten) zurueck."""
    if kind in ("openai", "chat"):
        ch = (obj.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):   # selten: Teilobjekte
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return (content or ""), ch.get("finish_reason") == "length"
    if kind == "gemini":
        fb = obj.get("promptFeedback") or {}
        if fb.get("blockReason"):
            raise AIError(f"Anfrage von Gemini blockiert ({fb['blockReason']}).")
        cand = (obj.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        txt = "".join(p.get("text", "") for p in parts
                      if isinstance(p, dict) and not p.get("thought"))
        return txt, cand.get("finishReason") == "MAX_TOKENS"
    if kind == "anthropic":
        txt = "".join(b.get("text", "") for b in (obj.get("content") or [])
                      if isinstance(b, dict) and b.get("type") == "text")
        return txt, obj.get("stop_reason") == "max_tokens"
    return "", False


def ask(provider_id, key, model, system, prompt, timeout=TIMEOUT_S, endpoint=None):
    """Eine Anfrage an den Anbieter. Gibt den Rohtext zurueck oder wirft AIError."""
    spec = PROVIDERS.get(provider_id)
    if spec is None:
        raise AIError("Kein KI-Anbieter gewaehlt.")
    key = (key or "").strip()
    if not key:
        raise AIError(f"Kein API-Key fuer {spec['label']} hinterlegt.")
    model = (model or spec["model"]).strip()
    kind = spec["kind"]
    url = (endpoint or spec["endpoint"]).replace("{model}", model)
    headers = _headers(kind, key)

    level = 0
    while True:
        body = _body(kind, model, system, prompt, level)
        try:
            obj = _post(url, headers, body, timeout)
            break
        except urllib.error.HTTPError as e:
            try:
                raw = e.read().decode("utf-8", "replace")
            except Exception:
                raw = ""
            msg = _redact(_err_message(raw), key)
            if e.code in (400, 422) and level < _MAX_LEVEL[kind]:
                level += 1       # Parameter nicht akzeptiert -> abgespeckt erneut
                continue
            if e.code in (401, 403):
                raise AIError(f"{spec['label']}: API-Key ungueltig oder ohne Berechtigung. {msg}")
            if e.code == 402:
                raise AIError(f"{spec['label']}: Guthaben aufgebraucht. {msg}")
            if e.code == 404:
                raise AIError(f"{spec['label']}: Modell '{model}' nicht gefunden. {msg}")
            if e.code == 429:
                raise AIError(f"{spec['label']}: Limit/Kontingent erreicht. {msg}")
            if e.code >= 500:
                raise AIError(f"{spec['label']}: Server gerade gestoert (HTTP {e.code}).")
            raise AIError(f"{spec['label']}: HTTP {e.code}. {msg}")
        except (socket.timeout, TimeoutError):
            raise AIError(f"{spec['label']}: Zeitueberschreitung nach {timeout:g} s.")
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise AIError(f"{spec['label']}: Zeitueberschreitung nach {timeout:g} s.")
            raise AIError(f"{spec['label']}: keine Verbindung ({_redact(str(reason), key)[:120]}).")
        except (ValueError, json.JSONDecodeError):
            raise AIError(f"{spec['label']}: unlesbare Antwort.")
        except OSError as e:
            raise AIError(f"{spec['label']}: Netzwerkfehler ({_redact(str(e), key)[:120]}).")

    text, truncated = _extract(kind, obj)
    if not (text or "").strip():
        if truncated:
            raise AIError(f"{spec['label']}: Antwort leer (Token-Limit, Modell denkt zu lange) "
                          f"- ein schnelleres Modell waehlen.")
        raise AIError(f"{spec['label']}: leere Antwort.")
    return text


def coach_line(cfg, facts, endpoint=None, timeout=TIMEOUT_S):
    """Hoechstens ein Satz fuer den Funk oder AIError. Gibt bereinigten Text zurueck."""
    pid = cfg.get("provider")
    text = ask(pid, get_key(cfg, pid), get_model(cfg, pid), SYSTEM_PROMPT,
               build_prompt(facts), timeout=timeout, endpoint=endpoint)
    line = clean_reply(text)
    if not line:
        raise AIError("Antwort nicht als Funkspruch verwendbar.")
    return line


# ------------------------------------------------------------ Konfiguration -
def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    inb = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    outb = BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(outb))
    if not ok:
        raise OSError("DPAPI fehlgeschlagen")
    try:
        return ctypes.string_at(outb.pbData, outb.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outb.pbData)


def protect_secret(text):
    """Windows: DPAPI (nur dieser Benutzer auf diesem PC kann entschluesseln). Sonst Klartext."""
    if not text:
        return ""
    if os.name == "nt":
        try:
            enc = _dpapi(text.encode("utf-8"), True)
            if _dpapi(enc, False).decode("utf-8") == text:   # Rundlauf pruefen
                return "dpapi:" + base64.b64encode(enc).decode("ascii")
        except Exception:
            pass
    return "plain:" + text


def unprotect_secret(stored):
    if not stored:
        return ""
    try:
        if stored.startswith("dpapi:"):
            return _dpapi(base64.b64decode(stored[6:]), False).decode("utf-8")
        if stored.startswith("plain:"):
            return stored[6:]
    except Exception:
        return ""       # anderer Benutzer/PC -> Key neu eingeben
    return stored


def default_config():
    return {"provider": LOCAL_ID, "keys": {}, "models": {}}


def load_config(path):
    cfg = default_config()
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            if raw.get("provider") in PROVIDERS:
                cfg["provider"] = raw["provider"]
            for pid in PROVIDERS:
                k = (raw.get("keys") or {}).get(pid)
                if k:
                    cfg["keys"][pid] = unprotect_secret(k)
                m = (raw.get("models") or {}).get(pid)
                if m:
                    cfg["models"][pid] = str(m)
    except Exception:
        pass
    return cfg


def save_config(path, cfg):
    out = {"provider": cfg.get("provider", LOCAL_ID),
           "keys": {pid: protect_secret(k) for pid, k in (cfg.get("keys") or {}).items() if k},
           "models": {pid: m for pid, m in (cfg.get("models") or {}).items() if m}}
    d = os.path.dirname(str(path))
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    try:
        os.chmod(tmp, 0o600)
    except Exception:
        pass
    os.replace(tmp, path)


def get_key(cfg, pid):
    return (cfg.get("keys") or {}).get(pid, "")


def get_model(cfg, pid):
    spec = PROVIDERS.get(pid) or {}
    return (cfg.get("models") or {}).get(pid) or spec.get("model", "")


def is_active(cfg):
    pid = cfg.get("provider")
    return pid in PROVIDERS and bool(get_key(cfg, pid).strip())


def label(cfg):
    pid = cfg.get("provider")
    return PROVIDERS[pid]["label"] if pid in PROVIDERS else LOCAL_LABEL
