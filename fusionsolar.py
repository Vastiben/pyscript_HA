"""
FusionSolar PRODUCTION VERSION

✅ robuste
✅ retry automatique
✅ gestion cookie expiré
✅ logs propres
✅ safe executor

Logs:
[FS] INFO
[FS][ERR] ERROR
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
    "cookie": "/config/fusionsolar/cookie.txt",
    "roarand": "/config/fusionsolar/roarand.txt",
    "tz": "Europe/Zurich",
    "debug": False,   # 🔥 PROD = False
    "retry": 2,
}

TZ = ZoneInfo(CONFIG["tz"])

# =========================
# LOGGING
# =========================
def dbg(msg):
    if CONFIG["debug"]:
        log.info(f"[FS] {msg}")

def err(msg):
    log.error(f"[FS][ERR] {msg}")

# =========================
# FILES
# =========================
def read(path):
    p = Path(path)
    return p.read_text().strip() if p.exists() else ""

# =========================
# TELEGRAM
# =========================
def notify(msg, chat=None):

    data = {"message": msg}

    if chat:
        data["target"] = chat

    try:
        service.call("telegram_bot", "send_message", **data)
    except Exception as e:
        err(f"Telegram failed: {e}")

# =========================
# PURE PYTHON (executor safe)
# =========================
def fetch_data():

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

    now = datetime.now(TZ)
    midnight = now.replace(hour=0, minute=0, second=0)

    params = {
        "stationDn": CONFIG["station"],
        "timeDim": 2,
        "queryTime": int(midnight.timestamp() * 1000),
        "_": int(time.time() * 1000),
    }

    def get(path, params):
        r = s.get(CONFIG["base"] + path, params=params, timeout=20)

        if "json" not in r.headers.get("content-type", ""):
            raise RuntimeError("SESSION_EXPIRED")

        j = r.json()

        if not j.get("success"):
            raise RuntimeError("API_ERROR")

        return j

    eb = get("/rest/pvms/web/station/v3/overview/energy-balance", params)
    ef = get("/rest/pvms/web/station/v1/overview/energy-flow", {"stationDn": CONFIG["station"]})

    d = eb["data"]

    idx = max(i for i,v in enumerate(d["productPower"]) if v not in ["--",""])

    pv = float(d["productPower"][idx])
    load = float(d["usePower"][idx])
    charge = float(d["chargePower"][idx])
    discharge = float(d["dischargePower"][idx])

    battery = next(n for n in ef["data"]["flow"]["nodes"] if n["id"] == "4")

    soc = float(battery["deviceTips"]["SOC"])

    return {
        "pv": pv,
        "load": load,
        "soc": soc,
        "charge": charge,
        "discharge": discharge,
    }

# =========================
# SAFE WRAPPER
# =========================
def fetch():

    for attempt in range(CONFIG["retry"] + 1):

        try:
            data = task.executor(fetch_data)

            dbg(f"OK PV={data['pv']} SOC={data['soc']}")
            return data

        except Exception as e:

            err(f"Fetch attempt {attempt} failed: {e}")

            if "SESSION_EXPIRED" in str(e):
                raise RuntimeError("COOKIE_EXPIRED")

            if attempt == CONFIG["retry"]:
                raise

            time.sleep(2)

# =========================
# SENSORS
# =========================
def update(m):

    state.set("sensor.fs_pv", m["pv"])
    state.set("sensor.fs_load", m["load"])
    state.set("sensor.fs_soc", m["soc"])

# =========================
# COMMAND HANDLER
# =========================
@event_trigger("fusionsolar_command")
def handle(**kwargs):

    action = kwargs.get("action")
    chat = kwargs.get("chat_id")

    try:

        if action == "status":
            notify("✅ FusionSolar actif", chat)

        elif action == "test":
            m = fetch()
            update(m)
            notify(f"☀️ {m['pv']} kW | 🔋 {m['soc']}%", chat)

        elif action == "reset":
            Path(CONFIG["cookie"]).unlink(missing_ok=True)
            Path(CONFIG["roarand"]).unlink(missing_ok=True)
            notify("✅ reset effectué", chat)

    except Exception as e:

        err(e)

        if "COOKIE_EXPIRED" in str(e):
            notify("⚠️ Cookie expiré → /fscookie", chat)
        else:
            notify(f"❌ erreur: {e}", chat)

# =========================
# AUTO POLLING
# =========================
@time_trigger("period(now, 5min)")
def auto():

    try:
        m = fetch()
        update(m)

    except Exception as e:

        err(e)

        if "COOKIE_EXPIRED" in str(e):
            notify("⚠️ Cookie FusionSolar expiré")

        else:
            dbg(f"Auto error: {e}")
