"""
fusionsolar_lib.py — Pure Python module, NO pyscript globals.
Imported by fusionsolar.py and called via task.executor.

Do NOT use: log.*, state.*, hass.*, task.*, @time_trigger, etc.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import json
import requests


@dataclass
class FusionSolarResult:
    ts_utc: str
    plant_dn: str
    status: str = "ok"
    error: Optional[str] = None
    pv_power_kw: Optional[float] = None
    battery_soc_percent: Optional[float] = None
    battery_power_kw: Optional[float] = None
    battery_charge_kw: Optional[float] = None
    battery_discharge_kw: Optional[float] = None
    grid_power_kw: Optional[float] = None
    grid_import_kw: Optional[float] = None
    grid_export_kw: Optional[float] = None
    load_power_kw: Optional[float] = None
    daily_energy_kwh: Optional[float] = None
    monthly_energy_kwh: Optional[float] = None
    yearly_energy_kwh: Optional[float] = None
    total_energy_kwh: Optional[float] = None
    raw: Optional[Dict[str, Any]] = None
    logs: List[str] = field(default_factory=list)


def _to_float(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        v = value.strip().replace(",", ".")
        if v in ("", "--", "-", "null", "None", "nan"):
            return None
        for suffix in ("kWh", "KWh", "kw", "kW", "W", "%"):
            if v.endswith(suffix):
                v = v[: -len(suffix)].strip()
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _find_by_key_contains(obj, candidates):
    cand = [c.lower().replace("_", "").replace("-", "") for c in candidates]
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k).lower().replace("_", "").replace("-", "")
            if any(c in key for c in cand):
                val = _to_float(v)
                if val is not None:
                    return val
        for v in obj.values():
            val = _find_by_key_contains(v, candidates)
            if val is not None:
                return val
    elif isinstance(obj, list):
        for item in obj:
            val = _find_by_key_contains(item, candidates)
            if val is not None:
                return val
    return None


def _poll_raw(base_url, station_dn, session, timeout, logs):
    endpoints = {
        "energy_flow":      ("GET", "/rest/pvms/web/station/v1/overview/energy-flow"),
        "energy_balance":   ("GET", "/rest/pvms/web/station/v1/overview/energy-balance"),
        "station_real_kpi": ("GET", "/rest/pvms/web/station/v1/overview/station-real-kpi"),
        "station_detail":   ("GET", "/rest/pvms/web/station/v1/overview/station-detail"),
    }
    logs.append(f"INFO poll {len(endpoints)} endpoints pour station={station_dn}")
    raw = {}
    ok_count = 0
    for name, (method, path) in endpoints.items():
        url = base_url + path
        try:
            r = session.request(method, url, params={"stationDn": station_dn}, timeout=timeout)
            logs.append(f"DEBUG HTTP {r.status_code} ({len(r.content)}B) {path}")
            if r.status_code in (401, 403):
                raise RuntimeError(f"Cookie rejeté HTTP {r.status_code} sur {path} — recapturer dans Edge/Chrome")
            r.raise_for_status()
            raw[name] = r.json()
            ok_count += 1
            logs.append(f"DEBUG endpoint '{name}' OK")
        except Exception as e:
            raw[name] = {"_error": str(e)}
            logs.append(f"WARNING endpoint '{name}' ERREUR: {e}")
    logs.append(f"INFO poll terminé: {ok_count}/{len(endpoints)} réussis")
    return raw


def _normalize(raw, station_dn, logs):
    pv_kw         = _find_by_key_contains(raw, ["pvPower", "productPower", "productionPower", "realTimePower", "activePower"])
    battery_soc   = _find_by_key_contains(raw, ["batterySoc", "stateOfCharge", "soc"])
    battery_power = _find_by_key_contains(raw, ["batteryPower", "chargeDischargePower", "chargePower", "dischargePower"])
    grid_power    = _find_by_key_contains(raw, ["gridPower", "meterPower", "onGridPower", "disGridPower"])
    load_power    = _find_by_key_contains(raw, ["loadPower", "usePower", "consumptionPower"])
    daily         = _find_by_key_contains(raw, ["dailyEnergy", "dayEnergy", "totalCurrentDayEnergy", "totalProductPower"])
    monthly       = _find_by_key_contains(raw, ["monthEnergy", "monthlyEnergy", "totalCurrentMonthEnergy"])
    yearly        = _find_by_key_contains(raw, ["yearEnergy", "yearlyEnergy", "totalCurrentYearEnergy"])
    total         = _find_by_key_contains(raw, ["cumulativeEnergy", "totalEnergy", "lifetimeEnergy"])

    logs.append(
        f"DEBUG valeurs extraites: pv={pv_kw}kW soc={battery_soc}% bat={battery_power}kW "
        f"grid={grid_power}kW load={load_power}kW daily={daily}kWh monthly={monthly}kWh "
        f"yearly={yearly}kWh total={total}kWh"
    )
    if pv_kw is None:
        logs.append("WARNING pv_power_kw est None — clé introuvable dans le payload")
    if battery_soc is None:
        logs.append("WARNING battery_soc_percent est None — batterie non détectée")
    if grid_power is None:
        logs.append("WARNING grid_power_kw est None — compteur réseau non détecté")

    battery_charge_kw    = max(-battery_power, 0.0) if battery_power is not None else None
    battery_discharge_kw = max(battery_power, 0.0)  if battery_power is not None else None
    grid_import_kw       = max(-grid_power, 0.0)    if grid_power is not None else None
    grid_export_kw       = max(grid_power, 0.0)     if grid_power is not None else None

    errors = {k: v.get("_error") for k, v in raw.items() if isinstance(v, dict) and v.get("_error")}
    status = "ok"
    err = None
    if errors and len(errors) == len(raw):
        status = "error"
        err = json.dumps(errors, ensure_ascii=False)
        logs.append(f"ERROR tous les endpoints ont échoué: {err}")
    elif errors:
        status = "partial"
        err = json.dumps(errors, ensure_ascii=False)
        logs.append(f"WARNING status=partial, endpoints en erreur: {list(errors.keys())}")
    else:
        logs.append("DEBUG normalisation OK, status=ok")

    return FusionSolarResult(
        ts_utc=datetime.now(timezone.utc).isoformat(),
        plant_dn=station_dn,
        status=status,
        error=err,
        pv_power_kw=pv_kw,
        battery_soc_percent=battery_soc,
        battery_power_kw=battery_power,
        battery_charge_kw=battery_charge_kw,
        battery_discharge_kw=battery_discharge_kw,
        grid_power_kw=grid_power,
        grid_import_kw=grid_import_kw,
        grid_export_kw=grid_export_kw,
        load_power_kw=load_power,
        daily_energy_kwh=daily,
        monthly_energy_kwh=monthly,
        yearly_energy_kwh=yearly,
        total_energy_kwh=total,
        raw=raw,
        logs=logs,
    )


def fetch(config):
    """
    Entry point called via task.executor from pyscript.
    Returns a plain dict (not a dataclass) so pyscript can call .get() on it.
    """
    logs = []
    cookie = config["cookie"]
    if not cookie or cookie == "PASTE_EDGE_NETWORK_COOKIE_HERE":
        raise RuntimeError("FusionSolar cookie manquant — éditer /config/pyscript/fusionsolar.py et coller le Cookie header")

    logs.append(f"DEBUG cookie présent ({len(cookie)} caractères)")
    base_url = config["base_url"].rstrip("/")
    station_dn = config["station_dn"]

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36 Edg/126.0",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Cookie": cookie,
        "Referer": config.get("referer", base_url + "/"),
        "Origin": base_url,
        "X-Requested-With": "XMLHttpRequest",
    })
    logs.append(f"DEBUG client HTTP initialisé pour {base_url}")

    raw = _poll_raw(base_url, station_dn, session, 20, logs)
    result = _normalize(raw, station_dn, logs)

    # Return plain dict — pyscript can call .get() on it safely
    return {
        "ts_utc":               result.ts_utc,
        "plant_dn":             result.plant_dn,
        "status":               result.status,
        "error":                result.error,
        "pv_power_kw":          result.pv_power_kw,
        "battery_soc_percent":  result.battery_soc_percent,
        "battery_power_kw":     result.battery_power_kw,
        "battery_charge_kw":    result.battery_charge_kw,
        "battery_discharge_kw": result.battery_discharge_kw,
        "grid_power_kw":        result.grid_power_kw,
        "grid_import_kw":       result.grid_import_kw,
        "grid_export_kw":       result.grid_export_kw,
        "load_power_kw":        result.load_power_kw,
        "daily_energy_kwh":     result.daily_energy_kwh,
        "monthly_energy_kwh":   result.monthly_energy_kwh,
        "yearly_energy_kwh":    result.yearly_energy_kwh,
        "total_energy_kwh":     result.total_energy_kwh,
        "logs":                 result.logs,
    }
