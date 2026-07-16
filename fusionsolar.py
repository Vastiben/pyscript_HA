"""
/config/pyscript/fusionsolar.py

FusionSolar -> Home Assistant sensors + Telegram every 5 minutes.

What it does every 5 minutes:
1) Calls FusionSolar web endpoints using a manually copied browser Cookie.
2) Extracts current PV production, household load, battery charge/discharge, battery SOC,
   instant grid import/export when available/derivable, and daily/month/year/lifetime totals.
3) Updates Home Assistant virtual sensors.
4) Sends a Telegram message through an existing Home Assistant notify service.

You need to edit only CONFIG below.
"""

import time
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# =========================
# USER CONFIGURATION
# =========================
CONFIG = {
    # FusionSolar
    "base_url": "https://uni004eu5.fusionsolar.huawei.com",
    "station_dn": "NE=152120280",
    "timezone": "Europe/Zurich",

    # Paste the full Cookie request header copied from Edge/Chrome DevTools -> Network.
    # Do NOT include the word "Cookie:" itself, only the value after it.
    "cookie": "PASTE_FUSIONSOLAR_COOKIE_HERE",

    # Optional. Paste the Roarand request header if your Network request contains one.
    # Leave empty if absent.
    "roarand": "",

    # Home Assistant Telegram notify service.
    # If your service is notify.telegram, use domain="notify", service="telegram".
    # If your service is notify.bastien_telegram, use domain="notify", service="bastien_telegram".
    "telegram_domain": "notify",
    "telegram_service": "telegram",

    # Send Telegram every run. User requested every 5 minutes.
    "send_telegram": True,

    # Pyscript trigger interval
    "update_interval": "period(now, 5min)",
}

# Endpoint paths observed in your FusionSolar tenant / discussion.
ENERGY_BALANCE_PATH = "/rest/pvms/web/station/v3/overview/energy-balance"
ENERGY_FLOW_PATH = "/rest/pvms/web/station/v1/overview/energy-flow"
STATION_REAL_KPI_PATH = "/rest/pvms/web/station/v1/overview/station-real-kpi"

TZ = ZoneInfo(CONFIG["timezone"])


# =========================
# LOW-LEVEL HELPERS
# =========================
def _float(value, default=None):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        v = value.strip().replace(",", ".")
        if v in ("", "--", "-", "null", "None", "nan"):
            return default
        for suffix in (" kWh", " kW", "kWh", "kW", " W", "W", "%"):
            if v.endswith(suffix):
                v = v[: -len(suffix)].strip()
        try:
            return float(v)
        except Exception:
            return default
    return default


def _round(value, ndigits=3):
    if value is None:
        return None
    try:
        return round(float(value), ndigits)
    except Exception:
        return value


def _session():
    cookie = CONFIG["cookie"]
    if not cookie or cookie == "PASTE_FUSIONSOLAR_COOKIE_HERE":
        raise RuntimeError("FusionSolar cookie missing: edit CONFIG['cookie'] in /config/pyscript/fusionsolar.py")

    s = requests.Session()
    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        ),
        "X-Requested-With": "XMLHttpRequest",
        "X-Timezone-Offset": "120",
        "Referer": CONFIG["base_url"] + "/uniportal/pvmswebsite/assets/build/cloud.html",
    }
    if CONFIG.get("roarand"):
        headers["Roarand"] = CONFIG["roarand"]
    s.headers.update(headers)
    return s


def _get_json(session, path, params):
    url = CONFIG["base_url"].rstrip("/") + path
    r = session.get(url, params=params, timeout=30)
    r.raise_for_status()
    content_type = r.headers.get("content-type", "")
    if "json" not in content_type.lower():
        raise RuntimeError("FusionSolar returned non-JSON, likely expired cookie/session")
    payload = r.json()
    if not payload.get("success", False):
        raise RuntimeError("FusionSolar API success=false: " + json.dumps(payload, ensure_ascii=False)[:500])
    return payload


def _today_params():
    midnight = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    query_time_ms = int(midnight.timestamp() * 1000)
    tz_offset = int(midnight.utcoffset().total_seconds() / 3600)
    return {
        "stationDn": CONFIG["station_dn"],
        "timeDim": 2,
        "timeZone": tz_offset,
        "timeZoneStr": CONFIG["timezone"],
        "queryTime": query_time_ms,
        "dateStr": midnight.strftime("%Y-%m-%d 00:00:00"),
        "_": int(time.time() * 1000),
    }


