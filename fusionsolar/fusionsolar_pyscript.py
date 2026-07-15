"""
pyscript: FusionSolar cookie-based sensors.

Put this file as:
  /config/pyscript/fusionsolar.py

Then edit CONFIG below:
  - paste the Cookie header captured from Edge/Chrome Network
  - keep station_dn = NE=152120280 unless your plant changes

Security:
  - Do not commit this file to Git with the cookie inside.
  - If you pasted your FusionSolar password into any chat or file, rotate it.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import json
import requests

CONFIG = {
    "base_url": "https://uni004eu5.fusionsolar.huawei.com",
    "station_dn": "NE=152120280",
    "referer": "https://uni004eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms",
    # Paste the complete Cookie request header value here, for example:
    # "cookie": "SESSION=...; other_cookie=...",
    "cookie": "JSESSIONID=520FBE4CD997FE338902E66458AA5663",
    "update_every": "period(now, 2min)",
}


@dataclass
class FusionSolarMetrics:
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


class FusionSolarWebClient:
    def __init__(self, base_url, station_dn, cookie, referer=None, timeout=20):
        self.base_url = base_url.rstrip("/")
        self.station_dn = station_dn
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36 Edg/126.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Cookie": cookie,
            "Referer": referer or self.base_url + "/",
            "Origin": self.base_url,
            "X-Requested-With": "XMLHttpRequest",
        })
        log.debug(f"FusionSolar: client initialisé — base_url={self.base_url} station={self.station_dn}")

    def request_json(self, method, path, params=None, json_body=None):
        url = self.base_url + path
        log.debug(f"FusionSolar: → {method} {path} params={params}")
        r = self.s.request(method, url, params=params, json=json_body, timeout=self.timeout)
        log.debug(f"FusionSolar: ← HTTP {r.status_code} ({len(r.content)} bytes) pour {path}")
        if r.status_code in (401, 403):
            log.error(f"FusionSolar: 🔒 cookie/session rejeté — HTTP {r.status_code} sur {path}. Recapturer le cookie dans Edge/Chrome.")
            raise RuntimeError(f"FusionSolar cookie/session rejected: HTTP {r.status_code}")
        r.raise_for_status()
        return r.json()

    def poll_raw(self):
        raw = {}
        endpoints = {
            "energy_flow":        ("GET", "/rest/pvms/web/station/v1/overview/energy-flow"),
            "energy_balance":     ("GET", "/rest/pvms/web/station/v1/overview/energy-balance"),
            "station_real_kpi":   ("GET", "/rest/pvms/web/station/v1/overview/station-real-kpi"),
            "station_detail":     ("GET", "/rest/pvms/web/station/v1/overview/station-detail"),
        }
        log.info(f"FusionSolar: interrogation de {len(endpoints)} endpoints pour station={self.station_dn}")
        ok_count = 0
        for name, (method, path) in endpoints.items():
            try:
                raw[name] = self.request_json(method, path, params={"stationDn": self.station_dn})
                ok_count += 1
                log.debug(f"FusionSolar: endpoint '{name}' ✅ OK")
            except Exception as e:
                raw[name] = {"_error": str(e)}
                log.warning(f"FusionSolar: endpoint '{name}' ❌ ERREUR — {e}")
        log.info(f"FusionSolar: poll terminé — {ok_count}/{len(endpoints)} endpoints réussis")
        return raw


def normalize_payload(raw, station_dn):
    log.debug("FusionSolar: normalisation du payload brut...")

    pv_kw        = _find_by_key_contains(raw, ["pvPower", "productPower", "productionPower", "realTimePower", "activePower"])
    battery_soc  = _find_by_key_contains(raw, ["batterySoc", "stateOfCharge", "soc"])
    battery_power= _find_by_key_contains(raw, ["batteryPower", "chargeDischargePower", "chargePower", "dischargePower"])
    grid_power   = _find_by_key_contains(raw, ["gridPower", "meterPower", "onGridPower", "disGridPower"])
    load_power   = _find_by_key_contains(raw, ["loadPower", "usePower", "consumptionPower"])
    daily        = _find_by_key_contains(raw, ["dailyEnergy", "dayEnergy", "totalCurrentDayEnergy", "totalProductPower"])
    monthly      = _find_by_key_contains(raw, ["monthEnergy", "monthlyEnergy", "totalCurrentMonthEnergy"])
    yearly       = _find_by_key_contains(raw, ["yearEnergy", "yearlyEnergy", "totalCurrentYearEnergy"])
    total        = _find_by_key_contains(raw, ["cumulativeEnergy", "totalEnergy", "lifetimeEnergy"])

    log.debug(
        f"FusionSolar: valeurs extraites — "
        f"pv={pv_kw}kW, soc={battery_soc}%, bat={battery_power}kW, "
        f"grid={grid_power}kW, load={load_power}kW, "
        f"daily={daily}kWh, monthly={monthly}kWh, yearly={yearly}kWh, total={total}kWh"
    )

    # Avertissement si les métriques essentielles sont None
    if pv_kw is None:
        log.warning("FusionSolar: ⚠️ pv_power_kw est None — clé non trouvée dans le payload. Vérifier les endpoints actifs.")
    if battery_soc is None:
        log.warning("FusionSolar: ⚠️ battery_soc_percent est None — batterie non détectée ou clé absente.")
    if grid_power is None:
        log.warning("FusionSolar: ⚠️ grid_power_kw est None — compteur réseau non détecté.")

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
        log.error(f"FusionSolar: ❌ tous les endpoints ont échoué — {err}")
    elif errors:
        status = "partial"
        err = json.dumps(errors, ensure_ascii=False)
        log.warning(f"FusionSolar: ⚠️ status=partial, endpoints en erreur: {list(errors.keys())}")
    else:
        log.debug("FusionSolar: normalisation OK, status=ok")

    return FusionSolarMetrics(
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
    )


def fetch_fusionsolar_sync():
    cookie = CONFIG["cookie"]
    if not cookie or cookie == "PASTE_EDGE_NETWORK_COOKIE_HERE":
        log.error("FusionSolar: ❌ cookie manquant — éditer /config/pyscript/fusionsolar.py et coller le Cookie header.")
        raise RuntimeError("FusionSolar cookie missing: edit /config/pyscript/fusionsolar.py and paste the Cookie header.")
    log.debug(f"FusionSolar: cookie présent ({len(cookie)} caractères), démarrage du client HTTP")
    client = FusionSolarWebClient(CONFIG["base_url"], CONFIG["station_dn"], cookie, CONFIG.get("referer"))
    raw = client.poll_raw()
    return asdict(normalize_payload(raw, CONFIG["station_dn"]))


def _set_sensor(entity_id, value, unit=None, device_class=None, state_class=None, attrs=None):
    if value is None:
        log.debug(f"FusionSolar: sensor {entity_id} ignoré (valeur None)")
        return
    a = dict(attrs or {})
    if unit:
        a["unit_of_measurement"] = unit
    if device_class:
        a["device_class"] = device_class
    if state_class:
        a["state_class"] = state_class
    try:
        value = round(float(value), 3)
    except Exception:
        pass
    state.set(entity_id, value=value, new_attributes=a)
    log.debug(f"FusionSolar: ✅ {entity_id} = {value} {unit or ''}")


@time_trigger(*/2 * * * *)
def update_fusionsolar_sensors():
    log.info("FusionSolar: ▶ déclenchement update (toutes les 2 min)")
    try:
        data = task.executor(fetch_fusionsolar_sync)
        status = data.get("status", "ok")
        log.info(
            f"FusionSolar: données reçues — status={status} | "
            f"PV={data.get('pv_power_kw')}kW | SOC={data.get('battery_soc_percent')}% | "
            f"grid_import={data.get('grid_import_kw')}kW | grid_export={data.get('grid_export_kw')}kW | "
            f"load={data.get('load_power_kw')}kW | daily={data.get('daily_energy_kwh')}kWh"
        )

        attrs = {
            "plant_dn":        data.get("plant_dn"),
            "last_update_utc": data.get("ts_utc"),
            "source":          "FusionSolar web cookie session",
            "status":          status,
        }
        if data.get("error"):
            attrs["error"] = data.get("error")
            log.warning(f"FusionSolar: erreurs partielles dans les attrs — {data.get('error')}")

        log.debug("FusionSolar: mise à jour des sensors Home Assistant...")
        _set_sensor("sensor.fusionsolar_pv_power",              data.get("pv_power_kw"),         "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_load_power",            data.get("load_power_kw"),        "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_grid_import_power",     data.get("grid_import_kw"),       "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_grid_export_power",     data.get("grid_export_kw"),       "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_battery_soc",           data.get("battery_soc_percent"),  "%",   "battery", "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_battery_charge_power",  data.get("battery_charge_kw"),    "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_battery_discharge_power",data.get("battery_discharge_kw"),"kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_daily_energy",          data.get("daily_energy_kwh"),     "kWh", "energy",  "total_increasing", attrs)
        _set_sensor("sensor.fusionsolar_monthly_energy",        data.get("monthly_energy_kwh"),   "kWh", "energy",  "total_increasing", attrs)
        _set_sensor("sensor.fusionsolar_yearly_energy",         data.get("yearly_energy_kwh"),    "kWh", "energy",  "total_increasing", attrs)
        _set_sensor("sensor.fusionsolar_total_energy",          data.get("total_energy_kwh"),     "kWh", "energy",  "total_increasing", attrs)

        state.set("sensor.fusionsolar_status",       value=status,                                     new_attributes=attrs)
        state.set("sensor.fusionsolar_last_success", value=datetime.now(timezone.utc).isoformat(),     new_attributes=attrs)
        log.info(f"FusionSolar: ✅ update complet — {sum(1 for k in ['pv_power_kw','load_power_kw','grid_import_kw','battery_soc_percent'] if data.get(k) is not None)}/4 métriques principales disponibles")

    except Exception as e:
        log.error(f"FusionSolar: ❌ update_fusionsolar_sensors EXCEPTION — {type(e).__name__}: {e}")
        state.set("sensor.fusionsolar_status", value="error", new_attributes={"error": str(e), "plant_dn": CONFIG.get("station_dn")})
