"""
Pyscript app: FusionSolar

Deploy:
  /config/pyscript/apps/fusionsolar/__init__.py   ← ce fichier
  /config/fusionsolar_fetch.py                    ← script autonome (hors pyscript)

Edit COOKIE and ROARAND below. Never commit the real cookie to GitHub.
"""

import json
import subprocess
from datetime import datetime, timezone

CONFIG = {
    "base_url":    "https://uni004eu5.fusionsolar.huawei.com",
    "station_dn":  "NE=152120280",
    "cookie":      "PASTE_EDGE_NETWORK_COOKIE_HERE",
    "roarand":     "",
}

SCRIPT_PATH    = "/config/fusionsolar_fetch.py"
TELEGRAM_CHAT_ID = 7332342681


def _run_fetch(config, script_path):
    """
    Runs fusionsolar_fetch.py as a subprocess.
    Passes config as JSON via stdin, reads result as JSON from stdout.
    Completely outside pyscript AST — no wrapping possible.
    """
    result = subprocess.run(
        ["python3", script_path],
        input=json.dumps(config),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"fusionsolar_fetch.py exit {result.returncode}: {result.stderr.strip()}")
    return json.loads(result.stdout)


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


def _send_telegram(message):
    service.call("telegram_bot", "send_message",
                 target=[TELEGRAM_CHAT_ID], message=message)


def _set_sensor(entity_id, value, unit=None, device_class=None, state_class=None, attrs=None):
    if value is None:
        log.debug(f"FusionSolar: {entity_id} ignoré (None)")
        return
    a = dict(attrs or {})
    if unit:         a["unit_of_measurement"] = unit
    if device_class: a["device_class"]        = device_class
    if state_class:  a["state_class"]         = state_class
    try:
        value = round(float(value), 3)
    except Exception:
        pass
    state.set(entity_id, value=value, new_attributes=a)
    log.debug(f"FusionSolar: ✅ {entity_id} = {value} {unit or ''}")


@time_trigger("period(now, 2min)")
def update_fusionsolar_sensors():
    log.info("FusionSolar: ▶ update (toutes les 2 min)")
    try:
        data = task.executor(_run_fetch, CONFIG, SCRIPT_PATH)
        _flush_logs(data.get("logs"))

        status = data.get("status", "ok")
        log.info(
            f"FusionSolar: reçu status={status} | "
            f"PV={data.get('pv_power_kw')}kW SOC={data.get('battery_soc_percent')}% "
            f"import={data.get('grid_import_kw')}kW export={data.get('grid_export_kw')}kW "
            f"load={data.get('load_power_kw')}kW daily={data.get('daily_energy_kwh')}kWh"
        )

        status_icon = "✅" if status == "ok" else ("⚠️" if status == "partial" else "❌")
        tg_msg = (
            f"{status_icon} *FusionSolar* — {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n"
            f"🌞 PV\t\t`{data.get('pv_power_kw')} kW`\n"
            f"🏠 Conso\t`{data.get('load_power_kw')} kW`\n"
            f"🔋 Batterie\t`{data.get('battery_soc_percent')} %`\n"
            f"⬆️ Charge bat\t`{data.get('battery_charge_kw')} kW`\n"
            f"⬇️ Décharge bat\t`{data.get('battery_discharge_kw')} kW`\n"
            f"📥 Soutirage\t`{data.get('grid_import_kw')} kW`\n"
            f"📤 Injection\t`{data.get('grid_export_kw')} kW`\n"
            f"⚡ Prod jour\t`{data.get('daily_energy_kwh')} kWh`\n"
            f"📅 Prod mois\t`{data.get('monthly_energy_kwh')} kWh`\n"
            f"Status\t\t`{status}`"
        )
        if data.get("error"):
            tg_msg += f"\n⚠️ Erreurs: `{data.get('error')}`"
        _send_telegram(tg_msg)
        log.info("FusionSolar: 💬 Telegram envoyé")

        attrs = {
            "plant_dn":        data.get("plant_dn"),
            "last_update_utc": data.get("ts_utc"),
            "source":          "FusionSolar web cookie session",
            "status":          status,
        }
        if data.get("error"):
            attrs["error"] = data.get("error")

        _set_sensor("sensor.fusionsolar_pv_power",                data.get("pv_power_kw"),          "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_load_power",              data.get("load_power_kw"),         "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_grid_import_power",       data.get("grid_import_kw"),        "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_grid_export_power",       data.get("grid_export_kw"),        "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_battery_soc",             data.get("battery_soc_percent"),   "%",   "battery", "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_battery_charge_power",    data.get("battery_charge_kw"),     "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_battery_discharge_power", data.get("battery_discharge_kw"),  "kW",  "power",   "measurement",      attrs)
        _set_sensor("sensor.fusionsolar_daily_energy",            data.get("daily_energy_kwh"),      "kWh", "energy",  "total_increasing", attrs)
        _set_sensor("sensor.fusionsolar_monthly_energy",          data.get("monthly_energy_kwh"),    "kWh", "energy",  "total_increasing", attrs)
        _set_sensor("sensor.fusionsolar_yearly_energy",           data.get("yearly_energy_kwh"),     "kWh", "energy",  "total_increasing", attrs)
        _set_sensor("sensor.fusionsolar_total_energy",            data.get("total_energy_kwh"),      "kWh", "energy",  "total_increasing", attrs)

        state.set("sensor.fusionsolar_status",       value=status,                                  new_attributes=attrs)
        state.set("sensor.fusionsolar_last_success", value=datetime.now(timezone.utc).isoformat(),  new_attributes=attrs)

        metrics_ok = 0
        if data.get("pv_power_kw")        is not None: metrics_ok += 1
        if data.get("load_power_kw")       is not None: metrics_ok += 1
        if data.get("grid_import_kw")      is not None: metrics_ok += 1
        if data.get("battery_soc_percent") is not None: metrics_ok += 1
        log.info(f"FusionSolar: ✅ update complet — {metrics_ok}/4 métriques disponibles")

    except Exception as e:
        log.error(f"FusionSolar: ❌ EXCEPTION — {type(e).__name__}: {e}")
        state.set("sensor.fusionsolar_status", value="error",
                  new_attributes={"error": str(e), "plant_dn": CONFIG.get("station_dn")})
