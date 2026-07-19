# /config/pyscript/fusionsolar.py

from datetime import datetime
from zoneinfo import ZoneInfo

CONFIG = {
    "base": "https://uni004eu5.fusionsolar.huawei.com",
    "station": "NE=152120280",
    "tz": "Europe/Zurich",
}

TZ = ZoneInfo(CONFIG["tz"])

SECRETS_PATH = "/config/secrets.yaml"
SECRETS_KEY_COOKIE = "fusionsolar_cookie"
SECRETS_KEY_ROARAND = "fusionsolar_roarand"


# =========================
# TELEGRAM
# =========================
def notify(msg, chat=None):
    """Envoie un message Telegram sans parse_mode."""
    data = {"message": str(msg)}
    if chat:
        data["target"] = chat
    service.call("telegram_bot", "send_message", **data)


# =========================
# PURE PYTHON (natif — appelable via task.executor)
# =========================
@pyscript_compile
def _read_secrets_native(path, key_cookie, key_roarand):
    """Lit cookie et roarand depuis secrets.yaml."""
    import yaml as _yaml

    with open(path, "r", encoding="utf-8") as f:
        data = _yaml.safe_load(f) or {}

    return {
        "cookie": data.get(key_cookie, "") or "",
        "roarand": data.get(key_roarand, "") or "",
    }


