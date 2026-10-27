"""RaceRoom Racing Experience (R3E) - Shared-Memory-Reader fuer PitBoss R3E.

Standalone, stdlib-only: liest den Shared-Memory-Block ``$R3E`` des Spiels und bildet ihn auf
PitBoss' ``Sample`` ab, sodass Overlays, Recording, Rundenanalyse, Spotter-Daten usw. darauf laufen.

Quelle der Struktur: Sector3 Studios ``r3e-api/sample-c/src/r3e.h`` (Version 3.5, ``#pragma
pack(1)``). Die ctypes-Klassen unten wurden maschinell aus diesem Header erzeugt und gegen
``sizeof``/``offsetof`` eines mit gcc uebersetzten C-Programms geprueft (315/315 identisch).

Kalibrier-Overrides (nur falls die Auto-Erkennung falsch liegt, per Umgebungsvariable):
    PITBOSS_R3E_WEAR=new1|new0         tire_wear: 1.0 = neu | 0.0 = neu
    PITBOSS_R3E_SECTORS=cumulative|single   Sektorzeiten kumulativ | einzeln
    PITBOSS_R3E_DAMAGE=intact1|intact0 car_damage: 1.0 = heil | 0.0 = heil

CLI:
    python raceroom_sm.py --probe     # einmal alle wichtigen Rohwerte ausgeben (Kalibrierung)
    python raceroom_sm.py --watch     # laufende Live-Zeile (2 Hz)
    python raceroom_sm.py --selftest  # Mapping-Tests gegen synthetischen Speicherblock
"""
from __future__ import annotations

import ctypes
import json
import math
import mmap
import os
import sys
import time
from datetime import datetime
from pathlib import Path

R3E_SHARED_MEMORY_NAME = "$R3E"
R3E_VERSION_MAJOR = 3
R3E_VERSION_MINOR_KNOWN = 5
R3E_NUM_DRIVERS_MAX = 128

# ---------------------------------------------------------------------------
# ctypes-Strukturen (generiert aus r3e.h, Version 3.5)
# ---------------------------------------------------------------------------
c_int32 = ctypes.c_int32
c_float = ctypes.c_float
c_double = ctypes.c_double
c_ubyte = ctypes.c_ubyte


class R3EVec3F32(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("x", c_float),
        ("y", c_float),
        ("z", c_float),
    ]


class R3EVec3F64(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("x", c_double),
        ("y", c_double),
        ("z", c_double),
    ]


class R3EOriF32(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("pitch", c_float),
        ("yaw", c_float),
        ("roll", c_float),
    ]


class R3ESectorstarts(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("sector1", c_float),
        ("sector2", c_float),
        ("sector3", c_float),
    ]


class R3EPlayerdata(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("user_id", c_int32),
        ("game_simulation_ticks", c_int32),
        ("game_simulation_time", c_double),
        ("position", R3EVec3F64),
        ("velocity", R3EVec3F64),
        ("local_velocity", R3EVec3F64),
        ("acceleration", R3EVec3F64),
        ("local_acceleration", R3EVec3F64),
        ("orientation", R3EVec3F64),
        ("rotation", R3EVec3F64),
        ("angular_acceleration", R3EVec3F64),
        ("angular_velocity", R3EVec3F64),
        ("local_angular_velocity", R3EVec3F64),
        ("local_g_force", R3EVec3F64),
        ("steering_force", c_double),
        ("steering_force_percentage", c_double),
        ("engine_torque", c_double),
        ("current_downforce", c_double),
        ("voltage", c_double),
        ("ers_level", c_double),
        ("power_mgu_h", c_double),
        ("power_mgu_k", c_double),
        ("torque_mgu_k", c_double),
        ("suspension_deflection", c_double * 4),
        ("suspension_velocity", c_double * 4),
        ("camber", c_double * 4),
        ("ride_height", c_double * 4),
        ("front_wing_height", c_double),
        ("front_roll_angle", c_double),
        ("rear_roll_angle", c_double),
        ("third_spring_suspension_deflection_front", c_double),
        ("third_spring_suspension_velocity_front", c_double),
        ("third_spring_suspension_deflection_rear", c_double),
        ("third_spring_suspension_velocity_rear", c_double),
        ("unused1", c_double),
        ("unused2", c_double),
        ("unused3", c_double),
    ]


class R3EFlags(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("yellow", c_int32),
        ("yellowCausedIt", c_int32),
        ("yellowOvertake", c_int32),
        ("yellowPositionsGained", c_int32),
        ("sector_yellow", c_int32 * 3),
        ("closest_yellow_distance_into_track", c_float),
        ("blue", c_int32),
        ("black", c_int32),
        ("green", c_int32),
        ("checkered", c_int32),
        ("white", c_int32),
        ("black_and_white", c_int32),
    ]


class R3ECarDamage(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("engine", c_float),
        ("transmission", c_float),
        ("aerodynamics", c_float),
        ("suspension", c_float),
        ("unused1", c_float),
        ("unused2", c_float),
    ]


class R3ECutTrackPenalties(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("drive_through", c_float),
        ("stop_and_go", c_float),
        ("pit_stop", c_float),
        ("time_deduction", c_float),
        ("slow_down", c_float),
    ]


class R3EDrs(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("equipped", c_int32),
        ("available", c_int32),
        ("numActivationsLeft", c_int32),
        ("engaged", c_int32),
    ]


class R3EPushToPass(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("available", c_int32),
        ("engaged", c_int32),
        ("amount_left", c_int32),
        ("engaged_time_left", c_float),
        ("wait_time_left", c_float),
    ]


class R3ETireTemp(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("current_temp", c_float * 3),
        ("optimal_temp", c_float),
        ("cold_temp", c_float),
        ("hot_temp", c_float),
    ]


class R3EBrakeTemp(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("current_temp", c_float),
        ("optimal_temp", c_float),
        ("cold_temp", c_float),
        ("hot_temp", c_float),
    ]


class R3EAidSettings(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("abs", c_int32),
        ("tc", c_int32),
        ("esp", c_int32),
        ("countersteer", c_int32),
        ("cornering", c_int32),
    ]


class R3EDriverInfo(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("name", c_ubyte * 64),
        ("car_number", c_int32),
        ("class_id", c_int32),
        ("model_id", c_int32),
        ("team_id", c_int32),
        ("livery_id", c_int32),
        ("manufacturer_id", c_int32),
        ("user_id", c_int32),
        ("slot_id", c_int32),
        ("class_performance_index", c_int32),
        ("engine_type", c_int32),
        ("car_width", c_float),
        ("car_length", c_float),
        ("rating", c_float),
        ("reputation", c_float),
        ("unused1", c_float),
        ("unused2", c_float),
    ]


class R3EDriverData(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("driver_info", R3EDriverInfo),
        ("finish_status", c_int32),
        ("place", c_int32),
        ("place_class", c_int32),
        ("lap_distance", c_float),
        ("lap_distance_fraction", c_float),
        ("position", R3EVec3F32),
        ("track_sector", c_int32),
        ("completed_laps", c_int32),
        ("current_lap_valid", c_int32),
        ("lap_time_current_self", c_float),
        ("sector_time_current_self", c_float * 3),
        ("sector_time_previous_self", c_float * 3),
        ("sector_time_best_self", c_float * 3),
        ("time_delta_front", c_float),
        ("time_delta_behind", c_float),
        ("pitstop_status", c_int32),
        ("in_pitlane", c_int32),
        ("num_pitstops", c_int32),
        ("penalties", R3ECutTrackPenalties),
        ("car_speed", c_float),
        ("tire_type_front", c_int32),
        ("tire_type_rear", c_int32),
        ("tire_subtype_front", c_int32),
        ("tire_subtype_rear", c_int32),
        ("base_penalty_weight", c_float),
        ("aid_penalty_weight", c_float),
        ("drs_state", c_int32),
        ("ptp_state", c_int32),
        ("virtual_energy", c_float),
        ("penaltyType", c_int32),
        ("penaltyReason", c_int32),
        ("engineState", c_int32),
        ("orientation", R3EVec3F32),
        ("unused1", c_float),
        ("unused2", c_float),
        ("unused3", c_float),
    ]


