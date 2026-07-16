"""
/config/pyscript/fusionsolar.py

FusionSolar -> Home Assistant sensors + Telegram every 5 minutes.
With verbose debug logs prefixed by [FUSIONSOLAR].
Set DEBUG=False once everything works.
"""

import time
import json
import requests
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

DEBUG = True

CONFIG = {
    "base_url": "https://uni004eu5.fusionsolar.huawei.com",
    "station_dn": "NE=152120280",
    "timezone": "Europe/Zurich",
    "cookie_file": "/config/fusionsolar/cookie.txt",
    "roarand_file": "/config/fusionsolar/roarand.txt",
    "telegram_domain": "notify",
    "telegram_service": "telegram",
    "send_telegram_every_run": True,
    "update_interval": "period(now, 5min)",
}

ENERGY_BALANCE_PATH = "/rest/pvms/web/station/v3/overview/energy-balance"
ENERGY_FLOW_PATH = "/rest/pvms/web/station/v1/overview/energy-flow"
STATION_REAL_KPI_PATH = "/rest/pvms/web/station/v1/overview/station-real-kpi"
TZ = ZoneInfo(CONFIG["timezone"])


def dbg(msg):
    if DEBUG:
        log.info(f"[FUSIONSOLAR] {msg}")


dbg("fusionsolar.py chargé")


def _read_text_file(path, default=""):
    p = Path(path)
    exists = p.exists()
    dbg(f"Lecture fichier: {path}, exists={exists}")
    if not exists:
        return default
    value = p.read_text(encoding="utf-8").strip()
    dbg(f"Fichier lu: {path}, length={len(value)}")
    return value


def _delete_file(path):
    p = Path(path)
    if p.exists():
        p.unlink()
        dbg(f"Fichier supprimé: {path}")
    else:
        dbg(f"Fichier absent, rien à supprimer: {path}")


def _get_cookie():
    cookie = _read_text_file(CONFIG["cookie_file"])
    if not cookie:
        dbg("Cookie absent")
        raise RuntimeError("FusionSolar cookie missing. Send it with /fs_cookie <cookie>.")
    dbg(f"Cookie présent, length={len(cookie)}")
    return cookie


def _get_roarand():
    roarand = _read_text_file(CONFIG["roarand_file"])
    dbg(f"Roarand présent={bool(roarand)}, length={len(roarand)}")
    return roarand


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


def _fmt(v, unit="", ndigits=2):
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.{ndigits}f} {unit}".strip()
    except Exception:
        return str(v)


def _notify(message, target=None):
    dbg(f"Notification: target={target}, message_length={len(str(message))}")
    kwargs = {"message": message}
    if target is not None:
        kwargs["target"] = target
    service.call(CONFIG["telegram_domain"], CONFIG["telegram_service"], **kwargs)


def _session():
    dbg("Création session requests")
    cookie = _get_cookie()
    roarand = _get_roarand()
    s = requests.Session()
    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "X-Timezone-Offset": "120",
        "Referer": CONFIG["base_url"] + "/uniportal/pvmswebsite/assets/build/cloud.html",
    }
    if roarand:
        headers["Roarand"] = roarand
    s.headers.update(headers)
    dbg(f"Session prête, headers={list(headers.keys())}")
    return s


def _get_json(session, path, params):
    url = CONFIG["base_url"].rstrip("/") + path
    dbg(f"GET {path}, params={params}")
    r = session.get(url, params=params, timeout=30)
    dbg(f"Réponse {path}: status={r.status_code}, content_type={r.headers.get('content-type', '')}")
    r.raise_for_status()
    content_type = r.headers.get("content-type", "")
    if "json" not in content_type.lower():
        dbg(f"Réponse non JSON pour {path}, extrait={r.text[:120]}")
        raise RuntimeError("FusionSolar returned non-JSON. Cookie/session likely expired.")
    payload = r.json()
    dbg(f"JSON reçu pour {path}: success={payload.get('success')}, keys={list(payload.keys())}")
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
    return {"stationDn": CONFIG["station_dn"], "_": int(time.time() * 1000)}


def fetch_energy_balance(session):
    return _get_json(session, ENERGY_BALANCE_PATH, _today_params())


def fetch_energy_flow(session):
    return _get_json(session, ENERGY_FLOW_PATH, _station_params())


def fetch_station_real_kpi(session):
    try:
        return _get_json(session, STATION_REAL_KPI_PATH, _station_params())
    except Exception as e:
        dbg(f"station-real-kpi ignoré suite erreur: {e}")
        return {"success": False, "_error": str(e), "data": {}}


