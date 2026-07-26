import subprocess
import os
import re
from datetime import datetime

TARGET_NAME      = "ha-slave"
TARGET_IP        = "172.27.66.3"
WG_ADDON_SLUG    = "a0d7b954_wireguard"

# ── Paramètres configurables ─────────────────────────────────────────────────────────
CHECK_CRON_MIN    = 5    # fréquence du cron (minutes)
CYCLE_MARGIN_SEC  = 30   # marge de sécurité avant le prochain trigger (secondes)
TEST_INTERVAL_SEC = 30   # intervalle entre chaque sous-test (secondes)
# ────────────────────────────────────────────────────────────────────────────

# Tout le reste se calcule automatiquement
CHECK_INTERVAL_SEC   = CHECK_CRON_MIN * 60
USABLE_SEC           = CHECK_INTERVAL_SEC - CYCLE_MARGIN_SEC
MAX_ATTEMPTS         = USABLE_SEC // TEST_INTERVAL_SEC
CHECK_CRON           = f"cron(*/{CHECK_CRON_MIN} * * * *)"
WG_HANDSHAKE_MAX_AGE = CHECK_INTERVAL_SEC

TWILIO_TARGET    = "+41792763781"
TELEGRAM_CHAT_ID = 7332342681

link_down      = False
_check_running = False


def _get_wireguard_stats():
    """Lit les logs de l'addon WireGuard via l'API Supervisor.
    Retourne (handshake_ok, hs_detail, transfer_ok, transfer_detail)."""
    try:
        token = os.environ.get("SUPERVISOR_TOKEN", "")
        if not token:
            return False, "SUPERVISOR_TOKEN absent", False, "SUPERVISOR_TOKEN absent"

        result = subprocess.run(
            [
                "curl", "-sf",
                "-H", f"Authorization: Bearer {token}",
                f"http://supervisor/addons/{WG_ADDON_SLUG}/logs"
            ],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return False, "API Supervisor inaccessible", False, "API Supervisor inaccessible"

        lines = result.stdout.splitlines()

        # ── Handshake ──
        handshake_ok = False
        hs_detail = f"peer {TARGET_IP} non trouvé"
        found_peer = False
        for line in lines:
            if "allowed ips" in line and TARGET_IP in line:
                found_peer = True
                continue
            if found_peer and "latest handshake" in line:
                minutes, seconds = 0, 0
                m = re.search(r'(\d+) minute', line)
                if m:
                    minutes = int(m.group(1))
                s = re.search(r'(\d+) second', line)
                if s:
                    seconds = int(s.group(1))
                age = minutes * 60 + seconds
                if age < WG_HANDSHAKE_MAX_AGE:
                    handshake_ok = True
                    hs_detail = f"handshake il y a {age}s"
                else:
                    hs_detail = f"handshake trop ancien ({age}s, max={WG_HANDSHAKE_MAX_AGE}s)"
                break
            if found_peer and "allowed ips" in line and TARGET_IP not in line:
                found_peer = False

        # ── Transfer (rx + tx > 0) ──
        transfer_ok = False
        transfer_detail = "transfer non trouvé"
        for line in reversed(lines):
            if "transfer:" in line:
                m = re.search(
                    r"transfer:\s*([\d.]+)\s*(\w+)\s*received,\s*([\d.]+)\s*(\w+)\s*sent",
                    line
                )
                if m:
                    def to_bytes(val, unit):
                        factors = {"B": 1, "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3}
                        return int(float(val) * factors.get(unit.upper(), 1))
                    rx = to_bytes(m.group(1), m.group(2))
                    tx = to_bytes(m.group(3), m.group(4))
                    transfer_detail = f"rx={m.group(1)} {m.group(2)} | tx={m.group(3)} {m.group(4)}"
                    transfer_ok = rx > 0 and tx > 0
                break

        return handshake_ok, hs_detail, transfer_ok, transfer_detail

    except FileNotFoundError:
        return False, "curl non disponible", False, "curl non disponible"
    except Exception as e:
        return False, f"erreur supervisor: {e}", False, f"erreur supervisor: {e}"


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
            f"critères: handshake<{WG_HANDSHAKE_MAX_AGE}s + transfer rx/tx>0 | "
            f"attempts={MAX_ATTEMPTS} interval={TEST_INTERVAL_SEC}s"
        )

        details = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            hs_ok, hs_detail, tr_ok, tr_detail = _get_wireguard_stats()

            log.debug(
                f"  tentative {attempt}/{MAX_ATTEMPTS} | "
                f"handshake={'OK' if hs_ok else 'KO'} ({hs_detail}) | "
                f"transfer={'OK' if tr_ok else 'KO'} ({tr_detail})"
            )

            # UP uniquement si handshake ET transfer sont OK
            if hs_ok and tr_ok:
                if link_down:
                    msg = (
                        f"Lien WireGuard rétabli vers {TARGET_NAME} ({TARGET_IP}).\n"
                        f"Tentative : {attempt}/{MAX_ATTEMPTS}\n"
                        f"Heure : {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                        f"Détail : {hs_detail} | {tr_detail}"
                    )
                    log.warning(f"✅ {msg}")
                    _clear_down_notification()
                    _notify_up(msg)

                link_down = False
                _set_status("up", f"{hs_detail} | {tr_detail}")
                log.info(
                    f"✅ wireguard_ha_slave_check terminé - lien OK "
                    f"(tentative {attempt}/{MAX_ATTEMPTS}) | {hs_detail} | {tr_detail}"
                )
                return

            # L'un ou les deux KO → on continue la boucle
            details = (
                f"handshake={'OK' if hs_ok else 'KO'} ({hs_detail}) | "
                f"transfer={'OK' if tr_ok else 'KO'} ({tr_detail})"
            )
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