class R3EShared(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("version_major", c_int32),
        ("version_minor", c_int32),
        ("all_drivers_offset", c_int32),
        ("driver_data_size", c_int32),
        ("game_mode", c_int32),
        ("game_paused", c_int32),
        ("game_in_menus", c_int32),
        ("game_in_replay", c_int32),
        ("game_using_vr", c_int32),
        ("game_player_in_garage", c_int32),
        ("player", R3EPlayerdata),
        ("track_name", c_ubyte * 64),
        ("layout_name", c_ubyte * 64),
        ("track_id", c_int32),
        ("layout_id", c_int32),
        ("layout_length", c_float),
        ("sector_start_factors", R3ESectorstarts),
        ("race_session_laps", c_int32 * 3),
        ("race_session_minutes", c_int32 * 3),
        ("event_index", c_int32),
        ("session_type", c_int32),
        ("session_iteration", c_int32),
        ("session_length_format", c_int32),
        ("session_pit_speed_limit", c_float),
        ("session_phase", c_int32),
        ("start_lights", c_int32),
        ("tire_wear_active", c_int32),
        ("fuel_use_active", c_int32),
        ("number_of_laps", c_int32),
        ("session_time_duration", c_float),
        ("session_time_remaining", c_float),
        ("max_incident_points", c_int32),
        ("event_unused1", c_float),
        ("event_unused2", c_float),
        ("pit_window_status", c_int32),
        ("pit_window_start", c_int32),
        ("pit_window_end", c_int32),
        ("in_pitlane", c_int32),
        ("pit_menu_selection", c_int32),
        ("pit_menu_state", c_int32 * 12),
        ("pit_state", c_int32),
        ("pit_total_duration", c_float),
        ("pit_elapsed_time", c_float),
        ("pit_action", c_int32),
        ("num_pitstops", c_int32),
        ("pit_min_duration_total", c_float),
        ("pit_min_duration_left", c_float),
        ("flags", R3EFlags),
        ("position", c_int32),
        ("position_class", c_int32),
        ("finish_status", c_int32),
        ("cut_track_warnings", c_int32),
        ("penalties", R3ECutTrackPenalties),
        ("num_penalties", c_int32),
        ("completed_laps", c_int32),
        ("current_lap_valid", c_int32),
        ("track_sector", c_int32),
        ("lap_distance", c_float),
        ("lap_distance_fraction", c_float),
        ("lap_time_best_leader", c_float),
        ("lap_time_best_leader_class", c_float),
        ("session_best_lap_sector_times", c_float * 3),
        ("lap_time_best_self", c_float),
        ("sector_time_best_self", c_float * 3),
        ("lap_time_previous_self", c_float),
        ("sector_time_previous_self", c_float * 3),
        ("lap_time_current_self", c_float),
        ("sector_time_current_self", c_float * 3),
        ("lap_time_delta_leader", c_float),
        ("lap_time_delta_leader_class", c_float),
        ("time_delta_front", c_float),
        ("time_delta_behind", c_float),
        ("time_delta_best_self", c_float),
        ("best_individual_sector_time_self", c_float * 3),
        ("best_individual_sector_time_leader", c_float * 3),
        ("best_individual_sector_time_leader_class", c_float * 3),
        ("incident_points", c_int32),
        ("lap_valid_state", c_int32),
        ("prev_lap_valid", c_int32),
        ("discharge_rate", c_float),
        ("brake_regen", c_float),
        ("unused1", c_float),
        ("vehicle_info", R3EDriverInfo),
        ("player_name", c_ubyte * 64),
        ("control_type", c_int32),
        ("car_speed", c_float),
        ("engine_rps", c_float),
        ("max_engine_rps", c_float),
        ("upshift_rps", c_float),
        ("gear", c_int32),
        ("num_gears", c_int32),
        ("car_cg_location", R3EVec3F32),
        ("car_orientation", R3EOriF32),
        ("local_acceleration", R3EVec3F32),
        ("total_mass", c_float),
        ("fuel_left", c_float),
        ("fuel_capacity", c_float),
        ("fuel_per_lap", c_float),
        ("virtual_energy_left", c_float),
        ("virtual_energy_capacity", c_float),
        ("virtual_energy_per_lap", c_float),
        ("engine_temp", c_float),
        ("engine_oil_temp", c_float),
        ("fuel_pressure", c_float),
        ("engine_oil_pressure", c_float),
        ("turbo_pressure", c_float),
        ("throttle", c_float),
        ("throttle_raw", c_float),
        ("brake", c_float),
        ("brake_raw", c_float),
        ("clutch", c_float),
        ("clutch_raw", c_float),
        ("steer_input_raw", c_float),
        ("steer_lock_degrees", c_int32),
        ("steer_wheel_range_degrees", c_int32),
        ("aid_settings", R3EAidSettings),
        ("drs", R3EDrs),
        ("pit_limiter", c_int32),
        ("push_to_pass", R3EPushToPass),
        ("brake_bias", c_float),
        ("drs_numActivationsTotal", c_int32),
        ("ptp_numActivationsTotal", c_int32),
        ("battery_soc", c_float),
        ("water_left", c_float),
        ("abs_setting", c_int32),
        ("headlights", c_int32),
        ("steer_wheel_max_rotation", c_int32),
        ("tire_type", c_int32),
        ("tire_rps", c_float * 4),
        ("tire_speed", c_float * 4),
        ("tire_grip", c_float * 4),
        ("tire_wear", c_float * 4),
        ("tire_flatspot", c_int32 * 4),
        ("tire_pressure", c_float * 4),
        ("tire_dirt", c_float * 4),
        ("tire_temp", R3ETireTemp * 4),
        ("tire_type_front", c_int32),
        ("tire_type_rear", c_int32),
        ("tire_subtype_front", c_int32),
        ("tire_subtype_rear", c_int32),
        ("brake_temp", R3EBrakeTemp * 4),
        ("brake_pressure", c_float * 4),
        ("traction_control_setting", c_int32),
        ("engine_map_setting", c_int32),
        ("engine_brake_setting", c_int32),
        ("traction_control_percent", c_float),
        ("tire_on_mtrl", c_int32 * 4),
        ("tire_load", c_float * 4),
        ("car_damage", R3ECarDamage),
        ("num_cars", c_int32),
        ("all_drivers_data_1", R3EDriverData * 128),
    ]


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
_RPS_TO_RPM = 60.0 / (2.0 * math.pi)
_APP_DIR = Path(__file__).resolve().parent
_NAMES_FILE = _APP_DIR / "assets" / "r3e_names.json"


