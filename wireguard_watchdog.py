import subprocess
from datetime import datetime

TARGET_NAME      = "ha-slave"
TARGET_IP        = "172.27.66.3"
WG_INTERFACE     = "wg0"

# ── Paramètres configurables ───────────────────────────────────────────────────
CHECK_CRON_MIN    = 5    # fréquence du cron (minutes)
CYCLE_MARGIN_SEC  = 30   # marge de sécurité avant le prochain trigger (secondes)
TEST_INTERVAL_SEC = 30   # intervalle entre chaque sous-test (secondes)
# ──────────────────────────────────────────────────────────────────────────────

# Tout le reste se calcule automatiquement
CHECK_INTERVAL_SEC   = CHECK_CRON_MIN * 60
USABLE_SEC           = CHECK_INTERVAL_SEC - CYCLE_MARGIN_SEC
PING_TIMEOUT         = TEST_INTERVAL_SEC
MAX_ATTEMPTS         = USABLE_SEC // TEST_INTERVAL_SEC
CHECK_CRON           = f"cron(*/{CHECK_CRON_MIN} * * * *)"
WG_HANDSHAKE_MAX_AGE = CHECK_INTERVAL_SEC

TWILIO_TARGET    = "+41792763781"
TELEGRAM_CHAT_ID = 7332342681

link_down      = False
_check_running = False


def _ping_once(ip):
    result = subprocess.run(
        ["ping", "-c", "1", "-W", str(PING_TIMEOUT), ip],
        capture_output=True,
        text=True
    )
    return result.returncode == 0, result.stdout.strip(), result.stderr.strip()


def _check_handshake():
    result = subprocess.run(
        ["wg", "show", WG_INTERFACE, "latest-handshakes"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return False, "wg show échoué"
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) == 2:
            age = int(datetime.now().timestamp()) - int(parts[1])
            if age < WG_HANDSHAKE_MAX_AGE:
                return True, f"handshake il y a {age}s"
            return False, f"handshake trop ancien ({age}s)"
    return False, "aucun handshake trouvé"


def _send_telegram(message):
    service.call(
        "telegram_bot",
        "send_message",
        target=[TELEGRAM_CHAT_ID],
        message=message
    )


def _notify_down(message):
    service.call(
        "persistent_notification",
        "create",
        title="🔌 WireGuard déconnecté",
        message=message,
        notification_id="wireguard_ha_slave_down"
    )
    service.call(
        "notify",
        "notifier_twilio",
        message=message,
        target=[TWILIO_TARGET]
    )
    _send_telegram(f"🔌 {message}")


def _notify_up(message):
    _send_telegram(f"✅ {message}")


def _clear_down_notification():
    service.call(
        "persistent_notification",
        "dismiss",
        notification_id="wireguard_ha_slave_down"
    )


def _set_status(status, details=""):
    state.set(
        "sensor.wireguard_ha_slave_status",
        value=status,
        new_attributes={
            "friendly_name": "WireGuard ha-slave",
            "target_ip": TARGET_IP,
            "ping_timeout": PING_TIMEOUT,
            "max_attempts": MAX_ATTEMPTS,
            "last_check": datetime.now().isoformat(),
            "details": details,
        }
    )


def _run_check(source="cron"):
    global link_down, _check_running

    if _check_running:
        log.warning("⚠ wireguard_ha_slave_check déjà en cours, skip")
        return
    _check_running = True

    try:
        log.info(
            f"▶ wireguard_ha_slave_check démarré ({source}) | "
            f"attempts={MAX_ATTEMPTS} interval={TEST_INTERVAL_SEC}s "
            f"ping_timeout={PING_TIMEOUT}s handshake_max={WG_HANDSHAKE_MAX_AGE}s"
        )

        details = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            hs_ok,   hs_detail               = _check_handshake()
            ping_ok, ping_stdout, ping_stderr = _ping_once(TARGET_IP)

            log.debug(
                f"  tentative {attempt}/{MAX_ATTEMPTS} | "
                f"handshake={'OK' if hs_ok else 'KO'} | "
                f"ping={'OK' if ping_ok else 'KO'}"
            )

            if hs_ok or ping_ok:
                # Au moins un des deux OK → lien considéré UP
                if link_down:
                    msg = (
                        f"Lien WireGuard rétabli vers {TARGET_NAME} ({TARGET_IP}).\n"
                        f"Tentative : {attempt}/{MAX_ATTEMPTS}\n"
                        f"Heure : {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                    )
                    log.warning(f"✅ {msg}")
                    _clear_down_notification()
                    _notify_up(msg)

                link_down = False
                _set_status("up", f"handshake={'OK' if hs_ok else hs_detail} | ping={'OK' if ping_ok else 'KO'}")
                log.info(f"✅ wireguard_ha_slave_check terminé - lien OK (tentative {attempt}/{MAX_ATTEMPTS})")
                return

            # Les deux KO → on attend et on retente (sauf dernière tentative)
            details = f"handshake={hs_detail} | ping={ping_stderr or ping_stdout or 'KO'}"
            _set_status("down", details)
            log.warning(f"⚠ tentative {attempt}/{MAX_ATTEMPTS} KO | {details}")

            if attempt < MAX_ATTEMPTS:
                task.sleep(TEST_INTERVAL_SEC)

        # Toutes les tentatives épuisées → ALARME
        if not link_down:
            msg = (
                f"Lien WireGuard indisponible vers {TARGET_NAME} ({TARGET_IP}).\n"
                f"Toutes les tentatives échouées : {MAX_ATTEMPTS}/{MAX_ATTEMPTS}\n"
                f"Heure : {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                f"Détail : {details}"
            )
            log.error(f"❌ {msg}")
            _notify_down(msg)
            link_down = True

        log.info("wireguard_ha_slave_check terminé - lien KO")

    finally:
        _check_running = False


@time_trigger(CHECK_CRON)
def wireguard_ha_slave_check():
    _run_check("cron")


@service
def wireguard_ha_slave_check_now():
    _run_check("manuel")
