#!/usr/bin/env python3
"""
fusionsolar_fetch.py — Standalone script, runs OUTSIDE pyscript.
Deploy to: /config/fusionsolar_fetch.py

Reads JSON config from stdin, writes JSON result to stdout.
Called by pyscript via subprocess — zero pyscript AST interference.

Dependencies: requests (pre-installed in HA container)
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import sys
import time
import requests

TZ = ZoneInfo("Europe/Zurich")


class SessionExpiredError(Exception):
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
    if not series:
        return None
    for v in reversed(series):
        f = _to_float(v)
        if f is not None:
            return f
    return None


def _get_json(session, url, params, logs, name, timeout=20):
    r = session.get(url, params=params, timeout=timeout)
    logs.append(f"DEBUG HTTP {r.status_code} ({len(r.content)}B) {name}")
    if r.status_code in (401, 403):
        raise SessionExpiredError(f"Cookie rejeté HTTP {r.status_code} — recapturer dans Edge/Chrome")
    r.raise_for_status()
    if "json" not in r.headers.get("content-type", ""):
        raise SessionExpiredError(f"HTML reçu ({name}) — session expirée, recapturer le cookie")
    payload = r.json()
    if not payload.get("success"):
        logs.append(f"WARNING {name}: success=false — {payload.get('message')}")
        return None
    return payload


def fetch(config):
    logs = []
    cookie = config.get("cookie", "")
    if not cookie or cookie == "PASTE_EDGE_NETWORK_COOKIE_HERE":
        raise RuntimeError("Cookie manquant — éditer /config/pyscript/apps/fusionsolar/__init__.py")

    base_url   = config["base_url"].rstrip("/")
    station_dn = config["station_dn"]
    logs.append(f"DEBUG cookie présent ({len(cookie)} chars), station={station_dn}")

    session = requests.Session()
    session.headers.update({
        "Cookie":            cookie,
        "Accept":            "application/json, text/javascript, */*; q=0.01",
        "User-Agent":        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/145.0.0.0 Safari/537.36 Edg/145.0",
        "X-Requested-With":  "XMLHttpRequest",
        "X-Timezone-Offset": "120",
        "Referer":           base_url + "/uniportal/pvmswebsite/assets/build/cloud.html",
        "Origin":            base_url,
    })
    roarand = config.get("roarand")
    if roarand:
        session.headers["Roarand"] = roarand

    # ── v3 energy-balance ──
    now_local = datetime.now(TZ)
    midnight  = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    tz_offset = midnight.utcoffset().total_seconds() / 3600

    balance = _get_json(
        session,
        base_url + "/rest/pvms/web/station/v3/overview/energy-balance",
        {
            "stationDn":   station_dn,
            "timeDim":     2,
            "timeZone":    tz_offset,
            "timeZoneStr": "Europe/Zurich",
            "queryTime":   int(midnight.timestamp() * 1000),
            "dateStr":     midnight.strftime("%Y-%m-%d 00:00:00"),
            "_":           int(time.time() * 1000),
        },
        logs, "energy_balance_v3"
    )

    # ── station-real-kpi ──
    kpi = _get_json(
        session,
        base_url + "/rest/pvms/web/station/v1/overview/station-real-kpi",
        {"stationDn": station_dn},
        logs, "station_real_kpi"
    )

    # ── normalize ──
    errors = {}
    pv_kw = battery_charge_kw = battery_discharge_kw = load_kw = None
    grid_import_kw = grid_export_kw = None

    if balance is None:
        errors["energy_balance_v3"] = "no data"
    else:
        data = balance.get("data", {})
        pv_kw                = _last_valid(data.get("productPower"))
        load_kw              = _last_valid(data.get("usePower"))
        battery_charge_kw    = _last_valid(data.get("chargePower"))
        battery_discharge_kw = _last_valid(data.get("dischargePower"))
        self_use             = _last_valid(data.get("selfUsePower"))
        if pv_kw is not None and load_kw is not None:
            if self_use is not None:
                grid_export_kw = max(pv_kw - self_use, 0.0)
                grid_import_kw = max(load_kw - self_use - (battery_discharge_kw or 0.0) + (battery_charge_kw or 0.0), 0.0)
            else:
                net = load_kw - pv_kw - (battery_discharge_kw or 0.0) + (battery_charge_kw or 0.0)
                grid_import_kw = max(net, 0.0)
                grid_export_kw = max(-net, 0.0)
        logs.append(f"DEBUG balance: pv={pv_kw} load={load_kw} chg={battery_charge_kw} dis={battery_discharge_kw} import={grid_import_kw} export={grid_export_kw}")

    battery_soc = daily_kwh = monthly_kwh = yearly_kwh = total_kwh = None
    if kpi is None:
        errors["station_real_kpi"] = "no data"
    else:
        kdata = kpi.get("data", {})
        battery_soc = _to_float(kdata.get("batterySoc") or kdata.get("stateOfCharge") or kdata.get("soc"))
        daily_kwh   = _to_float(kdata.get("dailyEnergy") or kdata.get("dayEnergy") or kdata.get("totalCurrentDayEnergy"))
        monthly_kwh = _to_float(kdata.get("monthEnergy") or kdata.get("monthlyEnergy") or kdata.get("totalCurrentMonthEnergy"))
        yearly_kwh  = _to_float(kdata.get("yearEnergy") or kdata.get("yearlyEnergy") or kdata.get("totalCurrentYearEnergy"))
        total_kwh   = _to_float(kdata.get("cumulativeEnergy") or kdata.get("totalEnergy") or kdata.get("lifetimeEnergy"))
        logs.append(f"DEBUG kpi: soc={battery_soc}% daily={daily_kwh} monthly={monthly_kwh} yearly={yearly_kwh}")

    status = "ok"
    err = None
    if errors:
        status = "error" if len(errors) >= 2 else "partial"
        err = json.dumps(errors, ensure_ascii=False)

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


if __name__ == "__main__":
    config = json.loads(sys.stdin.read())
    try:
        result = fetch(config)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e), "logs": [f"ERROR {e}"]}))
        sys.exit(1)
