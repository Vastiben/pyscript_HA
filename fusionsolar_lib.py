"""
fusionsolar_lib.py — Pure Python module, NO pyscript globals.
Imported by fusionsolar.py and called via task.executor.

Do NOT use: log.*, state.*, hass.*, task.*, @time_trigger, etc.

Key fixes vs previous version:
  - Uses v3/overview/energy-balance (same as the working external script)
  - Sends exact query params the portal sends (timeDim, queryTime, dateStr, etc.)
  - Detects session expiry via content-type (HTML redirect) not just HTTP status
  - Supports optional Roarand CSRF token
  - Extracts real-time power from the LAST non-null value of each 5-min series
  - daily/monthly/yearly energy from dedicated KPI endpoint
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional
import json
import time
import requests

TZ = ZoneInfo("Europe/Zurich")


class SessionExpiredError(Exception):
    """Cookie expired — FusionSolar returned HTML instead of JSON."""
    pass


def _to_float(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        v = value.strip().replace(",", ".")
        if v in ("", "--", "-", "null", "None", "nan"):
            return None
        for suffix in ("kWh", "KWh", "kW", "kw", "W", "%"):
            if v.endswith(suffix):
                v = v[:-len(suffix)].strip()
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _last_valid(series):
    """Return the last non-null value in a 5-min series (= current value)."""
    if not series:
        return None
    for v in reversed(series):
        f = _to_float(v)
        if f is not None:
            return f
    return None


def _get_json(session, url, params, logs, name, timeout=20):
    """GET a JSON endpoint. Raises SessionExpiredError on HTML redirect."""
    r = session.get(url, params=params, timeout=timeout)
    logs.append(f"DEBUG HTTP {r.status_code} ({len(r.content)}B) {name}")
    if r.status_code in (401, 403):
        raise SessionExpiredError(f"Cookie rejeté HTTP {r.status_code} — recapturer dans Edge/Chrome")
    r.raise_for_status()
    ct = r.headers.get("content-type", "")
    if "json" not in ct:
        raise SessionExpiredError(f"HTML reçu au lieu de JSON ({name}) — session expirée")
    payload = r.json()
    if not payload.get("success"):
        logs.append(f"WARNING {name}: success=false — {payload.get('message')}")
        return None
    return payload


def _poll(base_url, station_dn, session, logs):
    """Fetch real-time balance (v3) + KPI data."""
    now_local = datetime.now(TZ)
    midnight  = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    tz_offset = midnight.utcoffset().total_seconds() / 3600

    # ── v3 energy-balance (5-min series for today) ──
    balance_url = base_url + "/rest/pvms/web/station/v3/overview/energy-balance"
    balance_params = {
        "stationDn": station_dn,
        "timeDim": 2,
        "timeZone": tz_offset,
        "timeZoneStr": "Europe/Zurich",
        "queryTime": int(midnight.timestamp() * 1000),
        "dateStr": midnight.strftime("%Y-%m-%d 00:00:00"),
        "_": int(time.time() * 1000),
    }
    balance = _get_json(session, balance_url, balance_params, logs, "energy_balance_v3")

    # ── station-real-kpi (SOC + daily/monthly/yearly energy) ──
    kpi_url = base_url + "/rest/pvms/web/station/v1/overview/station-real-kpi"
    kpi_params = {"stationDn": station_dn}
    kpi = _get_json(session, kpi_url, kpi_params, logs, "station_real_kpi")

    return balance, kpi


def _normalize(balance, kpi, station_dn, logs):
    """Extract scalar values from the raw API responses."""
    errors = {}

    # ── Real-time power from last point of each 5-min series ──
    pv_kw = battery_charge_kw = battery_discharge_kw = None
    load_kw = grid_import_kw = grid_export_kw = None

    if balance is None:
        errors["energy_balance_v3"] = "no data"
    else:
        data = balance.get("data", {})
        pv_kw             = _last_valid(data.get("productPower"))
        load_kw           = _last_valid(data.get("usePower"))
        battery_charge_kw = _last_valid(data.get("chargePower"))
        battery_discharge_kw = _last_valid(data.get("dischargePower"))
        # grid: positive = import (buy), negative = export (sell)
        # FusionSolar v3 has no dedicated grid series — derive from energy balance:
        # grid_import = load - pv - discharge + charge  (when positive)
        # Use selfUsePower to compute grid if available
        self_use = _last_valid(data.get("selfUsePower"))
        if pv_kw is not None and load_kw is not None:
            if self_use is not None:
                # pv consumed locally = self_use, remainder exported
                grid_export_kw = max(pv_kw - self_use, 0.0)
                grid_import_kw = max(load_kw - self_use
                                     - (battery_discharge_kw or 0.0)
                                     + (battery_charge_kw or 0.0), 0.0)
            else:
                # Fallback: no self-use data
                net = load_kw - pv_kw - (battery_discharge_kw or 0.0) + (battery_charge_kw or 0.0)
                grid_import_kw = max(net, 0.0)
                grid_export_kw = max(-net, 0.0)
        logs.append(
            f"DEBUG balance: pv={pv_kw} load={load_kw} "
            f"chg={battery_charge_kw} dis={battery_discharge_kw} "
            f"import={grid_import_kw} export={grid_export_kw}"
        )

    # ── KPI: SOC + cumulative energy ──
    battery_soc = daily_kwh = monthly_kwh = yearly_kwh = total_kwh = None
    if kpi is None:
        errors["station_real_kpi"] = "no data"
    else:
        kdata = kpi.get("data", {})
        # Huawei key names vary by firmware — try several
        battery_soc  = _to_float(kdata.get("batterySoc") or kdata.get("stateOfCharge") or kdata.get("soc"))
        daily_kwh    = _to_float(kdata.get("dailyEnergy") or kdata.get("dayEnergy") or kdata.get("totalCurrentDayEnergy"))
        monthly_kwh  = _to_float(kdata.get("monthEnergy") or kdata.get("monthlyEnergy") or kdata.get("totalCurrentMonthEnergy"))
        yearly_kwh   = _to_float(kdata.get("yearEnergy") or kdata.get("yearlyEnergy") or kdata.get("totalCurrentYearEnergy"))
        total_kwh    = _to_float(kdata.get("cumulativeEnergy") or kdata.get("totalEnergy") or kdata.get("lifetimeEnergy"))
        logs.append(
            f"DEBUG kpi: soc={battery_soc}% daily={daily_kwh} "
            f"monthly={monthly_kwh} yearly={yearly_kwh} total={total_kwh}"
        )

    if pv_kw is None:
        logs.append("WARNING productPower series vide ou absente")
    if battery_soc is None:
        logs.append("WARNING batterySoc absent du KPI")
    if grid_import_kw is None:
        logs.append("WARNING grid dérivé impossible (pv ou load manquant)")

    if errors:
        status = "error" if len(errors) >= 2 else "partial"
        err = json.dumps(errors, ensure_ascii=False)
        logs.append(f"{'ERROR' if status == 'error' else 'WARNING'} status={status}: {err}")
    else:
        status = "ok"
        err = None

    return {
        "ts_utc":               datetime.now(timezone.utc).isoformat(),
        "plant_dn":             station_dn,
        "status":               status,
        "error":                err,
        "pv_power_kw":          pv_kw,
        "battery_soc_percent":  battery_soc,
        "battery_charge_kw":    battery_charge_kw,
        "battery_discharge_kw": battery_discharge_kw,
        "grid_import_kw":       grid_import_kw,
        "grid_export_kw":       grid_export_kw,
        "load_power_kw":        load_kw,
        "daily_energy_kwh":     daily_kwh,
        "monthly_energy_kwh":   monthly_kwh,
        "yearly_energy_kwh":    yearly_kwh,
        "total_energy_kwh":     total_kwh,
        "logs":                 logs,
    }


def fetch(config):
    """
    Entry point called via task.executor from pyscript.
    Returns a plain dict so pyscript can call .get() on it.
    Raises SessionExpiredError when the cookie needs to be refreshed.
    """
    logs = []
    cookie = config["cookie"]
    if not cookie or cookie == "PASTE_EDGE_NETWORK_COOKIE_HERE":
        raise RuntimeError("FusionSolar cookie manquant — éditer /config/pyscript/fusionsolar.py")

    base_url   = config["base_url"].rstrip("/")
    station_dn = config["station_dn"]
    logs.append(f"DEBUG cookie présent ({len(cookie)} chars), station={station_dn}")

    session = requests.Session()
    session.headers.update({
        "Cookie":           cookie,
        "Accept":           "application/json, text/javascript, */*; q=0.01",
        "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/145.0.0.0 Safari/537.36 Edg/145.0",
        "X-Requested-With": "XMLHttpRequest",
        "X-Timezone-Offset": "120",
        "Referer":          base_url + "/uniportal/pvmswebsite/assets/build/cloud.html",
        "Origin":           base_url,
    })
    roarand = config.get("roarand")
    if roarand:
        session.headers["Roarand"] = roarand
        logs.append("DEBUG Roarand header ajouté")

    balance, kpi = _poll(base_url, station_dn, session, logs)
    return _normalize(balance, kpi, station_dn, logs)
