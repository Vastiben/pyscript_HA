from datetime import datetime
from zoneinfo import ZoneInfo
import aiohttp

BASE = "https://uni004eu5.fusionsolar.huawei.com"
STATION = "NE=152120280"
TZ = ZoneInfo("Europe/Zurich")


def get_cookie():
    cookie = pyscript.config.get("fusionsolar_cookie", "")
    if not cookie:
        raise RuntimeError("fusionsolar_cookie absent")
    return cookie


async def get_json(session, path, params):
    async with session.get(BASE + path, params=params, timeout=20) as resp:
        resp.raise_for_status()
        return await resp.json()


async def get_data():
    headers = {
        "Cookie": get_cookie(),
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        flow = await get_json(
            session,
            "/rest/pvms/web/station/v3/overview/energy-flow",
            {
                "stationDn": STATION,
                "featureId": "aifc",
            },
        )

    flow_data = ((flow or {}).get("data") or {}).get("flow") or {}
    nodes = {n["id"]: n for n in (flow_data.get("nodes") or []) if "id" in n}

    pv = nodes.get("0") or {}
    battery = nodes.get("4") or {}
    load = nodes.get("5") or {}
    battery_tips = battery.get("deviceTips") or {}

    pv_power = float(pv.get("value") or 0)
    load_power = float(load.get("value") or 0)
    battery_power = float(battery.get("value") or 0)
    battery_soc = float(battery_tips.get("SOC") or 0)
    battery_charge_capacity = float(battery_tips.get("CHARGE_CAPACITY") or 0)
    battery_discharge_capacity = float(battery_tips.get("DISCHARGE_CAPACITY") or 0)

    grid_import = 0.0
    for link in flow_data.get("links") or []:
        desc = link.get("description") or {}
        label = desc.get("label") or ""
        value = desc.get("value") or ""

        if "buy.power" in label:
            try:
                grid_import = float(value.replace(" kW", ""))
            except Exception:
                pass

    return {
        "pv_power": pv_power,
        "load_power": load_power,
        "battery_power": battery_power,
        "battery_soc": battery_soc,
        "battery_charge_capacity": battery_charge_capacity,
        "battery_discharge_capacity": battery_discharge_capacity,
        "grid_import": grid_import,
    }


def publish_sensor(entity_id, value, unit=None, icon=None):
    attrs = {
        "state_class": "measurement",
    }

    if unit:
        attrs["unit_of_measurement"] = unit
    if icon:
        attrs["icon"] = icon

    state.set(entity_id, value=value, new_attributes=attrs)


async def update_sensors():
    d = await get_data()

    publish_sensor("sensor.fs_pv_power", d["pv_power"], "kW", "mdi:solar-power")
    publish_sensor("sensor.fs_load_power", d["load_power"], "kW", "mdi:home-lightning-bolt")
    publish_sensor("sensor.fs_battery_power", d["battery_power"], "kW", "mdi:battery-high")
    publish_sensor("sensor.fs_battery_soc", d["battery_soc"], "%", "mdi:battery")
    publish_sensor("sensor.fs_grid_import", d["grid_import"], "kW", "mdi:transmission-tower-import")
    publish_sensor("sensor.fs_battery_charge_capacity", d["battery_charge_capacity"], "kWh", "mdi:battery-plus")
    publish_sensor("sensor.fs_battery_discharge_capacity", d["battery_discharge_capacity"], "kWh", "mdi:battery-minus")


@time_trigger(cron(*/1 * * * *)
async def auto_update():
    try:
        await update_sensors()
        log.info("[FusionSolar] flow update OK")
    except Exception as e:
        log.error(f"[FusionSolar] {e}")