def _last_valid_index(data, keys):
    x_axis = data.get("xAxis", [])
    if not x_axis:
        return None
    for i in range(len(x_axis) - 1, -1, -1):
        for key in keys:
            values = data.get(key, [])
            if i < len(values) and _float(values[i]) is not None:
                dbg(f"Dernier index valide: i={i}, key={key}, timestamp={x_axis[i] if i < len(x_axis) else None}")
                return i
    dbg("Aucun index valide trouvé")
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
    dbg("Extraction métriques")
    eb = energy_balance.get("data", {})
    ef = energy_flow or {}
    kpi = station_real_kpi.get("data", {}) if station_real_kpi else {}

    idx = _last_valid_index(eb, ["productPower", "usePower", "selfUsePower", "chargePower", "dischargePower"])
    timestamp = eb.get("xAxis", [])[idx] if idx is not None and idx < len(eb.get("xAxis", [])) else None

    pv_kw = _series_value(eb, "productPower", idx)
    load_kw = _series_value(eb, "usePower", idx)
    self_use_kw = _series_value(eb, "selfUsePower", idx)
    battery_charge_kw = _series_value(eb, "chargePower", idx)
    battery_discharge_kw = _series_value(eb, "dischargePower", idx)

    pv_node = _node_by_id(ef, "0") or _node_by_moc(ef, 20812)
    battery_node = _node_by_id(ef, "4") or _node_by_moc(ef, 20815)
    load_node = _node_by_id(ef, "5") or _node_by_moc(ef, 90002)

    pv_kw = _float(pv_node.get("value"), pv_kw)
    load_kw = _float(load_node.get("value"), load_kw)

    device_tips = battery_node.get("deviceTips") or {}
    soc = _float(device_tips.get("SOC"))
    battery_power_from_flow = _float(device_tips.get("BATTERY_POWER"), _float(battery_node.get("value")))
    if battery_charge_kw is None and battery_discharge_kw is None and battery_power_from_flow is not None:
        battery_charge_kw = battery_power_from_flow
        battery_discharge_kw = 0.0

    grid_import_kw = _link_value_by_label_contains(ef, "buy.power")
    if grid_import_kw is None:
        grid_import_kw = 0.0

    net_export = None
    if pv_kw is not None and load_kw is not None:
        ch = battery_charge_kw or 0.0
        dis = battery_discharge_kw or 0.0
        imp = grid_import_kw or 0.0
        net_export = pv_kw + dis - ch - load_kw - imp
    grid_export_kw = max(net_export, 0.0) if net_export is not None else None

    metrics = {
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
        "daily_energy_kwh": _float(kpi.get("dailyEnergy"), _float(eb.get("totalProductPower"))),
        "daily_self_use_kwh": _float(kpi.get("dailySelfUseEnergy"), _float(eb.get("totalSelfUsePower"))),
        "daily_consumption_kwh": _float(kpi.get("dailyUseEnergy"), _float(eb.get("totalUsePower"))),
        "daily_export_kwh": _float(eb.get("totalOnGridPower")),
        "daily_import_kwh": _float(eb.get("totalBuyPower")),
        "month_energy_kwh": _float(kpi.get("monthEnergy")),
        "year_energy_kwh": _float(kpi.get("yearEnergy")),
        "lifetime_energy_kwh": _float(kpi.get("cumulativeEnergy")),
        "daily_income": _float(kpi.get("dailyIncome")),
        "charge_mode": device_tips.get("CHARGE_MODE_VALUE"),
        "station_dn": CONFIG["station_dn"],
        "last_update": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }
    dbg(f"Métriques extraites: PV={pv_kw}, load={load_kw}, SOC={soc}, charge={battery_charge_kw}, discharge={battery_discharge_kw}, import={grid_import_kw}, export={grid_export_kw}")
    return metrics


def fetch_all_sync():
    dbg("Début fetch_all_sync")
    s = _session()
    eb = fetch_energy_balance(s)
    ef = fetch_energy_flow(s)
    kpi = fetch_station_real_kpi(s)
    metrics = extract_metrics(eb, ef, kpi)
    dbg(f"Fetch OK: PV={metrics.get('pv_power_kw')}, SOC={metrics.get('battery_soc_percent')}")
    return metrics


