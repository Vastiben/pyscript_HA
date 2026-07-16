"""
/config/pyscript/fusionsolar.py

🔹 Récupération FusionSolar
🔹 Sensors Home Assistant
🔹 Réponses Telegram via événements

Architecture:
telegram_commands → event → fusionsolar

Endpoints:
- energy-balance
- energy-flow
- station-real-kpi
"""

import requests
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import time

# =========================
# CONFIG
# =========================
CONFIG = {
    "base": "https://uni004eu5.fusionsolar.huawei.com",
    "station": "NE=152120280",
    "cookie_file": "/config/fusionsolar/cookie.txt",
    "roarand_file": "/config/fusionsolar/roarand.txt",
    "tz": "Europe/Zurich",
    "debug": True,
}

TZ = ZoneInfo(CONFIG["tz"])

# =========================
# DEBUG
# =========================
def dbg(msg):
    if CONFIG["debug"]:
        log.info(f"[FS] {msg}")

dbg("✅ fusionsolar.py chargé")

# =========================
# HELPERS
# =========================
def read_file(path):
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text().strip()


def session():
    cookie = read_file(CONFIG["cookie_file"])
    roarand = read_file(CONFIG["roarand_file"])

    if not cookie:
        raise RuntimeError("Cookie manquant")

    s = requests.Session()
    s.headers.update({
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
    })

    if roarand:
        s.headers["Roarand"] = roarand

    return s


def get_json(s, path, params):
    url = CONFIG["base"] + path
    dbg(f"GET {path}")

    r = s.get(url, params=params, timeout=20)

    if "json" not in r.headers.get("content-type", ""):
        raise RuntimeError("Session expirée")

    data = r.json()

    if not data.get("success"):
        raise RuntimeError("API erreur")

    return data


# =========================
# FETCH
# =========================
def fetch():

    s = session()

    now = datetime.now(TZ)
    midnight = now.replace(hour=0, minute=0, second=0)

    params = {
        "stationDn": CONFIG["station"],
        "timeDim": 2,
        "queryTime": int(midnight.timestamp() * 1000),
        "_": int(time.time() * 1000),
    }

    eb = get_json(s, "/rest/pvms/web/station/v3/overview/energy-balance", params)
    ef = get_json(s, "/rest/pvms/web/station/v1/overview/energy-flow", {"stationDn": CONFIG["station"]})

    return extract(eb, ef)


# =========================
# EXTRACTION
# =========================
def extract(eb, ef):

    data = eb["data"]

    # dernier index valide
    idx = max(i for i,v in enumerate(data["productPower"]) if v not in ["--", ""])

    pv = float(data["productPower"][idx])
    load = float(data["usePower"][idx])
    charge = float(data["chargePower"][idx])
    discharge = float(data["dischargePower"][idx])

    nodes = ef["data"]["flow"]["nodes"]

    battery = next(n for n in nodes if n["id"] == "4")
    soc = float(battery["deviceTips"]["SOC"])

    dbg(f"PV={pv} Load={load} SOC={soc}")

    return {
        "pv": pv,
        "load": load,
        "charge": charge,
        "discharge": discharge,
        "soc": soc,
    }


# =========================
# SENSORS
# =========================
def update_sensors(m):

    state.set("sensor.fs_pv", m["pv"])
    state.set("sensor.fs_load", m["load"])
    state.set("sensor.fs_soc", m["soc"])

    dbg("Sensors updated")


# =========================
# TELEGRAM EVENT HANDLER
# =========================
@event_trigger("fusionsolar_command")
def handle(**kwargs):

    dbg(f"EVENT: {kwargs}")

    action = kwargs.get("action")
    chat = kwargs.get("chat_id")

    try:

        if action == "status":
            notify("✅ FusionSolar actif", chat)

        elif action == "test":
            m = task.executor(fetch)
            update_sensors(m)
            notify(f"PV {m['pv']} kW | SOC {m['soc']}%", chat)

        elif action == "reset":
            Path(CONFIG["cookie_file"]).unlink(missing_ok=True)
            Path(CONFIG["roarand_file"]).unlink(missing_ok=True)
            notify("✅ reset effectué", chat)

    except Exception as e:
        notify(f"❌ erreur: {e}", chat)


# =========================
# NOTIFY
# =========================
def notify(msg, chat=None):
    service.call("telegram_bot.send_message", message=msg, target=chat)
