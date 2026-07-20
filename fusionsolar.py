from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import json

BASE = "https://uni004eu5.fusionsolar.huawei.com"
STATION = "NE=152120280"
TZ = ZoneInfo("Europe/Zurich")


def get_cookie():
    """
    Lire le cookie depuis input_text ou secret.
    Adapte selon ton installation.
    """

    cookie = pyscript.config.get(
        "fusionsolar_cookie",
        ""
    )

    if not cookie:
        raise RuntimeError(
            "fusionsolar_cookie absent"
        )

    return cookie


def get_data():

    cookie = get_cookie()

    session = requests.Session()

    session.headers.update({
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    })

    #
    # ENERGY FLOW
    #

    flow = session.get(
        BASE +
        "/rest/pvms/web/station/v3/overview/energy-flow",
        params={
            "stationDn": STATION,
            "featureId": "aifc"
        },
        timeout=20
    ).json()

    nodes = {
        n["id"]: n
        for n in flow["data"]["flow"]["nodes"]
    }

    pv_power = float(
        nodes["0"]["value"]
    )

    load_power = float(
        nodes["5"]["value"]
    )

    battery_power = float(
        nodes["4"]["value"]
    )

    battery_soc = float(
        nodes["4"]["deviceTips"]["SOC"]
    )

    battery_charge_capacity = float(
        nodes["4"]["deviceTips"]["CHARGE_CAPACITY"]
    )

    battery_discharge_capacity = float(
        nodes["4"]["deviceTips"]["DISCHARGE_CAPACITY"]
    )

    #
    # GRID IMPORT
    #

    grid_import = 0.0

    for link in flow["data"]["flow"]["links"]:

        label = (
            link.get("description", {})
            .get("label", "")
        )

        value = (
            link.get("description", {})
            .get("value", "")
        )

        if "buy.power" in label:

            try:
                grid_import = float(
                    value.replace(" kW", "")
                )
            except Exception:
                pass

    #
    # ENERGY BALANCE
    #

    midnight = datetime.now(
        TZ
    ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    balance = session.get(
        BASE +
        "/rest/pvms/web/station/v3/overview/energy-balance",
        params={
            "stationDn": STATION,
            "timeDim": 2,
            "timeZone": 2,
            "timeZoneStr": "Europe/Zurich",
            "queryTime": int(
                midnight.timestamp() * 1000
            )
        },
        timeout=20
    ).json()

    return {
        "pv_power": pv_power,
        "load_power": load_power,
        "battery_power": battery_power,
        "battery_soc": battery_soc,
        "battery_charge_capacity":
            battery_charge_capacity,
        "battery_discharge_capacity":
            battery_discharge_capacity,
        "grid_import": grid_import,
        "raw_balance": balance
    }


def update_sensors():

    d = get_data()

    state.set(
        "sensor.fs_pv_power",
        value=str(d["pv_power"]),
        new_attributes={
            "unit_of_measurement": "kW"
        }
    )

    state.set(
        "sensor.fs_load_power",
        value=str(d["load_power"]),
        new_attributes={
            "unit_of_measurement": "kW"
        }
    )

    state.set(
        "sensor.fs_battery_power",
        value=str(d["battery_power"]),
        new_attributes={
            "unit_of_measurement": "kW"
        }
    )

    state.set(
        "sensor.fs_battery_soc",
        value=str(d["battery_soc"]),
        new_attributes={
            "unit_of_measurement": "%"
        }
    )

    state.set(
        "sensor.fs_grid_import",
        value=str(d["grid_import"]),
        new_attributes={
            "unit_of_measurement": "kW"
        }
    )


@time_trigger("period(now, 5min)")
def auto_update():

    try:

        update_sensors()

        log.info(
            "[FusionSolar] update OK"
        )

    except Exception as e:

        log.error(
            "[FusionSolar] "
            + str(e)
        )