@pyscript_compile
def fetch_data(cookie, roarand):
    """Interroge l'API FusionSolar, retourne les métriques PV."""
    import requests as _req
    from datetime import datetime
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("Europe/Zurich")
    BASE = "https://uni004eu5.fusionsolar.huawei.com"
    STATION = "NE=152120280"

    if not cookie:
        raise RuntimeError("COOKIE_MISSING")

    s = _req.Session()
    headers = {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
    }
    if roarand:
        headers["Roarand"] = roarand
    s.headers.update(headers)

    now = datetime.now(TZ)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    params = {
        "stationDn": STATION,
        "timeDim": 2,
        "queryTime": int(midnight.timestamp() * 1000),
    }

    r1 = s.get(
        BASE + "/rest/pvms/web/station/v3/overview/energy-balance",
        params=params,
        timeout=20,
    )
    if "json" not in r1.headers.get("content-type", ""):
        raise RuntimeError("SESSION_EXPIRED")
    eb = r1.json()
    if not eb.get("success"):
        raise RuntimeError("API_ERROR")

    r2 = s.get(
        BASE + "/rest/pvms/web/station/v1/overview/energy-flow",
        params={"stationDn": STATION},
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

    values = data.get("productPower", [])
    valid = [i for i, v in enumerate(values) if v not in ["--", "", None]]
    if not valid:
        raise RuntimeError("NO_VALID_DATA")

    idx = valid[-1]
    pv = float(values[idx])
    load = float((data.get("usePower") or [0])[idx])
    charge = float((data.get("chargePower") or [0])[idx])
    discharge = float((data.get("dischargePower") or [0])[idx])

    # Puissance réseau : positif = import, négatif = export
    grid_vals = data.get("buyPower") or data.get("gridPower") or []
    grid = float(grid_vals[idx]) if grid_vals else 0.0

    # SOC : cherche le nœud dont deviceTips contient "SOC"
    nodes = ef.get("data", {}).get("flow", {}).get("nodes", [])
    soc = None
    for n in nodes:
        tips = n.get("deviceTips") or {}
        if "SOC" in tips:
            soc = float(tips["SOC"])
            break
    if soc is None:
        raise RuntimeError("SOC_NOT_FOUND")

    return {
        "pv": pv,
        "load": load,
        "soc": soc,
        "charge": charge,
        "discharge": discharge,
        "grid": grid,
    }


# =========================
# WRAPPER
# =========================
def fetch():
    """Lit les credentials depuis secrets.yaml puis interroge l'API."""
    try:
        creds = task.executor(
            _read_secrets_native,
            SECRETS_PATH,
            SECRETS_KEY_COOKIE,
            SECRETS_KEY_ROARAND,
        )
    except Exception as e:
        raise RuntimeError("SECRETS_READ_ERROR: " + str(e))

    cookie = creds.get("cookie", "")
    roarand = creds.get("roarand", "")

    return task.executor(fetch_data, cookie, roarand)


def _update_sensors(m):
    """Écrit les valeurs dans les senseurs pyscript de HA."""
    sensor.fs_pv = m["pv"]
    sensor.fs_pv.unit_of_measurement = "kW"
    sensor.fs_pv.friendly_name = "FusionSolar PV"
    sensor.fs_pv.device_class = "power"

    sensor.fs_load = m["load"]
    sensor.fs_load.unit_of_measurement = "kW"
    sensor.fs_load.friendly_name = "FusionSolar Consommation"
    sensor.fs_load.device_class = "power"

    sensor.fs_soc = m["soc"]
    sensor.fs_soc.unit_of_measurement = "%"
    sensor.fs_soc.friendly_name = "FusionSolar Batterie SOC"
    sensor.fs_soc.device_class = "battery"

    sensor.fs_charge = m["charge"]
    sensor.fs_charge.unit_of_measurement = "kW"
    sensor.fs_charge.friendly_name = "FusionSolar Charge batterie"
    sensor.fs_charge.device_class = "power"

    sensor.fs_discharge = m["discharge"]
    sensor.fs_discharge.unit_of_measurement = "kW"
    sensor.fs_discharge.friendly_name = "FusionSolar Décharge batterie"
    sensor.fs_discharge.device_class = "power"

    sensor.fs_grid = m["grid"]
    sensor.fs_grid.unit_of_measurement = "kW"
    sensor.fs_grid.friendly_name = "FusionSolar Réseau"
    sensor.fs_grid.device_class = "power"


# =========================
# COMMAND HANDLER
# =========================
@event_trigger("fusionsolar_command")
def handle(**kwargs):
    """Gère les commandes FusionSolar envoyées via Telegram."""
    action = kwargs.get("action")
    chat = kwargs.get("chat_id")

    if action == "test":
        try:
            m = fetch()
            _update_sensors(m)
            notify(
                "FusionSolar OK\n"
                "PV : " + str(m["pv"]) + " kW\n"
                "SOC : " + str(m["soc"]) + " %\n"
                "Réseau : " + str(m["grid"]) + " kW",
                chat,
            )
        except Exception as e:
            notify("Erreur test: " + str(e), chat)

    elif action == "health":
        lines = ["FusionSolar Health"]
        try:
            creds = task.executor(
                _read_secrets_native,
                SECRETS_PATH,
                SECRETS_KEY_COOKIE,
                SECRETS_KEY_ROARAND,
            )
            ck = creds.get("cookie", "")
            rr = creds.get("roarand", "")
            lines.append("OK Cookie present" if ck else "FAIL Cookie absent")
            lines.append(
                "OK Roarand present" if rr else "WARN Roarand absent"
            )
        except Exception as e:
            lines.append("FAIL secrets.yaml illisible: " + str(e))
        try:
            m = fetch()
            lines.append(
                "OK API | PV "
                + str(m["pv"])
                + " kW | SOC "
                + str(m["soc"])
                + " %"
                + " | Réseau "
                + str(m["grid"])
                + " kW"
            )
        except Exception as e:
            lines.append("FAIL API: " + str(e))
        try:
            pv_val = state.get("sensor.fs_pv")
            lines.append("OK sensor.fs_pv = " + str(pv_val))
        except Exception as e:
            lines.append("FAIL sensor: " + str(e))
        notify("\n".join(lines), chat)

    elif action == "status":
        notify("FusionSolar actif", chat)

    elif action == "reset":
        notify("Reset OK", chat)


# =========================
# AUTO (toutes les 5 min)
# =========================
@time_trigger("period(now, 5min)")
def auto():
    """Rafraîchit les données FusionSolar et met à jour les senseurs."""
    try:
        m = fetch()
        _update_sensors(m)
        log.debug(
            "[FS] MAJ OK — PV "
            + str(m["pv"])
            + " kW | SOC "
            + str(m["soc"])
            + " %"
        )
    except Exception as e:
        log.error("[FS][ERR] Fetch failed: " + str(e))
