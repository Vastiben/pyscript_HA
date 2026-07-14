import subprocess
from datetime import datetime

TARGET_NAME = "ha-slave"
TARGET_IP = "172.27.66.3"
CHECK_CRON = "cron(*/1 * * * *)"
FAIL_THRESHOLD = 5
PING_RETRIES = 3
PING_RETRY_DELAY = 2
TWILIO_TARGET = "+41792763781"
TELEGRAM_CHAT_ID = 7332342681

fail_count = 0
link_down = False


def _ping_once(ip):
    result = subprocess.run(
        ["ping", "-c", "1", "-W", "2", ip],
        capture_output=True,
        text=True
    )
    return result.returncode == 0, result.stdout.strip(), result.stderr.strip()


def _ping_with_retries(ip):
    last_stdout, last_stderr = "", ""
    for attempt in range(1, PING_RETRIES + 1):
        ok, stdout, stderr = _ping_once(ip)
        log.debug(f"  ping tentative {attempt}/{PING_RETRIES} -> ok={ok}")
        if ok:
            return True, stdout, stderr
        last_stdout, last_stderr = stdout, stderr
        task.sleep(PING_RETRY_DELAY)
    return False, last_stdout, last_stderr


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
    global fail_count, link_down

    task.unique("wireguard_ha_slave_check")
    log.info(f"▶ wireguard_ha_slave_check démarré ({source})")

    ok, stdout, stderr = _ping_with_retries(TARGET_IP)

    if ok:
        if link_down:
            msg = (
                f"Lien WireGuard rétabli vers {TARGET_NAME} ({TARGET_IP}).\n"
                f"Heure : {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
            )
            log.warning(f"✅ {msg}")
            _clear_down_notification()
            _notify_up(msg)

        fail_count = 0
        link_down = False
        _set_status("up", "Ping OK")
        log.info("✅ wireguard_ha_slave_check terminé - lien OK")
        return

    fail_count += 1
    details = stderr or stdout or "Ping KO après retries"
    _set_status("down", details)
    log.warning(f"⚠ wireguard_ha_slave_check - échec {fail_count}/{FAIL_THRESHOLD} vers {TARGET_IP}")

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


@time_trigger(CHECK_CRON)
def wireguard_ha_slave_check():
    _run_check("cron")


@service
def wireguard_ha_slave_check_now():
    _run_check("manual")