def _set_sensor(entity_id, value, unit=None, device_class=None, state_class="measurement", attrs=None):
    if value is None:
        dbg(f"Sensor non mis à jour car valeur None: {entity_id}")
        return
    attributes = dict(attrs or {})
    if unit:
        attributes["unit_of_measurement"] = unit
    if device_class:
        attributes["device_class"] = device_class
    if state_class:
        attributes["state_class"] = state_class
    state.set(entity_id, value=_round(value), new_attributes=attributes)
    dbg(f"Sensor mis à jour: {entity_id}={_round(value)} {unit or ''}")


def update_sensors(m):
    dbg("Mise à jour sensors")
    attrs = {"station_dn": m.get("station_dn"), "fusion_timestamp": m.get("timestamp"), "last_update": m.get("last_update"), "charge_mode": m.get("charge_mode")}
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
    dbg("Sensors terminés")


def build_telegram_message(m):
    return ("☀️ FusionSolar\n" f"🕒 {m.get('last_update')}\n\n" f"Production PV: {_fmt(m.get('pv_power_kw'), 'kW')}\n" f"Consommation: {_fmt(m.get('load_power_kw'), 'kW')}\n" f"Autoconsommation: {_fmt(m.get('self_use_power_kw'), 'kW')}\n\n" f"🔋 Batterie: {_fmt(m.get('battery_soc_percent'), '%', 0)}\n" f"Charge: {_fmt(m.get('battery_charge_kw'), 'kW')}\n" f"Décharge: {_fmt(m.get('battery_discharge_kw'), 'kW')}\n\n" f"⚡ Import réseau: {_fmt(m.get('grid_import_kw'), 'kW')}\n" f"⚡ Export réseau: {_fmt(m.get('grid_export_kw'), 'kW')}\n\n" f"📊 Aujourd'hui\n" f"PV: {_fmt(m.get('daily_energy_kwh'), 'kWh')}\n" f"Conso: {_fmt(m.get('daily_consumption_kwh'), 'kWh')}\n" f"Import: {_fmt(m.get('daily_import_kwh'), 'kWh')}\n" f"Export: {_fmt(m.get('daily_export_kwh'), 'kWh')}")


@time_trigger(CONFIG["update_interval"])
def update_fusionsolar_every_5_min():
    dbg("Trigger périodique FusionSolar")
    try:
        metrics = task.executor(fetch_all_sync)
        update_sensors(metrics)
        if CONFIG.get("send_telegram_every_run", True):
            _notify(build_telegram_message(metrics))
    except Exception as e:
        msg = str(e)
        dbg(f"Erreur trigger périodique: {msg}")
        state.set("sensor.fusionsolar_status", value="error", new_attributes={"error": msg, "last_update": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"), "station_dn": CONFIG.get("station_dn")})
        try:
            _notify("⚠️ FusionSolar error\n" + msg)
        except Exception:
            pass
        log.error(f"[FUSIONSOLAR] FusionSolar update failed: {msg}")


@event_trigger("fusionsolar_command")
def handle_fusionsolar_command(**kwargs):
    dbg(f"Commande FusionSolar reçue: {kwargs}")
    action = kwargs.get("action")
    chat_id = kwargs.get("chat_id")

    if action == "status":
        cookie_exists = bool(_read_text_file(CONFIG["cookie_file"]))
        roarand_exists = bool(_read_text_file(CONFIG["roarand_file"]))
        status = state.get("sensor.fusionsolar_status") or "unknown"
        last_update = state.get("sensor.fusionsolar_last_update") or "n/a"
        _notify("ℹ️ FusionSolar status\n" f"Cookie: {'présent' if cookie_exists else 'absent'}\n" f"Roarand: {'présent' if roarand_exists else 'absent'}\n" f"Status: {status}\n" f"Last update: {last_update}", target=chat_id)
        return

    if action == "test":
        try:
            dbg("Action test: fetch immédiat")
            metrics = task.executor(fetch_all_sync)
            update_sensors(metrics)
            _notify("✅ Test FusionSolar OK\n\n" + build_telegram_message(metrics), target=chat_id)
        except Exception as e:
            dbg(f"Action test échouée: {e}")
            _notify("❌ Test FusionSolar échoué\n" + str(e), target=chat_id)
        return

    if action == "reset":
        dbg("Action reset")
        _delete_file(CONFIG["cookie_file"])
        _delete_file(CONFIG["roarand_file"])
        state.set("sensor.fusionsolar_status", value="reset")
        _notify("✅ Secrets FusionSolar supprimés : cookie + Roarand.", target=chat_id)
        return

    dbg(f"Action inconnue: {action}")
    _notify(f"❌ Action FusionSolar inconnue: {action}", target=chat_id)
