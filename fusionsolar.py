"""
pyscript: FusionSolar cookie-based sensors.

Put these two files in /config/pyscript/:
  - fusionsolar.py      (this file — pyscript triggers & HA state)
  - fusionsolar_lib.py  (pure Python logic — safe for task.executor)

Then edit CONFIG below:
  - paste the Cookie header captured from Edge/Chrome Network
  - keep station_dn = NE=152120280 unless your plant changes

Security:
  - Do not commit this file to Git with the cookie inside.
"""

import importlib.util
import os
from datetime import datetime, timezone

CONFIG = {
    "base_url": "https://uni004eu5.fusionsolar.huawei.com",
    "station_dn": "NE=152120280",
    "referer": "https://uni004eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms",
    # Paste the complete Cookie request header value here:
    "cookie": "PASTE_EDGE_NETWORK_COOKIE_HERE",
    "update_every": "period(now, 2min)",
}


def _load_lib():
    """Load fusionsolar_lib.py as a plain Python module (not wrapped by pyscript)."""
    lib_path = "/config/pyscript/fusionsolar_lib.py"
    spec = importlib.util.spec_from_file_location("fusionsolar_lib", lib_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _flush_logs(logs):
    for entry in (logs or []):
        if entry.startswith("ERROR"):
            log.error(f"FusionSolar: {entry[6:]}")
        elif entry.startswith("WARNING"):
            log.warning(f"FusionSolar: {entry[8:]}")
        elif entry.startswith("INFO"):
            log.info(f"FusionSolar: {entry[5:]}")
        else:
            log.debug(f"FusionSolar: {entry[6:]}")


def _set_sensor(entity_id, value, unit=None, device_class=None, state_class=None, attrs=None):
    if value is None:
        log.debug(f"FusionSolar: {entity_id} ignoré (None)")
        return
    a = dict(attrs or {})
    if unit:         a["unit_of_measurement"] = unit
    if device_class: a["device_class"] = device_class
    if state_class:  a["state_class"] = state_class
    try:
        value = round(float(value), 3)
    except Exception:
        pass
    state.set(entity_id, value=value, new_attributes=a)
    log.debug(f"FusionSolar: ✅ {entity_id} = {value} {unit or ''}")


@time_trigger(CONFIG["update_every"])
def update_fusionsolar_sensors():
    log.info("FusionSolar: ▶ déclenchement update (toutes les 2 min)")
    try:
        # Load the pure-Python lib and grab its fetch function BEFORE passing to executor.
        # lib.fetch is a plain Python function, not wrapped by pyscript.
        lib = _load_lib()
        data = task.executor(lib.fetch, CONFIG)

        _flush_logs(data.get("logs"))

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
            log.warning(f"FusionSolar: erreurs partielles — {data.get('error')}")

        log.debug("FusionSolar: mise à jour des sensors HA...")
        _set_sensor("sensor.fusionsolar_pv_power",               data.get("pv_power_kw"),          "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_load_power",             data.get("load_power_kw"),         "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_grid_import_power",      data.get("grid_import_kw"),        "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_grid_export_power",      data.get("grid_export_kw"),        "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_battery_soc",            data.get("battery_soc_percent"),   "%",   "battery", "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_battery_charge_power",   data.get("battery_charge_kw"),     "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_battery_discharge_power",data.get("battery_discharge_kw"),  "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_daily_energy",           data.get("daily_energy_kwh"),      "kWh", "energy",  "total_increasing", attrs)
        _set_sensor("sensor.fusionsolar_monthly_energy",         data.get("monthly_energy_kwh"),    "kWh", "energy",  "total_increasing", attrs)
        _set_sensor("sensor.fusionsolar_yearly_energy",          data.get("yearly_energy_kwh"),     "kWh", "energy",  "total_increasing", attrs)
        _set_sensor("sensor.fusionsolar_total_energy",           data.get("total_energy_kwh"),      "kWh", "energy",  "total_increasing", attrs)

        state.set("sensor.fusionsolar_status",       value=status,                                  new_attributes=attrs)
        state.set("sensor.fusionsolar_last_success", value=datetime.now(timezone.utc).isoformat(),  new_attributes=attrs)
        log.info(
            f"FusionSolar: ✅ update complet — "
            f"{sum(1 for k in ['pv_power_kw','load_power_kw','grid_import_kw','battery_soc_percent'] if data.get(k) is not None)}/4 "
            f"métriques principales disponibles"
        )

    except Exception as e:
        log.error(f"FusionSolar: ❌ EXCEPTION — {type(e).__name__}: {e}")
        state.set("sensor.fusionsolar_status", value="error",
                  new_attributes={"error": str(e), "plant_dn": CONFIG.get("station_dn")})
