import subprocess
from datetime import datetime

TARGET_NAME           = "ha-slave"
TARGET_IP             = "172.27.66.3"
WG_INTERFACE          = "wg0"

# ── Seul paramètre à modifier pour changer la fréquence ──────────────────────
CHECK_INTERVAL_SEC    = 5 * 60          # 5 minutes
PING_TIMEOUT          = 5               # secondes timeout par ping (-W)
CYCLE_MARGIN_SEC      = 30              # marge avant le prochain trigger
FAIL_THRESHOLD        = 3              # alarme après N cycles KO consécutifs
# ─────────────────────────────────────────────────────────────────────────────

CHECK_CRON            = f"cron(*/{CHECK_INTERVAL_SEC // 60} * * * *)"
WG_HANDSHAKE_MAX_AGE  = CHECK_INTERVAL_SEC - CYCLE_MARGIN_SEC
PING_RETRIES          = (CHECK_INTERVAL_SEC - CYCLE_MARGIN_SEC) // PING_TIMEOUT

TWILIO_TARGET         = "+41792763781"
TELEGRAM_CHAT_ID      = 7332342681

fail_count    = 0
link_down     = False
_check_running = False


def _ping_once(ip):
    result = subprocess.run(
        ["ping", "-c", "1", "-W", str(PING_TIMEOUT), ip],
        capture_output=True,
        text=True
    )
    return result.returncode == 0, result.stdout.strip(), result.stderr.strip()


def _ping_with_retries(ip):
    for attempt in range(1, PING_RETRIES + 1):
        ok, stdout, stderr = _ping_once(ip)
        log.debug(f"  ping tentative {attempt}/{PING_RETRIES} -> ok={ok}")
        if ok:
            return True, stdout, stderr
    return False, stdout, stderr


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
            "fail_count": fail_count,
            "last_check": datetime.now().isoformat(),
            "details": details,
        }
    )


def _run_check(source="cron"):
    global fail_count, link_down, _check_running

    if _check_running:
        log.warning("⚠ wireguard_ha_slave_check déjà en cours, skip")
        return
    _check_running = True

    try:
        log.info(f"▶ wireguard_ha_slave_check démarré ({source}) | retries={PING_RETRIES} timeout={PING_TIMEOUT}s handshake_max={WG_HANDSHAKE_MAX_AGE}s")

        hs_ok,   hs_detail              = _check_handshake()
        ping_ok, ping_stdout, ping_stderr = _ping_with_retries(TARGET_IP)

        log.debug(f"  handshake={'OK' if hs_ok else 'KO'} | ping={'OK' if ping_ok else 'KO'}")

        if hs_ok and ping_ok:
            if link_down:
                msg = (
                    f"Lien WireGuard rétabli vers {TARGET_NAME} ({TARGET_IP}).\n"
                    f"Heure : {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                )
                log.warning(f"✅ {msg}")
                _clear_down_notification()
                _notify_up(msg)
            fail_count = 0
            link_down  = False
            _set_status("up", f"ping OK | {hs_detail}")
            log.info("✅ wireguard_ha_slave_check terminé - lien OK")
            return

        # Au moins un des deux a échoué
        fail_count += 1
        details = (
            f"handshake={'OK' if hs_ok else hs_detail} | "
            f"ping={'OK' if ping_ok else (ping_stderr or ping_stdout or 'KO')}"
        )
        _set_status("down", details)
        log.warning(f"⚠ wireguard_ha_slave_check - échec {fail_count}/{FAIL_THRESHOLD} | {details}")

        if fail_count >= FAIL_THRESHOLD and not link_down:
            msg = (
                f"Lien WireGuard indisponible vers {TARGET_NAME} ({TARGET_IP}).\n"
                f"Échecs consécutifs : {fail_count}\n"
                f"Heure : {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                f"Détail : {details}"
            )
            log.error(f"❌ {msg}")
            _notify_down(msg)
            link_down = True

        log.info("✅ wireguard_ha_slave_check terminé")

    finally:
        _check_running = False


@time_trigger(CHECK_CRON)
def wireguard_ha_slave_check():
    _run_check("cron")


@service
def wireguard_ha_slave_check_now():
    _run_check("manuel")