def _station_params():
    return {
        "stationDn": CONFIG["station_dn"],
        "_": int(time.time() * 1000),
    }


# =========================
# FUSIONSOLAR FETCHERS
# =========================
def fetch_energy_balance(session):
    return _get_json(session, ENERGY_BALANCE_PATH, _today_params())


def fetch_energy_flow(session):
    return _get_json(session, ENERGY_FLOW_PATH, _station_params())


def fetch_station_real_kpi(session):
    # If this endpoint does not work in your portal version, the script continues without it.
    try:
        return _get_json(session, STATION_REAL_KPI_PATH, _station_params())
    except Exception as e:
        return {"success": False, "_error": str(e), "data": {}}


# =========================
# PARSING LOGIC
# =========================
def _last_valid_index(data, keys):
    x_axis = data.get("xAxis", [])
    if not x_axis:
        return None
    for i in range(len(x_axis) - 1, -1, -1):
        for key in keys:
            values = data.get(key, [])
            if i < len(values) and _float(values[i]) is not None:
                return i
    return None


def _series_value(data, key, idx):
    values = data.get(key, [])
    if idx is None or idx >= len(values):
        return None
    return _float(values[idx])


def _node_by_id(flow_data, node_id):
    nodes = flow_data.get("data", {}).get("flow", {}).get("nodes", [])
    for n in nodes:
        if str(n.get("id")) == str(node_id):
            return n
    return {}


def _node_by_moc(flow_data, moc_id):
    nodes = flow_data.get("data", {}).get("flow", {}).get("nodes", [])
    for n in nodes:
        if n.get("mocId") == moc_id:
            return n
    return {}


def _link_value_by_label_contains(flow_data, text):
    links = flow_data.get("data", {}).get("flow", {}).get("links", [])
    text = text.lower()
    for link in links:
        desc = link.get("description") or {}
        label = str(desc.get("label") or "").lower()
        value = desc.get("value")
        if text in label:
            return _float(value)
    return None


def extract_metrics(energy_balance, energy_flow, station_real_kpi):
    eb = energy_balance.get("data", {})
    ef = energy_flow or {}
    kpi = station_real_kpi.get("data", {}) if station_real_kpi else {}

    # Latest 5-minute index based on your available series.
    idx = _last_valid_index(eb, [
        "productPower", "usePower", "selfUsePower", "chargePower", "dischargePower"
    ])
    timestamp = None
    if idx is not None and idx < len(eb.get("xAxis", [])):
        timestamp = eb.get("xAxis", [])[idx]

    pv_kw = _series_value(eb, "productPower", idx)
    load_kw = _series_value(eb, "usePower", idx)
    self_use_kw = _series_value(eb, "selfUsePower", idx)
    battery_charge_kw = _series_value(eb, "chargePower", idx)
    battery_discharge_kw = _series_value(eb, "dischargePower", idx)

    # Energy-flow gives current node values and SOC.
    pv_node = _node_by_id(ef, "0") or _node_by_moc(ef, 20812)
    battery_node = _node_by_id(ef, "4") or _node_by_moc(ef, 20815)
    load_node = _node_by_id(ef, "5") or _node_by_moc(ef, 90002)

    # Prefer energy-flow current values where present, because it is the live diagram.
    pv_kw = _float(pv_node.get("value"), pv_kw)
    load_kw = _float(load_node.get("value"), load_kw)

    device_tips = battery_node.get("deviceTips") or {}
    soc = _float(device_tips.get("SOC"))
    battery_power_from_flow = _float(device_tips.get("BATTERY_POWER"), _float(battery_node.get("value")))

    # In your sample, energy-balance chargePower=1.896 and energy-flow battery value=1.896.
    # So we keep charge/discharge direction from energy-balance, not from the flow node alone.
    if battery_charge_kw is None and battery_discharge_kw is None and battery_power_from_flow is not None:
        battery_charge_kw = battery_power_from_flow
        battery_discharge_kw = 0.0

    # Grid instant import is available in energy-flow link with label buy.power in your sample.
    grid_import_kw = _link_value_by_label_contains(ef, "buy.power")

    # Derive export if not explicitly available:
    # export = PV + battery discharge - battery charge - load - import
    if grid_import_kw is None:
        grid_import_kw = 0.0
    net_export = None
    if pv_kw is not None and load_kw is not None:
        ch = battery_charge_kw or 0.0
        dis = battery_discharge_kw or 0.0
        imp = grid_import_kw or 0.0
        net_export = pv_kw + dis - ch - load_kw - imp
    grid_export_kw = max(net_export, 0.0) if net_export is not None else None

    # Daily/month/year totals: use station-real-kpi when present, else energy-balance totals.
    daily_energy = _float(kpi.get("dailyEnergy"), _float(eb.get("totalProductPower")))
    daily_self_use = _float(kpi.get("dailySelfUseEnergy"), _float(eb.get("totalSelfUsePower")))
    daily_consumption = _float(kpi.get("dailyUseEnergy"), _float(eb.get("totalUsePower")))
    daily_export = _float(eb.get("totalOnGridPower"))
    daily_import = _float(eb.get("totalBuyPower"))
    month_energy = _float(kpi.get("monthEnergy"))
    year_energy = _float(kpi.get("yearEnergy"))
    lifetime_energy = _float(kpi.get("cumulativeEnergy"))
    daily_income = _float(kpi.get("dailyIncome"))

    return {
        "timestamp": timestamp,
        "pv_power_kw": pv_kw,
        "load_power_kw": load_kw,
        "self_use_power_kw": self_use_kw,
        "battery_soc_percent": soc,
        "battery_charge_kw": battery_charge_kw,
        "battery_discharge_kw": battery_discharge_kw,
        "battery_charge_today_kwh": _float(device_tips.get("CHARGE_CAPACITY")),
        "battery_discharge_today_kwh": _float(device_tips.get("DISCHARGE_CAPACITY")),
        "grid_import_kw": grid_import_kw,
        "grid_export_kw": grid_export_kw,
        "daily_energy_kwh": daily_energy,
        "daily_self_use_kwh": daily_self_use,
        "daily_consumption_kwh": daily_consumption,
        "daily_export_kwh": daily_export,
        "daily_import_kwh": daily_import,
        "month_energy_kwh": month_energy,
        "year_energy_kwh": year_energy,
        "lifetime_energy_kwh": lifetime_energy,
        "daily_income": daily_income,
        "charge_mode": device_tips.get("CHARGE_MODE_VALUE"),
        "station_dn": CONFIG["station_dn"],
        "last_update": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }


