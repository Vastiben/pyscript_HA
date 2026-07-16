# /config/pyscript/fusionsolar.py

import requests
from datetime import datetime
from zoneinfo import ZoneInfo

CONFIG = {
    "base": "https://uni004eu5.fusionsolar.huawei.com",
    "station": "NE=152120280",
    "tz": "Europe/Zurich",
}

TZ = ZoneInfo(CONFIG["tz"])


# =========================
# TELEGRAM
# =========================
def notify(msg, chat=None):
    data = {"message": msg}
    if chat:
        data["target"] = chat
    service.call("telegram_bot", "send_message", **data)


# =========================
# PURE PYTHON ONLY
# =========================
def fetch_data(cookie, roarand):

    if not cookie:
        raise RuntimeError("COOKIE_MISSING")

    s = requests.Session()

    headers = {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
    }

    if roarand:
        headers["Roarand"] = roarand

    s.headers.update(headers)

    now = datetime.now(TZ)
    midnight = now.replace(hour=0, minute=0, second=0)

    params = {
        "stationDn": CONFIG["station"],
        "timeDim": 2,
        "queryTime": int(midnight.timestamp() * 1000),
    }

    # ENERGY BALANCE
    r1 = s.get(
        CONFIG["base"] + "/rest/pvms/web/station/v3/overview/energy-balance",
        params=params,
        timeout=20,
    )

    if "json" not in r1.headers.get("content-type", ""):
        raise RuntimeError("SESSION_EXPIRED")

    eb = r1.json()

    if not eb.get("success"):
        raise RuntimeError("API_ERROR")

    # ENERGY FLOW
    r2 = s.get(
        CONFIG["base"] + "/rest/pvms/web/station/v1/overview/energy-flow",
        params={"stationDn": CONFIG["station"]},
        timeout=20,
    )

    if "json" not in r2.headers.get("content-type", ""):
        raise RuntimeError("SESSION_EXPIRED")

    ef = r2.json()

    if not ef.get("success"):
        raise RuntimeError("API_ERROR")

    data = eb.get("data")
    if not data:
        raise RuntimeError("NO_DATA")

    # SAFE INDEX
    values = data.get("productPower", [])
    valid = [i for i, v in enumerate(values) if v not in ["--", "", None]]

    if not valid:
        raise RuntimeError("NO_VALID_DATA")

    idx = valid[-1]

    pv = float(values[idx])
    load = float(data.get("usePower", [0])[idx])
    charge = float(data.get("chargePower", [0])[idx])
    discharge = float(data.get("dischargePower", [0])[idx])

    # BATTERY
    nodes = ef.get("data", {}).get("flow", {}).get("nodes", [])

    soc = None
    for n in nodes:
        if n.get("id") == "4":
            soc = float(n.get("deviceTips", {}).get("SOC", 0))
            break

    if soc is None:
        raise RuntimeError("SOC_NOT_FOUND")

    return {
        "pv": pv,
        "load": load,
        "soc": soc,
        "charge": charge,
        "discharge": discharge,
    }


# =========================
# WRAPPER
# =========================
def fetch():

    # ✅ lecture fichier ici (pyscript autorisé)
    cookie = ""
    roarand = ""

    try:
        with open("/config/fusionsolar/cookie.txt") as f:
            cookie = f.read().strip()
    except:
        pass

    try:
        with open("/config/fusionsolar/roarand.txt") as f:
            roarand = f.read().strip()
    except:
        pass

    return task.executor(fetch_data, cookie, roarand)


# =========================
# COMMAND HANDLER
# =========================
@event_trigger("fusionsolar_command")
def handle(**kwargs):

    action = kwargs.get("action")
    chat = kwargs.get("chat_id")

    try:

        if action == "test":

            m = fetch()

            notify(
                f"✅ PV {m['pv']} kW\n"
                f"🔋 SOC {m['soc']}%",
                chat,
            )

        elif action == "health":

            try:
                m = fetch()
                notify(
                    "✅ API OK\n"
                    f"PV {m['pv']} kW\n"
                    f"SOC {m['soc']}%",
                    chat,
                )
            except Exception as e:
                notify(f"❌ Health error: {e}", chat)

        elif action == "status":
            notify("✅ FusionSolar actif", chat)

        elif action == "reset":
            notify("✅ reset OK", chat)

    except Exception as e:

        if "SESSION_EXPIRED" in str(e):
            notify("⚠️ Cookie expiré", chat)
        else:
            notify(f"❌ erreur: {e}", chat)


# =========================
# AUTO
# =========================
@time_trigger("period(now, 5min)")
def auto():

    try:
        fetch()
    except Exception:
        pass
