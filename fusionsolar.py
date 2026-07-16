"""
🔹 FusionSolar Collector
🔹 Met à jour sensors HA
🔹 Répond aux commandes Telegram

Logs: [FS]
"""

import requests
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import time

CONFIG = {
    "base": "https://uni004eu5.fusionsolar.huawei.com",
    "station": "NE=152120280",
    "cookie": "/config/fusionsolar/cookie.txt",
    "roarand": "/config/fusionsolar/roarand.txt",
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
def read(path):
    p = Path(path)
    return p.read_text().strip() if p.exists() else ""


def notify(msg, chat=None):
    dbg(f"Notify → {msg[:50]}")
    data = {"message": msg}
    if chat:
        data["target"] = chat

    service.call("telegram_bot", "send_message", **data)


# =========================
# API
# =========================
def session():

    cookie = read(CONFIG["cookie"])
    roarand = read(CONFIG["roarand"])

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


def get(s, path, params):

    url = CONFIG["base"] + path
    dbg(f"GET {path}")

    r = s.get(url, params=params, timeout=20)

    if "json" not in r.headers.get("content-type", ""):
        raise RuntimeError("Session expirée")

    j = r.json()

    if not j.get("success"):
        raise RuntimeError("API erreur")

    return j


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

    eb = get(s, "/rest/pvms/web/station/v3/overview/energy-balance", params)
    ef = get(s, "/rest/pvms/web/station/v1/overview/energy-flow", {"stationDn": CONFIG["station"]})

    return extract(eb, ef)


# =========================
# EXTRACTION
# =========================
def extract(eb, ef):

    d = eb["data"]

    idx = max(i for i,v in enumerate(d["productPower"]) if v not in ["--", ""])

    pv = float(d["productPower"][idx])
    load = float(d["usePower"][idx])
    charge = float(d["chargePower"][idx])
    discharge = float(d["dischargePower"][idx])

    battery = next(n for n in ef["data"]["flow"]["nodes"] if n["id"] == "4")

    soc = float(battery["deviceTips"]["SOC"])

    dbg(f"PV={pv} LOAD={load} SOC={soc}")

    return {
        "pv": pv,
        "load": load,
        "soc": soc,
        "charge": charge,
        "discharge": discharge,
    }


# =========================
# SENSORS
# =========================
def update(m):

    state.set("sensor.fs_pv", m["pv"])
    state.set("sensor.fs_load", m["load"])
    state.set("sensor.fs_soc", m["soc"])

    dbg("Sensors updated")


# =========================
# TELEGRAM COMMAND HANDLER
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
            update(m)
            notify(f"PV {m['pv']} kW | SOC {m['soc']}%", chat)

        elif action == "reset":
            Path(CONFIG["cookie"]).unlink(missing_ok=True)
            Path(CONFIG["roarand"]).unlink(missing_ok=True)
            notify("✅ reset effectué", chat)

    except Exception as e:
        notify(f"❌ erreur: {e}", chat)


# =========================
# AUTOMATIQUE (optionnel)
# =========================
@time_trigger("period(now, 5min)")
def auto():

    try:
        m = task.executor(fetch)
        update(m)
    except Exception as e:
        dbg(f"Auto error: {e}")
