"""
PitBoss — Offline-Sprachausgabe  (additiv, 0.4.7.3)
=================================================================

Backends (in dieser Prioritaet)
-------------------------------
1. Piper (natuerlich, offline, KEINE Cloud)  -> lokales neuronales TTS. Sehr
   natuerliche Stimme (z.B. Thorsten/DE). Braucht einmalig die piper-Executable
   + ein Stimm-Modell (.onnx + .onnx.json). Pfade werden in der App gesetzt
   ("Natuerliche Stimme (Piper)...") und in exports/tts_config.json gemerkt.
   Synthese laeuft in einem Worker-Thread, Wiedergabe per winsound (async,
   unterbrechbar). Niedrige Latenz auf der CPU.
2. SAPI5 via pywin32  -> Windows-Standardstimmen (roboterhaft), asynchron.
3. PowerShell System.Speech  -> immer auf Windows vorhanden, offline, Fallback.
4. Kein Backend (z.B. Nicht-Windows / nichts konfiguriert) -> speak() ist No-Op.

Rate: -10..10. Volume: 0..100. (Piper: Rate/Volume systembedingt ohne Wirkung.)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

try:
    import winsound  # nur Windows
except Exception:
    winsound = None

def _app_dir() -> str:
    """Verzeichnis der App (PyInstaller-frozen oder Skript)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# SAPI-Flags
_SVSFlagsAsync = 1
_SVSFPurgeBeforeSpeak = 2

_MD = re.compile(r"[*_`#>|]+")
_BULLET = re.compile(r"^\s*[-\u2022\u2013]\s*", re.MULTILINE)


def _clean_for_speech(text: str) -> str:
    text = _MD.sub(" ", text or "")
    text = _BULLET.sub("", text)
    text = re.sub(r"\s[-\u2013\u2022]\s", " ", text)   # mittige Aufzaehlungsstriche
    text = re.sub(r"\s+", " ", text).strip()
    return text


