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
    cookie = get_cookie()

    headers = {
        "Cookie": cookie,
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

        nodes = {n["id"]: n for n in flow["data"]["flow"]["nodes"]}

        pv_power = float(nodes["0"]["value"])
        load_power = float(nodes["5"]["value"])
        battery_power = float(nodes["4"]["value"])
        battery_soc = float(nodes["4"]["deviceTips"]["SOC"])
        battery_charge_capacity = float(nodes["4"]["deviceTips"]["CHARGE_CAPACITY"])
        battery_discharge_capacity = float(nodes["4"]["deviceTips"]["DISCHARGE_CAPACITY"])

        grid_import = 0.0
        
        links = (((flow or {}).get("data") or {}).get("flow") or {}).get("links") or []
        
        for link in links:
            desc = link.get("description") or {}
            label = desc.get("label") or ""
            value = desc.get("value") or ""
        
            if "buy.power" in label:
                try:
                    grid_import = float(value.replace(" kW", ""))
                except Exception:
                    pass

        midnight = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)

        balance = await get_json(
            session,
            "/rest/pvms/web/station/v3/overview/energy-balance",
            {
                "stationDn": STATION,
                "timeDim": 2,
                "timeZone": 2,
                "timeZoneStr": "Europe/Zurich",
                "queryTime": int(midnight.timestamp() * 1000),
            },
        )

        return {
            "pv_power": pv_power,
            "load_power": load_power,
            "battery_power": battery_power,
            "battery_soc": battery_soc,
            "battery_charge_capacity": battery_charge_capacity,
            "battery_discharge_capacity": battery_discharge_capacity,
            "grid_import": grid_import,
            "raw_balance": balance,
        }


async def update_sensors():
    d = await get_data()

    state.set("sensor.fs_pv_power", value=str(d["pv_power"]), new_attributes={"unit_of_measurement": "kW"})
    state.set("sensor.fs_load_power", value=str(d["load_power"]), new_attributes={"unit_of_measurement": "kW"})
    state.set("sensor.fs_battery_power", value=str(d["battery_power"]), new_attributes={"unit_of_measurement": "kW"})
    state.set("sensor.fs_battery_soc", value=str(d["battery_soc"]), new_attributes={"unit_of_measurement": "%"})
    state.set("sensor.fs_grid_import", value=str(d["grid_import"]), new_attributes={"unit_of_measurement": "kW"})


@time_trigger("period(now, 5min)")
async def auto_update():
    try:
        await update_sensors()
        log.info("[FusionSolar] update OK")
    except Exception as e:
        log.error("[FusionSolar] " + str(e))
