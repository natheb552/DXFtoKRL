"""Einstellungen (werden als JSON im Benutzerprofil gespeichert)."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class GeneralSettings:
    program_name: str = "DXF_PROG"
    base_no: int = 1
    tool_no: int = 1
    # Werkzeugausrichtung in BASE (KUKA: Werkzeug-X = Stoßrichtung; B=90 -> zeigt nach -Z)
    a: float = 0.0
    b: float = 90.0
    c: float = 0.0
    safe_z: float = 20.0         # absolute Sicherheitshöhe in BASE
    surface_z: float = 0.0       # Werkstückoberfläche in BASE
    travel_speed: float = 6000.0  # mm/min, Leerfahrten
    apo_cdis: float = 0.5        # Überschleifabstand mm
    ptp_vel: int = 20            # % für PTP
    use_home: bool = True
    origin_mode: str = "dxf"     # "dxf" | "bbox_min"
    offset_x: float = 0.0
    offset_y: float = 0.0
    chain_tol: float = 0.05
    flatten_tol: float = 0.02
    rotate_start: bool = True


@dataclass
class MillingSettings:
    spindle_out: int = 0         # 0 = kein Ausgang
    spindle_delay: float = 3.0   # s Hochlaufzeit
    feed: float = 600.0          # mm/min
    plunge_feed: float = 150.0   # mm/min
    depth: float = 2.0           # mm Gesamttiefe
    step_down: float = 1.0       # mm je Zustellung (0 = eine Zustellung)
    approach: float = 2.0        # mm über Oberfläche im Eilgang


@dataclass
class PlasmaSettings:
    torch_out: int = 0           # Ausgang Brenner ein
    arc_ok_in: int = 0           # Eingang "Lichtbogen steht" (0 = nicht vorhanden)
    arc_timeout: float = 3.0     # s
    timer_no: int = 1            # $TIMER[] für Timeout
    thc_out: int = 0             # Ausgang Höhenregelung freigeben (0 = nicht vorhanden)
    pierce_height: float = 4.0   # mm über Oberfläche
    pierce_delay: float = 0.5    # s
    cut_height: float = 1.5      # mm über Oberfläche
    feed: float = 2000.0         # mm/min
    plunge_feed: float = 300.0   # mm/min von Durchstech- auf Schneidhöhe
    post_delay: float = 0.0      # s nach Brenner aus


@dataclass
class Settings:
    profile: str = "plasma"      # "plasma" | "milling"
    general: GeneralSettings = field(default_factory=GeneralSettings)
    milling: MillingSettings = field(default_factory=MillingSettings)
    plasma: PlasmaSettings = field(default_factory=PlasmaSettings)
    last_dir: str = ""
    export_dir: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        s = cls()
        if not isinstance(d, dict):
            return s
        for key in ("profile", "last_dir", "export_dir"):
            if isinstance(d.get(key), str):
                setattr(s, key, d[key])
        for key in ("general", "milling", "plasma"):
            _fill(getattr(s, key), d.get(key))
        if s.profile not in ("plasma", "milling"):
            s.profile = "plasma"
        return s


def _fill(obj, data) -> None:
    if not isinstance(data, dict):
        return
    for f in fields(obj):
        if f.name not in data:
            continue
        cur = getattr(obj, f.name)
        val = data[f.name]
        try:
            if isinstance(cur, bool):
                val = bool(val)
            elif isinstance(cur, int):
                val = int(val)
            elif isinstance(cur, float):
                val = float(val)
            elif isinstance(cur, str):
                val = str(val)
        except (TypeError, ValueError):
            continue
        setattr(obj, f.name, val)


def config_path() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "DXFtoKRL" / "settings.json"


def load_settings(path: Path | None = None) -> Settings:
    path = path or config_path()
    try:
        return Settings.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return Settings()


def save_settings(s: Settings, path: Path | None = None) -> None:
    path = path or config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(s.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
