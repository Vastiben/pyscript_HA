# /config/pyscript/fusionsolar.py

from datetime import datetime
from zoneinfo import ZoneInfo

CONFIG = {
    "base": "https://uni004eu5.fusionsolar.huawei.com",
    "station": "NE=152120280",
    "tz": "Europe/Zurich",
}

TZ = ZoneInfo(CONFIG["tz"])

# Cache des credentials en mémoire (mis à jour par login)
_cookie = None
_roarand = None


# =========================
# TELEGRAM
# =========================
def notify(msg, chat=None):
    """Envoie un message Telegram sans parse_mode."""
    data = {"message": str(msg)}
    if chat:
        data["target"] = [int(chat)]
    service.call("telegram_bot", "send_message", **data)


# =========================
# LOGIN AUTOMATIQUE
# =========================
@pyscript_compile
def _do_login(username, password):
    """Se connecte à FusionSolar et retourne (cookie, roarand).
    Utilise le chiffrement RSA de la clé publique fournie par /unisso/pubkey.action.
    """
    import requests as _req
    import base64

    BASE = "https://uni004eu5.fusionsolar.huawei.com"
    s = _req.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": BASE,
        "Referer": BASE + "/unisso/login.action",
        "Connection": "keep-alive",
    })

    # Étape 1 : charger la page de login pour obtenir les cookies de session
    s.get(BASE + "/unisso/login.action", timeout=20)

    # Étape 2 : récupérer la clé publique RSA
    r0 = s.get(BASE + "/unisso/pubkey.action", timeout=20)
    pub_ct = r0.headers.get("content-type", "")
    pub_data = r0.json() if "json" in pub_ct else {}

    # Chiffrement RSA du mot de passe avec la clé publique du serveur
    pub_key_str = pub_data.get("pubKey", "")
    if pub_key_str:
        try:
            from Crypto.PublicKey import RSA
            from Crypto.Cipher import PKCS1_v1_5
            rsa_key = RSA.import_key(pub_key_str)
            cipher = PKCS1_v1_5.new(rsa_key)
            encrypted_pwd = base64.b64encode(
                cipher.encrypt(password.encode("utf-8"))
            ).decode("utf-8")
        except Exception:
            # Fallback : pas de chiffrement si pycryptodome absent
            encrypted_pwd = password
    else:
        encrypted_pwd = password

    # Étape 3 : POST login avec le mot de passe chiffré
    payload = {
        "organizationName": "",
        "userName": username,
        "userNameReg": username,
        "language": "fr_FR",
        "timeZone": 2,
        "password": encrypted_pwd,
        "value": encrypted_pwd,
    }
    r1 = s.post(
        BASE + "/unisso/v2/validateUser.action",
        json=payload,
        timeout=20,
    )

    ct = r1.headers.get("content-type", "")
    if "json" not in ct:
        raise RuntimeError("LOGIN_FAILED: réponse non-JSON -> " + r1.text[:300])

    resp = r1.json()
    if not resp.get("success") and resp.get("errorCode"):
        raise RuntimeError("LOGIN_FAILED: " + str(resp.get("errorCode")) + " " + str(resp.get("failCode", "")))

    # Extraire JSESSIONID
    jsession = s.cookies.get("JSESSIONID", "")
    if not jsession:
        set_cookie = r1.headers.get("Set-Cookie", "")
        for part in set_cookie.split(";"):
            if "JSESSIONID" in part:
                jsession = part.split("=")[-1].strip()
                break

    if not jsession:
        raise RuntimeError("LOGIN_FAILED: JSESSIONID introuvable dans les cookies")

    roarand = r1.headers.get("Roarand", "") or resp.get("data", {}).get("roarand", "")

    cookie_str = "JSESSIONID=" + jsession
    return cookie_str, roarand


def _login():
    """Wrapper pyscript : lit les credentials, appelle _do_login, met à jour le cache."""
    global _cookie, _roarand
    username = pyscript.config.get("fusionsolar_user", "")
    password = pyscript.config.get("fusionsolar_pw", "")
    if not username or not password:
        raise RuntimeError("LOGIN_MISSING_CREDENTIALS -- vérifier configuration.yaml")
    result = task.executor(_do_login, username, password)
    _cookie, _roarand = result
    log.info("[FS] Login OK - nouveau cookie obtenu")
    return _cookie, _roarand