class SpeechEngine:
    def __init__(self, config_path: str = os.path.join("exports", "tts_config.json")):
        self.config_path = config_path
        self._backend = None            # 'piper' | 'sapi' | 'powershell' | None
        self._sapi = None
        self._ps_proc = None
        self._voices: list[str] = []
        self.voice_name = ""
        self.rate = 0
        self.volume = 100
        self.auto_read = True           # 0.4.7.4: Auto-Vorlesen standardmaessig an
        # Piper
        self.piper_exe = ""
        self.piper_model = ""
        self._piper_proc = None
        self._piper_gen = 0
        self._piper_lock = threading.Lock()
        self._clip_cache = {}          # 0.4.8.5: vorsynthetisierte Countdown-Clips

        self._load_config()
        self._autodetect_bundled_piper()   # 0.4.8.0: mitgeliefertes Piper automatisch nutzen
        self._detect()
        self._apply_voice()

    # -- Backend-Erkennung ----------------------------------------------------
    def _detect(self) -> None:
        # 1) Piper hat Vorrang, wenn Executable + Modell existieren
        if self._piper_ready():
            self._backend = "piper"
            # SAPI-Stimmen zusaetzlich anbieten (falls User zurueckwechselt)
            self._probe_sapi_voices()
            return
        if not sys.platform.startswith("win"):
            self._backend = None
            return
        try:
            import pythoncom  # noqa
            import win32com.client
            try:
                pythoncom.CoInitialize()
            except Exception:
                pass
            self._sapi = win32com.client.Dispatch("SAPI.SpVoice")
            toks = self._sapi.GetVoices()
            self._voices = [toks.Item(i).GetDescription() for i in range(toks.Count)]
            self._backend = "sapi"
            return
        except Exception:
            self._sapi = None
        if shutil.which("powershell"):
            self._backend = "powershell"
            self._voices = self._ps_list_voices()
            return
        self._backend = None

    def _probe_sapi_voices(self) -> None:
        if not sys.platform.startswith("win"):
            return
        try:
            import pythoncom  # noqa
            import win32com.client
            try:
                pythoncom.CoInitialize()
            except Exception:
                pass
            self._sapi = win32com.client.Dispatch("SAPI.SpVoice")
            toks = self._sapi.GetVoices()
            self._voices = [toks.Item(i).GetDescription() for i in range(toks.Count)]
        except Exception:
            self._sapi = None

    def _autodetect_bundled_piper(self) -> None:
        """Sucht ein mit der App ausgeliefertes Piper (piper.exe + *.onnx) und
        aktiviert es automatisch, falls der Nutzer nichts eigenes gesetzt hat."""
        if self.piper_exe and self.piper_model:
            return
        base = _app_dir()
        cand_dirs = [os.path.join(base, 'piper'), os.path.join(base, '_internal', 'piper'),
                     base, os.path.join(base, '_internal')]
        exe = ''
        for d in cand_dirs:
            for name in ('piper.exe', 'piper'):
                p = os.path.join(d, name)
                if os.path.isfile(p):
                    exe = p; break
            if exe: break
        if not exe:
            return
        model = ''
        for d in cand_dirs:
            if os.path.isdir(d):
                for f in sorted(os.listdir(d)):
                    if f.lower().endswith('.onnx'):
                        model = os.path.join(d, f); break
            if model: break
        if exe and model:
            self.piper_exe, self.piper_model = exe, model

    def _piper_ready(self) -> bool:
        return bool(self.piper_exe and self.piper_model
                    and os.path.isfile(self.piper_exe) and os.path.isfile(self.piper_model))

    def is_available(self) -> bool:
        return self._backend is not None

    def backend(self) -> str:
        return self._backend or "none"

    def list_voices(self) -> list[str]:
        return list(self._voices)

    # -- Konfiguration --------------------------------------------------------
    def _load_config(self) -> None:
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            self.voice_name = cfg.get("voice", "") or ""
            self.rate = int(cfg.get("rate", 0))
            self.volume = int(cfg.get("volume", 100))
            self.auto_read = bool(cfg.get("auto_read", False))
            self.piper_exe = cfg.get("piper_exe", "") or ""
            self.piper_model = cfg.get("piper_model", "") or ""
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            pass

    def _save_config(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.config_path) or ".", exist_ok=True)
            tmp = self.config_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"voice": self.voice_name, "rate": self.rate,
                           "volume": self.volume, "auto_read": self.auto_read,
                           "piper_exe": self.piper_exe, "piper_model": self.piper_model},
                          fh, indent=2)
            os.replace(tmp, self.config_path)
        except Exception:
            pass

    # -- Setter ---------------------------------------------------------------
    def set_rate(self, value: int) -> None:
        self.rate = max(-10, min(10, int(value)))
        self._save_config()

    def set_volume(self, value: int) -> None:
        self.volume = max(0, min(100, int(value)))
        self._save_config()

    def set_auto_read(self, value: bool) -> None:
        self.auto_read = bool(value)
        self._save_config()

    def set_voice(self, name: str) -> None:
        self.voice_name = name or ""
        self._apply_voice()
        self._save_config()

    def set_piper(self, exe: str, model: str) -> bool:
        """Piper-Executable + Stimm-Modell setzen. Bei Erfolg wird Piper aktiv."""
        self.piper_exe = exe or ""
        self.piper_model = model or ""
        self._save_config()
        self._detect()
        return self._backend == "piper"

    def clear_piper(self) -> None:
        self.piper_exe = ""
        self.piper_model = ""
        self._save_config()
        self._detect()

    def _apply_voice(self) -> None:
        if self._sapi is not None and self.voice_name:
            try:
                toks = self._sapi.GetVoices()
                for i in range(toks.Count):
                    if toks.Item(i).GetDescription() == self.voice_name:
                        self._sapi.Voice = toks.Item(i)
                        break
            except Exception:
                pass

    # -- Ausgabe --------------------------------------------------------------
    def speak(self, text: str, interrupt: bool = True) -> bool:
        text = _clean_for_speech(text)
        if not text or self._backend is None:
            return False
        if self._backend == "piper":
            return self._piper_speak(text, interrupt)
        if self._backend == "sapi":
            return self._sapi_speak(text, interrupt)
        if self._backend == "powershell":
            return self._ps_speak(text, interrupt)
        return False

    def stop(self) -> None:
        # Piper
        with self._piper_lock:
            self._piper_gen += 1
            if self._piper_proc is not None and self._piper_proc.poll() is None:
                try:
                    self._piper_proc.terminate()
                except Exception:
                    pass
        if winsound is not None:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        # SAPI
        if self._sapi is not None:
            try:
                self._sapi.Speak("", _SVSFPurgeBeforeSpeak | _SVSFlagsAsync)
            except Exception:
                pass
        # PowerShell
        if self._ps_proc is not None and self._ps_proc.poll() is None:
            try:
                self._ps_proc.terminate()
            except Exception:
                pass

    # -- Piper (natuerlich, offline) -----------------------------------------
    def _piper_speak(self, text: str, interrupt: bool) -> bool:
        if not self._piper_ready():
            return False
        with self._piper_lock:
            if interrupt:
                self._piper_gen += 1
                if self._piper_proc is not None and self._piper_proc.poll() is None:
                    try:
                        self._piper_proc.terminate()
                    except Exception:
                        pass
                if winsound is not None:
                    try:
                        winsound.PlaySound(None, winsound.SND_PURGE)
                    except Exception:
                        pass
            gen = self._piper_gen
        threading.Thread(target=self._piper_worker, args=(text, gen), daemon=True).start()
        return True

    def _piper_worker(self, text: str, gen: int) -> None:
        wav = os.path.join(tempfile.gettempdir(), f"pitboss_r3e_piper_{gen}.wav")
        cmd = [self.piper_exe, "-m", self.piper_model, "-f", wav]  # Kurzflags = versionsrobust
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with self._piper_lock:
                if gen != self._piper_gen:            # zwischenzeitlich neuer Aufruf
                    proc.terminate(); return
                self._piper_proc = proc
            proc.communicate(input=text.encode("utf-8"))
            if proc.returncode != 0 or not os.path.isfile(wav):
                return
            with self._piper_lock:
                if gen != self._piper_gen:            # veraltet -> nicht abspielen
                    return
            if winsound is not None:
                winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            return

    # -- Vorsynthetisierte Clips (0.4.8.5, fuer Brems-Countdown) --------------
    def prewarm_clips(self, clips: dict) -> bool:
        """Synthetisiert kurze Ansagen einmalig zu WAVs (nur Piper), damit sie
        spaeter latenzfrei abgespielt werden koennen. clips: {key: text}.
        Ohne Piper werden die Clips leer gecacht -> play_clip nutzt Live-speak."""
        if not isinstance(getattr(self, "_clip_cache", None), dict):
            self._clip_cache = {}
        if self._backend != "piper" or not self._piper_ready():
            for k, t in clips.items():
                self._clip_cache[k] = (None, t)
            return False
        ok = True
        for k, t in clips.items():
            cached = self._clip_cache.get(k)
            if cached and cached[0] and os.path.isfile(cached[0]):
                continue
            wav = os.path.join(tempfile.gettempdir(), f"pitboss_r3e_clip_{k}.wav")
            if self._piper_synth_to(t, wav):
                self._clip_cache[k] = (wav, t)
            else:
                self._clip_cache[k] = (None, t)
                ok = False
        return ok

    def _piper_synth_to(self, text: str, out_wav: str) -> bool:
        if not self._piper_ready():
            return False
        cmd = [self.piper_exe, "-m", self.piper_model, "-f", out_wav]
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            proc.communicate(input=_clean_for_speech(text).encode("utf-8"), timeout=20)
            return proc.returncode == 0 and os.path.isfile(out_wav)
        except Exception:
            return False

    def play_clip(self, key: str, fallback_text: str = "") -> bool:
        """Spielt einen vorsynthetisierten Clip latenzarm ab (winsound); faellt auf
        Live-speak zurueck, wenn kein Clip vorhanden ist (z.B. SAPI/PowerShell)."""
        entry = getattr(self, "_clip_cache", {}).get(key)
        wav = entry[0] if entry else None
        if wav and winsound is not None and os.path.isfile(wav):
            try:
                winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
                return True
            except Exception:
                pass
        return self.speak(fallback_text or (entry[1] if entry else ""), interrupt=True)

    # -- SAPI ----------------------------------------------------------------
    def _sapi_speak(self, text: str, interrupt: bool) -> bool:
        try:
            self._sapi.Rate = self.rate
            self._sapi.Volume = self.volume
            flags = _SVSFlagsAsync | (_SVSFPurgeBeforeSpeak if interrupt else 0)
            self._sapi.Speak(text, flags)
            return True
        except Exception:
            return False

    # -- PowerShell System.Speech (Fallback) ---------------------------------
    def _ps_list_voices(self) -> list[str]:
        script = ("Add-Type -AssemblyName System.Speech;"
                  "(New-Object System.Speech.Synthesis.SpeechSynthesizer)."
                  "GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                 capture_output=True, text=True, timeout=8,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return [l.strip() for l in out.stdout.splitlines() if l.strip()]
        except Exception:
            return []

    def _ps_speak(self, text: str, interrupt: bool) -> bool:
        if interrupt and self._ps_proc is not None and self._ps_proc.poll() is None:
            try:
                self._ps_proc.terminate()
            except Exception:
                pass
        safe = text.replace("'", "''")
        voice_sel = f"$s.SelectVoice('{self.voice_name}');" if self.voice_name else ""
        script = ("Add-Type -AssemblyName System.Speech;"
                  "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                  f"{voice_sel}$s.Rate={self.rate};$s.Volume={self.volume};"
                  f"$s.Speak('{safe}')")
        try:
            self._ps_proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", script],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
        except Exception:
            return False


if __name__ == "__main__":
    eng = SpeechEngine(config_path=os.path.join("exports", "tts_config_demo.json"))
    print("Backend:", eng.backend(), "| Stimmen:", eng.list_voices() or "(keine)")
    print("speak ->", eng.speak(sys.argv[1] if len(sys.argv) > 1 else "Sprachausgabe aktiv."))
    import time; time.sleep(2)