def fetch_all_sync():
    s = _session()
    eb = fetch_energy_balance(s)
    ef = fetch_energy_flow(s)
    kpi = fetch_station_real_kpi(s)
    metrics = extract_metrics(eb, ef, kpi)
    return metrics


# =========================
# HOME ASSISTANT OUTPUT
# =========================
def _set_sensor(entity_id, value, unit=None, device_class=None, state_class="measurement", attrs=None):
    if value is None:
        return
    attributes = dict(attrs or {})
    if unit:
        attributes["unit_of_measurement"] = unit
    if device_class:
        attributes["device_class"] = device_class
    if state_class:
        attributes["state_class"] = state_class
    state.set(entity_id, value=_round(value), new_attributes=attributes)


def update_sensors(m):
    attrs = {
        "station_dn": m.get("station_dn"),
        "fusion_timestamp": m.get("timestamp"),
        "last_update": m.get("last_update"),
        "charge_mode": m.get("charge_mode"),
    }

    _set_sensor("sensor.fusionsolar_pv_power", m.get("pv_power_kw"), "kW", "power", attrs=attrs)
    _set_sensor("sensor.fusionsolar_load_power", m.get("load_power_kw"), "kW", "power", attrs=attrs)
    _set_sensor("sensor.fusionsolar_self_use_power", m.get("self_use_power_kw"), "kW", "power", attrs=attrs)
    _set_sensor("sensor.fusionsolar_battery_soc", m.get("battery_soc_percent"), "%", "battery", attrs=attrs)
    _set_sensor("sensor.fusionsolar_battery_charge_power", m.get("battery_charge_kw"), "kW", "power", attrs=attrs)
    _set_sensor("sensor.fusionsolar_battery_discharge_power", m.get("battery_discharge_kw"), "kW", "power", attrs=attrs)
    _set_sensor("sensor.fusionsolar_grid_import_power", m.get("grid_import_kw"), "kW", "power", attrs=attrs)
    _set_sensor("sensor.fusionsolar_grid_export_power", m.get("grid_export_kw"), "kW", "power", attrs=attrs)

    _set_sensor("sensor.fusionsolar_production_today", m.get("daily_energy_kwh"), "kWh", "energy", "total_increasing", attrs)
    _set_sensor("sensor.fusionsolar_self_use_today", m.get("daily_self_use_kwh"), "kWh", "energy", "total_increasing", attrs)
    _set_sensor("sensor.fusionsolar_consumption_today", m.get("daily_consumption_kwh"), "kWh", "energy", "total_increasing", attrs)
    _set_sensor("sensor.fusionsolar_export_today", m.get("daily_export_kwh"), "kWh", "energy", "total_increasing", attrs)
    _set_sensor("sensor.fusionsolar_import_today", m.get("daily_import_kwh"), "kWh", "energy", "total_increasing", attrs)
    _set_sensor("sensor.fusionsolar_month_energy", m.get("month_energy_kwh"), "kWh", "energy", "total_increasing", attrs)
    _set_sensor("sensor.fusionsolar_year_energy", m.get("year_energy_kwh"), "kWh", "energy", "total_increasing", attrs)
    _set_sensor("sensor.fusionsolar_lifetime_energy", m.get("lifetime_energy_kwh"), "kWh", "energy", "total_increasing", attrs)
    _set_sensor("sensor.fusionsolar_daily_income", m.get("daily_income"), None, None, "measurement", attrs)
    _set_sensor("sensor.fusionsolar_battery_charge_today", m.get("battery_charge_today_kwh"), "kWh", "energy", "total_increasing", attrs)
    _set_sensor("sensor.fusionsolar_battery_discharge_today", m.get("battery_discharge_today_kwh"), "kWh", "energy", "total_increasing", attrs)

    state.set("sensor.fusionsolar_status", value="ok", new_attributes=attrs)
    state.set("sensor.fusionsolar_last_update", value=m.get("last_update"), new_attributes=attrs)