def _txt(arr) -> str:
    """Nullterminierten UTF-8-Puffer (ctypes-Array) in str wandeln."""
    try:
        return bytes(arr).split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _f(v, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _pos(v, default: float = 0.0) -> float:
    """R3E meldet 'nicht verfuegbar' als -1.0 -> auf default abbilden."""
    x = _f(v, default)
    return x if x >= 0.0 else default


def _na_int(v, default: int = 0) -> int:
    try:
        x = int(v)
        return x if x >= 0 else default
    except Exception:
        return default


def _unit(v) -> float:
    """0..1-Wert (Pedale); -1 = N/A -> 0."""
    x = _f(v, 0.0)
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _gap(v) -> float:
    x = _f(v, 0.0)
    return 0.0 if x == -1.0 else abs(x)


def load_names(path=None):
    """Auto-/Klassennamen (ID -> Name) aus assets/r3e_names.json. Fehlt die Datei: leere Tabellen."""
    p = Path(path) if path else _NAMES_FILE
    try:
        with open(p, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return ({int(k): str(v) for k, v in d.get("cars", {}).items()},
                {int(k): str(v) for k, v in d.get("classes", {}).items()})
    except Exception:
        return {}, {}


# R3E-Session -> PitBoss-Konvention (mSession: 1-4 Practice, 5-8 Quali, 9 Warmup, 10-13 Rennen)
_SESSION_MAP = {0: 1, 1: 5, 2: 10, 3: 9}
# R3E-Session-Phase -> mGamePhase-Konvention (5 gruen, 8 Session vorbei ...)
_PHASE_MAP = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 8}


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------
class _MemoryBasicInformation(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", ctypes.c_uint32),
                ("PartitionId", ctypes.c_uint16), ("RegionSize", ctypes.c_size_t), ("State", ctypes.c_uint32),
                ("Protect", ctypes.c_uint32), ("Type", ctypes.c_uint32)]


class R3EReader:
    """Liest ``$R3E`` und liefert ``read_sample()`` -> PitBoss-``Sample`` (PitBoss-Sample).

    sample_cls   : PitBoss' Sample-Dataclass (wird von main.py uebergeben; vermeidet zirkulaeren Import)
    raw_provider : optional, liefert die Rohbytes (Tests/Mock); sonst echtes Shared Memory
    """

    source_label = "RaceRoom"

    def __init__(self, sample_cls, names_path=None, raw_provider=None, env=None, k32=None):
        self.Sample = sample_cls
        self._k32 = k32  # nur Tests: Fake-kernel32
        self.size = ctypes.sizeof(R3EShared)
        self._head_size = R3EShared.num_cars.offset  # Teilblock ohne Fahrerliste (Fallback bei kleinerem Mapping)
        self._raw_provider = raw_provider
        self._view_size = None
        self.car_names, self.class_names = load_names(names_path)
        env = os.environ if env is None else env
        # Reifenverschleiss: 1.0 = neu (Standardannahme) oder 0.0 = neu. Auto-Erkennung in der ersten Runde.
        ov = (env.get("PITBOSS_R3E_WEAR", "") or "").strip().lower()
        self._wear_new_is_one = {"new1": True, "new0": False}.get(ov)
        self._wear_locked = ov in ("new1", "new0")
        # Sektorzeiten: kumulativ (S1, S1+S2, Runde) oder einzeln - wird an der Vorrunde erkannt.
        sv = (env.get("PITBOSS_R3E_SECTORS", "") or "").strip().lower()
        self._sectors_cumulative = {"cumulative": True, "single": False}.get(sv)
        self._sectors_locked = sv in ("cumulative", "single")
        # Fahrzeugschaden: 1.0 = heil (Standardannahme) oder 0.0 = heil - beim ersten Frame ohne Schaden erkannt.
        dv = (env.get("PITBOSS_R3E_DAMAGE", "") or "").strip().lower()
        self._dmg_intact_is_one = {"intact1": True, "intact0": False}.get(dv)
        self._dmg_locked = dv in ("intact1", "intact0")
        # Bremsdruck kommt in kN -> pro Rad gegen den bisherigen Spitzenwert (je Fahrzeug) auf 0..1 normiert.
        self._brake_peak = [0.0, 0.0, 0.0, 0.0]
        self._brake_model = -1
        self.last_version = (0, 0)
        self.layout_warning = ""

    # ----- Rohdaten --------------------------------------------------------
    def _read_raw(self) -> bytes:
        if self._raw_provider is not None:
            raw = bytes(self._raw_provider())
        elif sys.platform == "win32" or self._k32 is not None:
            raw = self._read_open_only()
        else:
            # Nicht-Windows (nur Tests/Entwicklung): mmap-Fallback
            sizes = [self._view_size] if self._view_size else [self.size, self._head_size]
            last_err = None
            raw = None
            for sz in sizes:
                try:
                    with mmap.mmap(-1, sz, tagname=R3E_SHARED_MEMORY_NAME, access=mmap.ACCESS_READ) as mm:
                        raw = mm[:]
                    self._view_size = sz
                    break
                except (OSError, ValueError, TypeError) as e:
                    last_err = e
            if raw is None:
                raise RuntimeError(f"RaceRoom Shared Memory ($R3E) nicht lesbar ({last_err}). Laeuft RaceRoom?")
        if len(raw) < self.size:
            raw = raw + bytes(self.size - len(raw))
        return raw

    def _read_open_only(self) -> bytes:
        """Windows: das vom Spiel angelegte Mapping NUR OEFFNEN (OpenFileMapping, nur lesen) - nie anlegen.
        Python-mmap mit tagname legt das Mapping an, wenn es (noch) nicht existiert; dann haelt PitBoss ein
        eigenes, zu kleines Nur-Lese-Objekt unter dem Namen $R3E und kann das Spiel beim Start stoeren."""
        k32 = self._k32 if self._k32 is not None else self._load_k32()
        FILE_MAP_READ = 0x0004
        h = k32.OpenFileMappingW(FILE_MAP_READ, False, R3E_SHARED_MEMORY_NAME)
        if not h:
            raise RuntimeError("RaceRoom Shared Memory ($R3E) nicht gefunden - laeuft RaceRoom und bist du in einer Session?")
        view = None
        try:
            view = k32.MapViewOfFile(h, FILE_MAP_READ, 0, 0, 0)
            if not view:
                raise RuntimeError("RaceRoom Shared Memory ($R3E) konnte nicht eingeblendet werden.")
            mbi = _MemoryBasicInformation()
            size = self.size
            if k32.VirtualQuery(view, ctypes.byref(mbi), ctypes.sizeof(mbi)):
                size = min(self.size, int(mbi.RegionSize))
            return ctypes.string_at(view, size)
        finally:
            if view:
                k32.UnmapViewOfFile(view)
            k32.CloseHandle(h)

    @staticmethod
    def _load_k32():
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        vp, dw = ctypes.c_void_p, ctypes.c_uint32
        k32.OpenFileMappingW.argtypes = [dw, ctypes.c_int, ctypes.c_wchar_p]
        k32.OpenFileMappingW.restype = vp
        k32.MapViewOfFile.argtypes = [vp, dw, dw, dw, ctypes.c_size_t]
        k32.MapViewOfFile.restype = vp
        k32.UnmapViewOfFile.argtypes = [vp]
        k32.UnmapViewOfFile.restype = ctypes.c_int
        k32.CloseHandle.argtypes = [vp]
        k32.CloseHandle.restype = ctypes.c_int
        k32.VirtualQuery.argtypes = [vp, vp, ctypes.c_size_t]
        k32.VirtualQuery.restype = ctypes.c_size_t
        return k32

    def read_object(self) -> "R3EShared":
        return R3EShared.from_buffer_copy(self._read_raw())

    # ----- Fahrerliste (robust ueber all_drivers_offset/driver_data_size) -----
    def _drivers(self, raw: bytes, d: "R3EShared"):
        n = max(0, min(int(d.num_cars), R3E_NUM_DRIVERS_MAX))
        base = int(d.all_drivers_offset) + 4  # all_drivers_offset zeigt auf num_cars (int32), danach das Array
        stride = int(d.driver_data_size) or ctypes.sizeof(R3EDriverData)
        need = ctypes.sizeof(R3EDriverData)
        out = []
        if base < 4 or stride < need:
            return out
        for i in range(n):
            o = base + i * stride
            if o + need > len(raw):
                break
            out.append(R3EDriverData.from_buffer_copy(raw, o))
        return out

    def _layout_warning(self, d: "R3EShared") -> str:
        """Erkennt, wenn das Spiel einen anderen Speicheraufbau meldet als r3e.h 3.5 (z.B. nach einem Spiel-Update)."""
        warn = []
        if int(d.version_minor) > R3E_VERSION_MINOR_KNOWN:
            warn.append(f"API 3.{int(d.version_minor)} neuer als bekannt (3.{R3E_VERSION_MINOR_KNOWN}); neue Felder werden ignoriert")
        if int(d.driver_data_size) != ctypes.sizeof(R3EDriverData):
            warn.append(f"Fahrerblock {int(d.driver_data_size)} statt {ctypes.sizeof(R3EDriverData)} Byte")
        if int(d.all_drivers_offset) != R3EShared.num_cars.offset:
            warn.append(f"Fahrerliste bei Offset {int(d.all_drivers_offset)} statt {R3EShared.num_cars.offset}")
        return "; ".join(warn)

    # ----- Heuristiken ------------------------------------------------------
    def _detect_sectors(self, d: "R3EShared"):
        if self._sectors_locked:
            return
        lap = _pos(d.lap_time_previous_self)
        s = [_pos(x) for x in d.sector_time_previous_self]
        if lap > 1.0 and all(v > 0.0 for v in s):
            if abs(s[2] - lap) < 0.05:
                self._sectors_cumulative = True
            elif abs(s[0] + s[1] + s[2] - lap) < 0.05:
                self._sectors_cumulative = False

    def _sec2(self, s1: float, s2: float) -> float:
        """PitBoss erwartet S2 kumulativ (S1+S2)."""
        if self._sectors_cumulative is False and s1 > 0.0 and s2 > 0.0:
            return s1 + s2
        return s2

    def _wear_pct(self, d: "R3EShared", completed: int):
        raw = [_f(x, -1.0) for x in d.tire_wear]
        valid = [w for w in raw if w >= 0.0]
        if not self._wear_locked and valid and completed <= 0:
            mean = sum(valid) / len(valid)
            if mean >= 0.9:
                self._wear_new_is_one = True
            elif mean <= 0.1:
                self._wear_new_is_one = False
        new_is_one = True if self._wear_new_is_one is None else self._wear_new_is_one
        out = []
        for w in raw:
            if w < 0.0:
                out.append(0.0)
            else:
                w = min(1.0, w)
                out.append((w if new_is_one else 1.0 - w) * 100.0)  # PitBoss: Rest-Profil in %
        return out

    def _damage_pct(self, d: "R3EShared"):
        """car_damage -> Schaden in % (0 = heil, 100 = zerstoert); -1 = nicht verfuegbar."""
        cd = d.car_damage
        raw = [_f(cd.engine, -1.0), _f(cd.transmission, -1.0), _f(cd.aerodynamics, -1.0), _f(cd.suspension, -1.0)]
        valid = [v for v in raw if v >= 0.0]
        if not self._dmg_locked and valid:
            if all(v >= 0.9 for v in valid):
                self._dmg_intact_is_one, self._dmg_locked = True, True
            elif all(v <= 0.1 for v in valid):
                self._dmg_intact_is_one, self._dmg_locked = False, True
        intact_one = True if self._dmg_intact_is_one is None else self._dmg_intact_is_one
        out = []
        for v in raw:
            if v < 0.0:
                out.append(-1.0)
            else:
                v = min(1.0, v)
                out.append(((1.0 - v) if intact_one else v) * 100.0)
        return out

    def _brake_norm(self, d: "R3EShared"):
        mid = int(d.vehicle_info.model_id)
        if mid != self._brake_model:
            self._brake_model = mid
            self._brake_peak = [0.0, 0.0, 0.0, 0.0]
        out = []
        for i in range(4):
            p = _pos(d.brake_pressure[i])
            if p > self._brake_peak[i]:
                self._brake_peak[i] = p
            out.append(min(1.0, p / self._brake_peak[i]) if self._brake_peak[i] > 1e-6 else 0.0)
        return out

    def _tire_window(self, d: "R3EShared"):
        """Vom Spiel gelieferte Temperaturfenster (kalt/optimal/heiss), Mittel ueber die Raeder; 0 = unbekannt."""
        res = []
        for attr in ("cold_temp", "optimal_temp", "hot_temp"):
            vals = [_pos(getattr(d.tire_temp[i], attr)) for i in range(4)]
            vals = [v for v in vals if v > 0.0]
            res.append(sum(vals) / len(vals) if vals else 0.0)
        return res

    def _sector_bounds_m(self, d: "R3EShared"):
        """0.2.9: offizielle Sektorgrenzen aus dem Spiel (sector_start_factors x layout_length).

        Liefert die INNEREN Grenzen in Metern (Sektor1-Ende, Sektor2-Ende) als Tuple,
        oder (), wenn das Spiel keine gueltigen Werte liefert (z.B. -1 oder 0).
        Faktoren sind Anteile der Streckenlaenge (0..1); 0.0/1.0 und Dubletten
        werden gefiltert, damit beide Belegungen (Start-Faktoren oder Grenz-Faktoren)
        funktionieren."""
        length = _pos(d.layout_length)
        if length <= 50.0:
            return ()
        raw = [_f(getattr(d.sector_start_factors, a), -1.0) for a in ("sector1", "sector2", "sector3")]
        bounds = []
        for f in raw:
            if 0.0 < f < 1.0:
                m = f * length
                if 5.0 < m < length - 5.0 and all(abs(m - b) > 5.0 for b in bounds):
                    bounds.append(m)
        bounds.sort()
        return tuple(bounds) if len(bounds) >= 2 else ()

    # ----- Hauptfunktion ---------------------------------------------------
    def read_sample(self):
        raw = self._read_raw()
        d = R3EShared.from_buffer_copy(raw)
        self.last_version = (int(d.version_major), int(d.version_minor))
        if int(d.version_major) == 0:
            raise RuntimeError("RaceRoom Shared Memory nicht aktiv (Spiel laeuft nicht oder schreibt noch nicht).")
        if int(d.version_major) != R3E_VERSION_MAJOR:
            raise RuntimeError(
                f"RaceRoom-API {int(d.version_major)}.{int(d.version_minor)} wird nicht unterstuetzt "
                f"(PitBoss R3E kennt {R3E_VERSION_MAJOR}.x). Bitte auf eine neuere PitBoss-R3E-Version aktualisieren.")
        self.layout_warning = self._layout_warning(d)
        n_cars = int(d.num_cars)
        if n_cars <= 0:
            raise RuntimeError("RaceRoom: keine aktiven Fahrzeuge (noch nicht in einer Session).")

        drivers = self._drivers(raw, d)
        ego_slot = int(d.vehicle_info.slot_id)
        ego_idx = -1
        for i, dr in enumerate(drivers):
            if int(dr.driver_info.slot_id) == ego_slot:
                ego_idx = i
                break

        self._detect_sectors(d)
        completed = _na_int(d.completed_laps, 0)
        state = int(d.lap_valid_state)
        invalid = (state in (1, 2)) if state >= 0 else (int(d.current_lap_valid) == 0)

        track = _txt(d.track_name)
        layout = _txt(d.layout_name)
        if layout and layout.lower() != track.lower():
            track = f"{track} - {layout}" if track else layout

        model_id = int(d.vehicle_info.model_id)
        class_id = int(d.vehicle_info.class_id)
        car_name = self.car_names.get(model_id) or (f"R3E Car {model_id}" if model_id > 0 else "")
        class_name = self.class_names.get(class_id) or (f"R3E Class {class_id}" if class_id > 0 else "")

        gear = int(d.gear)
        if gear < -1:
            gear = 0

        P = d.player
        pos = P.position
        wear = self._wear_pct(d, completed)

        def tire_temp(i, j):
            return _pos(d.tire_temp[i].current_temp[j])

        def brake_temp(i):
            return _pos(d.brake_temp[i].current_temp)

        # Gegner: Spotter-Positionen + Ueberholalarm-Abstaende
        opps, behind = [], []
        track_len = _pos(d.layout_length)
        my_dist = _pos(d.lap_distance)
        for i, dr in enumerate(drivers):
            if i == ego_idx:
                continue
            pit = int(dr.in_pitlane) == 1
            opps.append((int(dr.driver_info.slot_id), _f(dr.position.x), _f(dr.position.z), pit))
            if not pit and track_len > 1.0 and _f(dr.lap_distance, -1.0) >= 0.0:
                db = (my_dist - _f(dr.lap_distance)) % track_len
                if 0.5 < db < 400.0:
                    cid = int(dr.driver_info.class_id)
                    behind.append((int(dr.place), _txt(dr.driver_info.name),
                                   self.class_names.get(cid) or (f"R3E Class {cid}" if cid > 0 else ""), db))
        behind.sort(key=lambda e: e[3])
        behind = behind[:6]

        # Flaggen -> mGamePhase / mYellowFlagState / mFlag-Konvention des FlagOverlays
        fl = d.flags
        phase = _PHASE_MAP.get(int(d.session_phase), 0)
        if int(fl.checkered) == 1:
            phase = 8
        if int(fl.yellow) == 1:
            yellow_state = 1
        elif int(fl.white) == 1:
            yellow_state = 5
        else:
            yellow_state = 0
        player_flag = 6 if int(fl.blue) == 1 else 0

        dur = _pos(d.session_time_duration)
        rem = _pos(d.session_time_remaining)
        ve_cap = _f(d.virtual_energy_capacity, -1.0)
        ve_left = _f(d.virtual_energy_left, -1.0)
        has_vehicle = (int(d.control_type) == 0 and int(d.game_in_menus) != 1 and int(d.game_in_replay) != 1)
        sector_idx = {1: 1, 2: 2, 3: 0}.get(int(d.track_sector), 0)  # PitBoss: 0=S3, 1=S1, 2=S2
        ffb = max(-1.0, min(1.0, _f(P.steering_force_percentage) / 100.0))
        grip = [_unit(x) for x in d.tire_grip]
        dmg = self._damage_pct(d)
        bp = self._brake_norm(d)
        tw = self._tire_window(d)
        gap_leader = _f(d.lap_time_delta_leader, -1.0)

        kw = dict(
            timestamp=datetime.now().isoformat(timespec="milliseconds"),
            game_version=int(d.version_major) * 100 + int(d.version_minor),
            track=track,
            player_name=_txt(d.player_name),
            active_vehicles=n_cars,
            player_idx=max(ego_idx, 0),
            player_has_vehicle=has_vehicle,
            telem_id=ego_slot,
            scoring_id=ego_slot,
            vehicle_name=car_name,
            vehicle_model=car_name,
            vehicle_class=class_name,
            speed_kmh=_pos(d.car_speed) * 3.6,
            gear=gear,
            rpm=_pos(d.engine_rps) * _RPS_TO_RPM,
            fuel_l=_pos(d.fuel_left),
            fuel_capacity_l=_pos(d.fuel_capacity),
            throttle=_unit(d.throttle),
            brake=_unit(d.brake),
            steering=max(-1.0, min(1.0, _f(d.steer_input_raw))),
            input_throttle=_unit(d.throttle_raw),
            input_brake=_unit(d.brake_raw),
            input_clutch=_unit(d.clutch_raw),
            input_steering=max(-1.0, min(1.0, _f(d.steer_input_raw))),
            pos_x=_f(pos.x), pos_y=_f(pos.y), pos_z=_f(pos.z),
            lap_number=completed + 1,
            completed_laps=completed,
            lap_dist_m=my_dist,
            current_lap_time=_pos(d.lap_time_current_self),
            last_lap_time=_pos(d.lap_time_previous_self),
            best_lap_time=_pos(d.lap_time_best_self),
            lap_invalidated=bool(invalid),
            in_pits=int(d.in_pitlane) == 1,
            place=_na_int(d.position, 0),
            tire_fl_pressure_kpa=_pos(d.tire_pressure[0]), tire_fr_pressure_kpa=_pos(d.tire_pressure[1]),
            tire_rl_pressure_kpa=_pos(d.tire_pressure[2]), tire_rr_pressure_kpa=_pos(d.tire_pressure[3]),
            tire_fl_temp_l_c=tire_temp(0, 0), tire_fl_temp_c_c=tire_temp(0, 1), tire_fl_temp_r_c=tire_temp(0, 2),
            tire_fr_temp_l_c=tire_temp(1, 0), tire_fr_temp_c_c=tire_temp(1, 1), tire_fr_temp_r_c=tire_temp(1, 2),
            tire_rl_temp_l_c=tire_temp(2, 0), tire_rl_temp_c_c=tire_temp(2, 1), tire_rl_temp_r_c=tire_temp(2, 2),
            tire_rr_temp_l_c=tire_temp(3, 0), tire_rr_temp_c_c=tire_temp(3, 1), tire_rr_temp_r_c=tire_temp(3, 2),
            # R3E liefert keine Karkassentemperatur -> bewusst 0 statt eines erfundenen Naeherungswerts
            tire_fl_wear_pct=wear[0], tire_fr_wear_pct=wear[1], tire_rl_wear_pct=wear[2], tire_rr_wear_pct=wear[3],
            tire_fl_flat=int(d.tire_flatspot[0]) == 1, tire_fr_flat=int(d.tire_flatspot[1]) == 1,
            tire_rl_flat=int(d.tire_flatspot[2]) == 1, tire_rr_flat=int(d.tire_flatspot[3]) == 1,
            tire_fl_grip_fract=grip[0], tire_fr_grip_fract=grip[1], tire_rl_grip_fract=grip[2], tire_rr_grip_fract=grip[3],
            accel_lat_ms2=_f(d.local_acceleration.x),
            accel_long_ms2=_f(d.local_acceleration.z),
            session_type=_SESSION_MAP.get(int(d.session_type), 0),
            session_remaining_s=rem,
            session_current_et=max(0.0, dur - rem) if dur > 0.0 else 0.0,
            session_end_et=dur,
            sector_index=sector_idx,
            cur_sector1_s=_pos(d.sector_time_current_self[0]),
            cur_sector2_s=self._sec2(_pos(d.sector_time_current_self[0]), _pos(d.sector_time_current_self[1])),
            last_sector1_s=_pos(d.sector_time_previous_self[0]),
            last_sector2_s=self._sec2(_pos(d.sector_time_previous_self[0]), _pos(d.sector_time_previous_self[1])),
            best_sector1_s=_pos(d.sector_time_best_self[0]),
            best_sector2_s=self._sec2(_pos(d.sector_time_best_self[0]), _pos(d.sector_time_best_self[1])),
            brake_fl_temp_raw=brake_temp(0), brake_fr_temp_raw=brake_temp(1),
            brake_rl_temp_raw=brake_temp(2), brake_rr_temp_raw=brake_temp(3),
            max_rpm=_pos(d.max_engine_rps) * _RPS_TO_RPM,
            virtual_energy=(ve_left / ve_cap) if (ve_cap > 0.0 and ve_left >= 0.0) else 0.0,
            ffb_torque=ffb,
            steering_shaft_torque=_f(P.steering_force),
            pit_state=_na_int(d.pit_state, 0),
            speed_limiter=int(d.pit_limiter) == 1,
            num_pitstops=_na_int(d.num_pitstops, 0),
            gap_ahead_s=_gap(d.time_delta_front),
            gap_behind_s=_gap(d.time_delta_behind),
            opponents=tuple(opps),
            opponents_behind=tuple(behind),
            game_phase=phase,
            yellow_flag_state=yellow_state,
            player_flag=player_flag,
            rear_brake_bias=_pos(d.brake_bias),
            brake_fl_pressure=bp[0], brake_fr_pressure=bp[1], brake_rl_pressure=bp[2], brake_rr_pressure=bp[3],
            gap_leader_s=abs(gap_leader) if gap_leader > -0.5 else 0.0,
            abs_on=_na_int(d.aid_settings.abs, 0) >= 1,
            dmg_engine_pct=dmg[0], dmg_transmission_pct=dmg[1], dmg_aero_pct=dmg[2], dmg_suspension_pct=dmg[3],
            tire_temp_cold_c=tw[0], tire_temp_opt_c=tw[1], tire_temp_hot_c=tw[2],
            pit_window_status=_na_int(d.pit_window_status, -1),
            pit_elapsed_s=_pos(d.pit_elapsed_time, -1.0),
            pit_total_s=_pos(d.pit_total_duration, -1.0),
            # 0.2.20: zusaetzliche Telemetrie-Kanaele fuer CSV/Analyse
            g_force_lat=_f(P.local_g_force.x),
            g_force_long=_f(P.local_g_force.z),
            heading_deg=math.degrees(_f(P.orientation.yaw)) % 360.0,
            velocity_lat_ms=_f(P.local_velocity.x),
            velocity_long_ms=_f(P.local_velocity.z),
            engine_torque_nm=_f(P.engine_torque),
            tc_on=_na_int(d.aid_settings.tc, 0) >= 1,
            esp_on=_na_int(d.aid_settings.esp, 0) >= 1,
            track_length_m=_pos(d.layout_length),          # 0.2.9: layout_length aus dem Spiel
            sector_bounds_m=self._sector_bounds_m(d),      # 0.2.9: offizielle Sektorgrenzen in m
        )
        return self.Sample(**kw)


# ---------------------------------------------------------------------------
# Demo-Frame (Selbsttest / Integrationstest) + CLI
# ---------------------------------------------------------------------------
def make_demo_shared(n_cars: int = 4) -> "R3EShared":
    """Synthetischer, plausibler Speicherblock (Spiel laeuft, Spieler faehrt Runde 3)."""
    d = R3EShared()
    d.version_major, d.version_minor = R3E_VERSION_MAJOR, R3E_VERSION_MINOR_KNOWN
    d.all_drivers_offset = R3EShared.num_cars.offset
    d.driver_data_size = ctypes.sizeof(R3EDriverData)
    d.game_mode = 3
    d.track_name = (c_ubyte * 64)(*b"Nuerburgring")
    d.layout_name = (c_ubyte * 64)(*b"Grand Prix")
    d.layout_length = 5148.0
    # 0.2.9: offizielle Sektorgrenzen als Start-Faktoren (S2 ab 35 %, S3 ab 68 %)
    d.sector_start_factors.sector1 = 0.0
    d.sector_start_factors.sector2 = 0.35
    d.sector_start_factors.sector3 = 0.68
    d.session_type = 2
    d.session_phase = 5
    d.session_time_duration = 1800.0
    d.session_time_remaining = 1500.0
    d.position = 2
    d.completed_laps = 2
    d.current_lap_valid = 1
    d.lap_valid_state = 0
    d.track_sector = 2
    d.lap_distance = 1800.0
    d.lap_time_current_self = 52.4
    d.lap_time_previous_self = 118.250
    d.lap_time_best_self = 117.900
    for i, v in enumerate((38.1, 79.4, 118.25)):  # kumulativ: S1, S1+S2, Runde
        d.sector_time_previous_self[i] = v
        d.sector_time_best_self[i] = v - 0.3
    d.sector_time_current_self[0] = 38.6
    d.sector_time_current_self[1] = 52.4
    d.time_delta_front = 1.35
    d.time_delta_behind = 0.82
    d.vehicle_info.slot_id = 7
    d.vehicle_info.model_id = 252
    d.vehicle_info.class_id = 255
    d.player_name = (c_ubyte * 64)(*b"Marcel")
    d.control_type = 0
    d.car_speed = 55.0
    d.engine_rps = 6000.0 / _RPS_TO_RPM
    d.max_engine_rps = 7500.0 / _RPS_TO_RPM
    d.gear = 4
    d.fuel_left, d.fuel_capacity = 42.5, 80.0
    d.throttle = d.throttle_raw = 0.8
    d.brake = d.brake_raw = 0.0
    d.clutch = d.clutch_raw = 0.0
    d.steer_input_raw = -0.12
    d.brake_bias = 0.56
    d.pit_limiter = 0
    d.pit_state = 0
    d.num_pitstops = 1
    for i in range(4):
        d.tire_wear[i] = 0.91 - 0.01 * i
        d.tire_pressure[i] = 165.0 + i
        d.tire_grip[i] = 0.95
        d.tire_flatspot[i] = 0
        for j in range(3):
            d.tire_temp[i].current_temp[j] = 80.0 + 2 * j + i
        d.tire_temp[i].cold_temp, d.tire_temp[i].optimal_temp, d.tire_temp[i].hot_temp = 70.0, 90.0, 105.0
        d.brake_temp[i].current_temp = 420.0 + 10 * i
        d.brake_temp[i].optimal_temp = 500.0
        d.brake_pressure[i] = 3.0
    d.local_acceleration.x, d.local_acceleration.z = 7.5, -2.0
    d.player.position.x, d.player.position.y, d.player.position.z = 100.0, 5.0, -250.0
    d.player.steering_force_percentage = 35.0
    d.player.steering_force = 12.0
    d.virtual_energy_left, d.virtual_energy_capacity = 60.0, 100.0
    d.num_cars = n_cars
    for i in range(n_cars):
        dr = d.all_drivers_data_1[i]
        dr.driver_info.slot_id = 7 if i == 1 else 20 + i
        dr.driver_info.class_id = 255
        nm = f"Fahrer {i}".encode()
        dr.driver_info.name = (c_ubyte * 64)(*nm)
        dr.place = i + 1
        dr.lap_distance = 1800.0 + (i - 1) * 60.0
        dr.position.x, dr.position.z = 100.0 + 4 * i, -250.0 - 4 * i
        dr.in_pitlane = 1 if i == 3 else 0
    return d


class _FakeSample:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _selftest() -> int:
    ok = bad = 0

    def check(name, cond, info=""):
        nonlocal ok, bad
        if cond:
            ok += 1
        else:
            bad += 1
            print(f"  FEHLER: {name} {info}")

    d = make_demo_shared()
    rd = R3EReader(_FakeSample, raw_provider=lambda: bytes(d), env={})
    s = rd.read_sample()
    check("Version", rd.last_version == (3, 5))
    check("Track+Layout", s.track == "Nuerburgring - Grand Prix", s.track)
    check("Speed km/h", abs(s.speed_kmh - 198.0) < 1e-3, s.speed_kmh)
    check("RPM", abs(s.rpm - 6000.0) < 0.5 and abs(s.max_rpm - 7500.0) < 0.5, (s.rpm, s.max_rpm))
    check("Gang", s.gear == 4)
    check("Fuel", abs(s.fuel_l - 42.5) < 1e-6 and abs(s.fuel_capacity_l - 80.0) < 1e-6)
    check("Runde/Completed", s.lap_number == 3 and s.completed_laps == 2)
    check("Zeiten", abs(s.last_lap_time - 118.25) < 1e-4 and abs(s.best_lap_time - 117.9) < 1e-4)
    check("Lap gueltig", s.lap_invalidated is False)
    check("Sektor-Mapping S2->2", s.sector_index == 2)
    check("Sektorgrenzen aus Spiel", len(getattr(s, "sector_bounds_m", ())) == 2
          and abs(s.sector_bounds_m[0] - 1801.8) < 1.0 and abs(s.sector_bounds_m[1] - 3500.6) < 1.0, s.sector_bounds_m)
    check("Streckenlaenge aus Spiel", abs(getattr(s, "track_length_m", 0.0) - 5148.0) < 0.5, s.track_length_m)
    check("S2 kumulativ", abs(s.last_sector2_s - 79.4) < 1e-4, s.last_sector2_s)
    check("Session Rennen", s.session_type == 10 and s.game_phase == 5)
    check("Restzeit", abs(s.session_remaining_s - 1500.0) < 1e-3 and abs(s.session_current_et - 300.0) < 1e-3)
    check("Auto-/Klassenname", s.vehicle_name.startswith("Aquila") or s.vehicle_name == "R3E Car 252", s.vehicle_name)
    check("Verschleiss Rest-% (1.0=neu)", abs(s.tire_fl_wear_pct - 91.0) < 0.01, s.tire_fl_wear_pct)
    check("Karkasse nicht gesetzt (Default 0)", not hasattr(s, "tire_fl_carcass_c") or s.tire_fl_carcass_c == 0.0)
    check("Reifentemp links/mitte/rechts", s.tire_fl_temp_l_c == 80.0 and s.tire_fl_temp_c_c == 82.0 and s.tire_fl_temp_r_c == 84.0)
    check("Pedale", abs(s.throttle - 0.8) < 1e-6 and s.brake == 0.0)
    check("Lenkung", abs(s.steering + 0.12) < 1e-6)
    check("Boxenstopps", s.num_pitstops == 1)
    check("Platz", s.place == 2)
    check("Gaps", abs(s.gap_ahead_s - 1.35) < 1e-6 and abs(s.gap_behind_s - 0.82) < 1e-6)
    check("Gegner ohne Ego", len(s.opponents) == 3 and all(o[0] != 7 for o in s.opponents), s.opponents)
    check("Hintermann <400 m, nicht Box", len(s.opponents_behind) == 1 and s.opponents_behind[0][0] == 1
          and abs(s.opponents_behind[0][3] - 60.0) < 1e-3, s.opponents_behind)
    check("VE-Anteil", abs(s.virtual_energy - 0.6) < 1e-6)
    check("FFB normiert", abs(s.ffb_torque - 0.35) < 1e-6)
    check("Fahrer im Auto", s.player_has_vehicle is True)
    check("Flagge keine", s.yellow_flag_state == 0 and s.player_flag == 0)

    # Flaggen
    d2 = make_demo_shared(); d2.flags.yellow = 1
    check("Gelb -> yellow_flag_state 1", R3EReader(_FakeSample, raw_provider=lambda: bytes(d2), env={}).read_sample().yellow_flag_state == 1)
    d3 = make_demo_shared(); d3.flags.blue = 1
    check("Blau -> player_flag 6", R3EReader(_FakeSample, raw_provider=lambda: bytes(d3), env={}).read_sample().player_flag == 6)
    d4 = make_demo_shared(); d4.flags.checkered = 1
    check("Ziel -> game_phase 8", R3EReader(_FakeSample, raw_provider=lambda: bytes(d4), env={}).read_sample().game_phase == 8)

    # Ungueltige Runde
    d5 = make_demo_shared(); d5.lap_valid_state = 1
    check("Runde ungueltig (state 1)", R3EReader(_FakeSample, raw_provider=lambda: bytes(d5), env={}).read_sample().lap_invalidated is True)

    # Einzel-Sektorzeiten -> auf kumulativ umgerechnet
    d6 = make_demo_shared()
    for i, v in enumerate((38.1, 41.3, 38.85)):  # einzeln, Summe = 118.25
        d6.sector_time_previous_self[i] = v
    s6 = R3EReader(_FakeSample, raw_provider=lambda: bytes(d6), env={}).read_sample()
    check("Einzel-Sektoren -> S2 kumulativ", abs(s6.last_sector2_s - 79.4) < 1e-3, s6.last_sector2_s)

    # Verschleiss invertiert (0.0 = neu) in Runde 0
    d7 = make_demo_shared(); d7.completed_laps = 0
    for i in range(4):
        d7.tire_wear[i] = 0.02
    s7 = R3EReader(_FakeSample, raw_provider=lambda: bytes(d7), env={}).read_sample()
    check("Verschleiss 0.0=neu erkannt", abs(s7.tire_fl_wear_pct - 98.0) < 0.01, s7.tire_fl_wear_pct)
    s7b = R3EReader(_FakeSample, raw_provider=lambda: bytes(d7), env={"PITBOSS_R3E_WEAR": "new1"}).read_sample()
    check("Override new1", abs(s7b.tire_fl_wear_pct - 2.0) < 0.01, s7b.tire_fl_wear_pct)

    # Fehlerfaelle
    for label, mutate, needle in (
        ("Spiel aus", lambda x: setattr(x, "version_major", 0), "nicht aktiv"),
        ("Keine Autos", lambda x: setattr(x, "num_cars", 0), "keine aktiven"),
    ):
        dd = make_demo_shared(); mutate(dd)
        try:
            R3EReader(_FakeSample, raw_provider=lambda: bytes(dd), env={}).read_sample()
            check(f"Fehlerfall {label}", False, "(keine Exception)")
        except RuntimeError as e:
            check(f"Fehlerfall {label}", needle in str(e), str(e))
    # Nullspeicher (Mapping existiert, Spiel schreibt nicht)
    try:
        R3EReader(_FakeSample, raw_provider=lambda: bytes(ctypes.sizeof(R3EShared)), env={}).read_sample()
        check("Nullspeicher", False)
    except RuntimeError:
        check("Nullspeicher", True)

    # Neue Felder: ABS, Schaden, Reifenfenster, Boxenstopp, Bremsdruck
    dA = make_demo_shared(); dA.aid_settings.abs = 5
    check("ABS aktiv -> abs_on", R3EReader(_FakeSample, raw_provider=lambda: bytes(dA), env={}).read_sample().abs_on is True)
    dB = make_demo_shared(); dB.aid_settings.abs = -1
    check("ABS N/A -> aus", R3EReader(_FakeSample, raw_provider=lambda: bytes(dB), env={}).read_sample().abs_on is False)
    dC = make_demo_shared()
    dC.car_damage.engine, dC.car_damage.transmission, dC.car_damage.aerodynamics, dC.car_damage.suspension = 1.0, 1.0, 0.7, -1.0
    rC = R3EReader(_FakeSample, raw_provider=lambda: bytes(dC), env={})
    sC = rC.read_sample()
    check("Schaden 1.0=heil: aero 30 %", abs(sC.dmg_aero_pct - 30.0) < 1e-3 and sC.dmg_engine_pct == 0.0, (sC.dmg_aero_pct, sC.dmg_engine_pct))
    check("Schaden N/A = -1", sC.dmg_suspension_pct == -1.0)
    dD = make_demo_shared()
    dD.car_damage.engine, dD.car_damage.transmission, dD.car_damage.aerodynamics, dD.car_damage.suspension = 0.0, 0.0, 0.0, 0.0
    sD = R3EReader(_FakeSample, raw_provider=lambda: bytes(dD), env={}).read_sample()
    check("Schaden 0.0=heil erkannt", sD.dmg_engine_pct == 0.0, sD.dmg_engine_pct)
    sD2 = R3EReader(_FakeSample, raw_provider=lambda: bytes(dD), env={"PITBOSS_R3E_DAMAGE": "intact1"}).read_sample()
    check("Override intact1", abs(sD2.dmg_engine_pct - 100.0) < 1e-3, sD2.dmg_engine_pct)
    check("Reifenfenster aus Spiel", s.tire_temp_cold_c > 0 and s.tire_temp_opt_c > s.tire_temp_cold_c and s.tire_temp_hot_c > s.tire_temp_opt_c,
          (s.tire_temp_cold_c, s.tire_temp_opt_c, s.tire_temp_hot_c))
    check("Pit-Felder vorhanden", hasattr(s, "pit_window_status") and hasattr(s, "pit_elapsed_s") and hasattr(s, "pit_total_s"))
    dE = make_demo_shared()
    rE = R3EReader(_FakeSample, raw_provider=lambda: bytes(dE), env={})
    for kn in (0.0, 2.0, 4.0):
        for i in range(4):
            dE.brake_pressure[i] = kn
        sE = rE.read_sample()
    check("Bremsdruck normiert 0..1", abs(sE.brake_fl_pressure - 1.0) < 1e-6)
    for i in range(4):
        dE.brake_pressure[i] = 1.0
    check("Bremsdruck relativ zum Peak", abs(rE.read_sample().brake_fl_pressure - 0.25) < 1e-6)

    # Windows-Pfad: nur OEFFNEN, nie anlegen (Fake-kernel32)
    class _FakeK32:
        def __init__(self, buf, exists=True):
            self.buf, self.exists, self.calls = buf, exists, []
        def OpenFileMappingW(self, acc, inh, name):
            self.calls.append(("Open", acc, name)); return 1 if self.exists else 0
        def MapViewOfFile(self, h, acc, hi, lo, n):
            self.calls.append(("Map", acc)); return ctypes.addressof(self.buf)
        def VirtualQuery(self, addr, mbi_ref, n):
            mbi = ctypes.cast(mbi_ref, ctypes.POINTER(_MemoryBasicInformation)).contents
            mbi.RegionSize = ctypes.sizeof(self.buf); return n
        def UnmapViewOfFile(self, v): self.calls.append(("Unmap",)); return 1
        def CloseHandle(self, h): self.calls.append(("Close",)); return 1
        def CreateFileMappingW(self, *a): self.calls.append(("CREATE!",)); return 1
    buf = (ctypes.c_ubyte * ctypes.sizeof(R3EShared)).from_buffer_copy(bytes(d))
    fk = _FakeK32(buf)
    sw = R3EReader(_FakeSample, env={}, k32=fk).read_sample()
    kinds = [c[0] for c in fk.calls]
    check("Win: Open->Map->Unmap->Close, schreibgeschuetzt", kinds == ["Open", "Map", "Unmap", "Close"] and fk.calls[0][1] == 4 and fk.calls[0][2] == "$R3E", fk.calls)
    check("Win: nie CreateFileMapping", "CREATE!" not in kinds)
    check("Win: Daten korrekt", sw.gear == 4 and abs(sw.speed_kmh - 198.0) < 1e-3)
    try:
        R3EReader(_FakeSample, env={}, k32=_FakeK32(buf, exists=False)).read_sample()
        check("Win: Spiel aus -> Fehler", False)
    except RuntimeError as e:
        check("Win: Spiel aus -> Fehler ohne Anlegen", "nicht gefunden" in str(e), str(e))

    # Layout-/Versionswaechter
    check("Layout passt (3.5)", rd.layout_warning == "", rd.layout_warning)
    dm = make_demo_shared(); dm.version_minor = 6
    rm = R3EReader(_FakeSample, raw_provider=lambda: bytes(dm), env={}); rm.read_sample()
    check("Minor 6 -> Warnung, laeuft weiter", "neuer als bekannt" in rm.layout_warning, rm.layout_warning)
    ds = make_demo_shared(); ds.driver_data_size = ctypes.sizeof(R3EDriverData) + 8
    rs = R3EReader(_FakeSample, raw_provider=lambda: bytes(ds), env={}); rs.read_sample()
    check("Fahrerblock-Abweichung erkannt", "Fahrerblock" in rs.layout_warning, rs.layout_warning)
    dj = make_demo_shared(); dj.version_major = 4
    try:
        R3EReader(_FakeSample, raw_provider=lambda: bytes(dj), env={}).read_sample(); check("Major 4 -> Fehler", False)
    except RuntimeError as e:
        check("Major 4 -> klare Meldung", "nicht unterstuetzt" in str(e), str(e))

    # Struktur-Plausibilitaet
    check("sizeof R3EShared", ctypes.sizeof(R3EShared) == 43996, ctypes.sizeof(R3EShared))
    check("Fahrerliste direkt hinter num_cars", R3EShared.all_drivers_data_1.offset == R3EShared.num_cars.offset + 4)

    print(f"raceroom_sm selftest: {ok} ok, {bad} fehler")
    return 0 if bad == 0 else 1


def _probe_text(rd: "R3EReader", d: "R3EShared") -> str:
    P = d.player
    lines = [
        f"Version        : {d.version_major}.{d.version_minor} (bekannt: {R3E_VERSION_MAJOR}.{R3E_VERSION_MINOR_KNOWN})  Layout: {rd._layout_warning(d) or 'passt zu r3e.h 3.5'}",
        f"Spiel          : menus={d.game_in_menus} pause={d.game_paused} replay={d.game_in_replay} vr={d.game_using_vr} control={d.control_type}",
        f"Strecke        : {_txt(d.track_name)} / {_txt(d.layout_name)}  len={d.layout_length:.0f} m",
        f"Session        : typ={d.session_type} phase={d.session_phase} dauer={d.session_time_duration:.0f}s rest={d.session_time_remaining:.0f}s",
        f"Auto           : model_id={d.vehicle_info.model_id} -> {rd.car_names.get(int(d.vehicle_info.model_id), '?')} | "
        f"class_id={d.vehicle_info.class_id} -> {rd.class_names.get(int(d.vehicle_info.class_id), '?')}",
        f"Reifenverschl. : roh={[round(float(x), 3) for x in d.tire_wear]}  (1.0=neu? 0.0=neu? -> PITBOSS_R3E_WEAR=new1|new0)  "
        f"erkannt={'1.0=neu' if rd._wear_new_is_one in (None, True) else '0.0=neu'}",
        f"Sektoren prev  : {[round(float(x), 3) for x in d.sector_time_previous_self]}  lap_prev={d.lap_time_previous_self:.3f}  "
        f"kumulativ={rd._sectors_cumulative} (None=noch unbekannt, bis eine volle Runde vorliegt)",
        f"Sektoren cur   : {[round(float(x), 3) for x in d.sector_time_current_self]}  lap_cur={d.lap_time_current_self:.3f}",
        f"Sektorgrenzen  : factors=({d.sector_start_factors.sector1:.3f}, {d.sector_start_factors.sector2:.3f}, "
        f"{d.sector_start_factors.sector3:.3f}) -> innere Grenzen m={[round(b) for b in rd._sector_bounds_m(d)]} "
        f"(leer = Spiel liefert keine gueltigen Werte, 50-m-Raster bleibt Grundlage)",
        f"Lenkkraft      : steering_force={P.steering_force:.3f}  percentage={P.steering_force_percentage:.3f}",
        f"Schaden        : engine={d.car_damage.engine:.2f} trans={d.car_damage.transmission:.2f} aero={d.car_damage.aerodynamics:.2f} susp={d.car_damage.suspension:.2f}",
        f"Flags          : yellow={d.flags.yellow} blue={d.flags.blue} white={d.flags.white} checkered={d.flags.checkered} black={d.flags.black}",
        f"Pit            : state={d.pit_state} in_pitlane={d.in_pitlane} limiter={d.pit_limiter} stops={d.num_pitstops} window={d.pit_window_status} ({d.pit_window_start}-{d.pit_window_end}) elapsed={d.pit_elapsed_time:.1f} total={d.pit_total_duration:.1f}",
        f"Schaden-Richtung: erkannt={'1.0=heil' if rd._dmg_intact_is_one in (None, True) else '0.0=heil'} (Override PITBOSS_R3E_DAMAGE=intact1|intact0)",
        f"Fahrhilfen     : abs={d.aid_settings.abs} (-1 n/a, 0 aus, 1 an, 5 aktiv) tc={d.aid_settings.tc} esp={d.aid_settings.esp}",
        f"Reifenfenster  : kalt/optimal/heiss FL={d.tire_temp[0].cold_temp:.0f}/{d.tire_temp[0].optimal_temp:.0f}/{d.tire_temp[0].hot_temp:.0f} C  Bremse FL opt={d.brake_temp[0].optimal_temp:.0f} C",
        f"Bremsdruck     : roh(kN)={[round(float(x), 3) for x in d.brake_pressure]}  Gap Leader={d.lap_time_delta_leader:.2f}s",
        f"Fahrerliste    : num_cars={d.num_cars} offset={d.all_drivers_offset} stride={d.driver_data_size} (erwartet {ctypes.sizeof(R3EDriverData)})",
    ]
    return "\n".join(lines)


def _main(argv) -> int:
    if "--selftest" in argv:
        return _selftest()
    rd = R3EReader(_FakeSample)
    if "--probe" in argv:
        try:
            d = rd.read_object()
        except Exception as e:  # noqa: BLE001
            print(f"[FEHLER] {e}")
            return 2
        if int(d.version_major) != R3E_VERSION_MAJOR:
            print("[FEHLER] $R3E ist leer/inaktiv - RaceRoom starten und in eine Session gehen.")
            return 2
        try:
            rd.read_sample()  # Heuristiken (Verschleiss/Sektoren) einmal laufen lassen
        except Exception:
            pass
        print(_probe_text(rd, d))
        return 0
    if "--watch" in argv:
        print("RaceRoom-Livezeile (Strg+C beendet) ...")
        try:
            while True:
                try:
                    s = rd.read_sample()
                    print(f"\r{s.track[:28]:28s} | {s.vehicle_name[:22]:22s} | {s.speed_kmh:6.1f} km/h | G{s.gear:>2} | "
                          f"{s.rpm:6.0f} rpm | Lap {s.lap_number:>3} {s.current_lap_time:7.2f}s | Fuel {s.fuel_l:5.1f} L   ", end="", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"\r[wartet] {str(e)[:100]:100s}", end="", flush=True)
                time.sleep(0.5)
        except KeyboardInterrupt:
            print()
            return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