# =========================
# PURE PYTHON (natif - appelable via task.executor)
# =========================
@pyscript_compile
def fetch_data(cookie, roarand):
    """Interroge l'API FusionSolar, retourne les metriques PV."""
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": BASE + "/pvmswebsite/assets/build/index.html",
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

    grid_vals = data.get("buyPower") or data.get("gridPower") or []
    grid = float(grid_vals[idx]) if grid_vals else 0.0

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
# WRAPPER FETCH
# =========================
def fetch():
    """Utilise le cookie en cache (ou pyscript.config en fallback) pour interroger l'API."""
    global _cookie, _roarand

    cookie = _cookie or pyscript.config.get("fusionsolar_cookie", "")
    roarand = _roarand or pyscript.config.get("fusionsolar_roarand", "")

    if not cookie:
        raise RuntimeError(
            "COOKIE_MISSING -- verifier configuration.yaml > pyscript > global_ctx"
        )

    try:
        return task.executor(fetch_data, cookie, roarand)
    except RuntimeError as e:
        if "SESSION_EXPIRED" in str(e):
            log.warning("[FS] Session expirée, tentative de relogin...")
            _login()
            return task.executor(fetch_data, _cookie, _roarand)
        raise


def _update_sensors(m):
    """Ecrit les valeurs dans les senseurs pyscript de HA via state.set()."""
    state.set(
        "sensor.fs_pv",
        value=str(m["pv"]),
        new_attributes={
            "unit_of_measurement": "kW",
            "friendly_name": "FusionSolar PV",
            "device_class": "power",
            "state_class": "measurement",
        },
    )
    state.set(
        "sensor.fs_load",
        value=str(m["load"]),
        new_attributes={
            "unit_of_measurement": "kW",
            "friendly_name": "FusionSolar Consommation",
            "device_class": "power",
            "state_class": "measurement",
        },
    )
    state.set(
        "sensor.fs_soc",
        value=str(m["soc"]),
        new_attributes={
            "unit_of_measurement": "kW",
            "friendly_name": "FusionSolar Batterie SOC",
            "device_class": "battery",
            "state_class": "measurement",
        },
    )
    state.set(
        "sensor.fs_charge",
        value=str(m["charge"]),
        new_attributes={
            "unit_of_measurement": "kW",
            "friendly_name": "FusionSolar Charge batterie",
            "device_class": "power",
            "state_class": "measurement",
        },
    )
    state.set(
        "sensor.fs_discharge",
        value=str(m["discharge"]),
        new_attributes={
            "unit_of_measurement": "kW",
            "friendly_name": "FusionSolar Decharge batterie",
            "device_class": "power",
            "state_class": "measurement",
        },
    )
    state.set(
        "sensor.fs_grid",
        value=str(m["grid"]),
        new_attributes={
            "unit_of_measurement": "kW",
            "friendly_name": "FusionSolar Reseau",
            "device_class": "power",
            "state_class": "measurement",
        },
    )


# =========================
# AUTO-LOGIN (toutes les 8h)
# =========================
@time_trigger("period(now, 8h)")
def auto_login():
    """Renouvelle le cookie FusionSolar automatiquement toutes les 8h."""
    try:
        _login()
        log.info("[FS] Auto-login OK")
    except Exception as e:
        log.error("[FS][ERR] Auto-login failed: " + str(e))


# =========================
# COMMAND HANDLER
# =========================
@event_trigger("fusionsolar_command")
def handle(**kwargs):
    """Gere les commandes FusionSolar envoyees via Telegram."""
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
                "Reseau : " + str(m["grid"]) + " kW",
                chat,
            )
        except Exception as e:
            notify("Erreur test: " + str(e), chat)

    elif action == "login":
        try:
            _login()
            notify("Login FusionSolar OK - nouveau cookie obtenu", chat)
        except Exception as e:
            notify("Login FAIL: " + str(e), chat)

    elif action == "health":
        lines = ["FusionSolar Health"]
        ck = _cookie or pyscript.config.get("fusionsolar_cookie", "")
        rr = _roarand or pyscript.config.get("fusionsolar_roarand", "")
        usr = pyscript.config.get("fusionsolar_user", "")
        lines.append("OK Cookie present" if ck else "FAIL Cookie absent")
        lines.append("OK Roarand present" if rr else "WARN Roarand absent")
        lines.append("OK Credentials presents" if usr else "WARN fusionsolar_user absent")
        try:
            m = fetch()
            lines.append(
                "OK API | PV "
                + str(m["pv"]) + " kW"
                + " | SOC " + str(m["soc"]) + "%"
                + " | Reseau " + str(m["grid"]) + " kW"
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
    """Rafraichit les donnees FusionSolar et met a jour les senseurs."""
    try:
        m = fetch()
        _update_sensors(m)
        log.debug(
            "[FS] MAJ OK - PV "
            + str(m["pv"]) + " kW | SOC "
            + str(m["soc"]) + "%"
        )
    except Exception as e:
        log.error("[FS][ERR] Fetch failed: " + str(e))