def _fmt(v, unit="", ndigits=2):
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.{ndigits}f} {unit}".strip()
    except Exception:
        return str(v)


def build_telegram_message(m):
    return (
        "☀️ FusionSolar\n"
        f"🕒 {m.get('last_update')}\n\n"
        f"Production PV: {_fmt(m.get('pv_power_kw'), 'kW')}\n"
        f"Consommation: {_fmt(m.get('load_power_kw'), 'kW')}\n"
        f"Autoconsommation: {_fmt(m.get('self_use_power_kw'), 'kW')}\n\n"
        f"🔋 Batterie: {_fmt(m.get('battery_soc_percent'), '%', 0)}\n"
        f"Charge: {_fmt(m.get('battery_charge_kw'), 'kW')}\n"
        f"Décharge: {_fmt(m.get('battery_discharge_kw'), 'kW')}\n\n"
        f"⚡ Réseau import: {_fmt(m.get('grid_import_kw'), 'kW')}\n"
        f"⚡ Réseau export: {_fmt(m.get('grid_export_kw'), 'kW')}\n\n"
        f"📊 Aujourd'hui\n"
        f"PV: {_fmt(m.get('daily_energy_kwh'), 'kWh')}\n"
        f"Conso: {_fmt(m.get('daily_consumption_kwh'), 'kWh')}\n"
        f"Import: {_fmt(m.get('daily_import_kwh'), 'kWh')}\n"
        f"Export: {_fmt(m.get('daily_export_kwh'), 'kWh')}"
    )


def send_telegram(m):
    if not CONFIG.get("send_telegram", True):
        return
    message = build_telegram_message(m)
    service.call(CONFIG["telegram_domain"], CONFIG["telegram_service"], message=message)


# =========================
# MAIN PERIODIC TASK
# =========================
@time_trigger(CONFIG["update_interval"])
def update_fusionsolar_every_5_min():
    try:
        metrics = task.executor(fetch_all_sync)
        update_sensors(metrics)
        send_telegram(metrics)
    except Exception as e:
        msg = str(e)
        state.set(
            "sensor.fusionsolar_status",
            value="error",
            new_attributes={
                "error": msg,
                "last_update": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
                "station_dn": CONFIG.get("station_dn"),
            },
        )
        # Send Telegram also on error, because cookie expiry is operationally important.
        try:
            service.call(
                CONFIG["telegram_domain"],
                CONFIG["telegram_service"],
                message="⚠️ FusionSolar error\n" + msg,
            )
        except Exception:
            pass
        log.error(f"FusionSolar update failed: {msg}")
