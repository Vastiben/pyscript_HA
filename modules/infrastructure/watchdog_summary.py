# watchdog_summary.py
# Résume l'état de tous les watchdogs actifs et envoie une notification
# persistante + Telegram.
#
# Pour ajouter un watchdog futur : ajouter une entrée dans WATCHDOGS.

from datetime import datetime

# ── Paramètres ───────────────────────────────────────────────────────────────
SUMMARY_CRON     = "cron(0 * * * *)"   # chaque heure — changer en "cron(0 8,20 * * *)" pour 2x/jour
TELEGRAM_CHAT_ID = 7332342681

# Liste des watchdogs à surveiller.
# Chaque entrée : (label affiché, sensor_entity_id, champ details dans les attributs)
# Pour ajouter un watchdog : dupliquer une ligne et adapter.
WATCHDOGS = [
    {
        "label":   "WireGuard → ha-slave",
        "sensor":  "sensor.wireguard_ha_slave_status",
        "details_attr": "details",
    },
    # Exemple pour un futur watchdog :
    # {
    #     "label":   "Internet → DNS",
    #     "sensor":  "sensor.internet_watchdog_status",
    #     "details_attr": "details",
    # },
]
# ────────────────────────────────────────────────────────────────────────────


def _get_watchdog_status(wdg):
    """Lit l'état d'un watchdog depuis son sensor.
    Retourne (ok: bool, status: str, details: str, last_check: str)."""
    try:
        sensor_val = state.get(wdg["sensor"])
        attrs      = state.getattr(wdg["sensor"]) or {}
        details    = attrs.get(wdg["details_attr"], "")
        last_check = attrs.get("last_check", "inconnue")

        if sensor_val is None or sensor_val == "unavailable":
            return False, "unavailable", "sensor non disponible", "inconnue"

        ok = sensor_val.lower() == "up"
        return ok, sensor_val, details, last_check

    except Exception as e:
        return False, "erreur", str(e), "inconnue"


def _format_last_check(iso_str):
    """Formate un timestamp ISO en heure lisible."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return iso_str


def _build_summary():
    """Construit le texte du résumé pour tous les watchdogs.
    Retourne (all_ok: bool, lines_notification: str, lines_telegram: str)."""
    now_txt  = datetime.now().strftime("%d.%m.%Y %H:%M")
    n_lines  = [f"Résumé Watchdog — {now_txt}\n"]
    tg_lines = [f"📊 *Résumé Watchdog* — {now_txt}\n"]
    all_ok   = True

    for wdg in WATCHDOGS:
        ok, status, details, last_check = _get_watchdog_status(wdg)
        icon = "✅" if ok else "❌"
        lc   = _format_last_check(last_check)

        n_lines.append(
            f"{icon} {wdg['label']}\n"
            f"   État      : {status}\n"
            f"   Détail    : {details}\n"
            f"   Dernier check : {lc}\n"
        )
        tg_lines.append(
            f"{icon} *{wdg['label']}*\n"
            f"  État: `{status}` | {lc}\n"
            f"  {details}\n"
        )

        if not ok:
            all_ok = False

    summary_icon = "✅ Tout OK" if all_ok else "⚠️ Problème(s) détecté(s)"
    footer_n  = f"\n{summary_icon}"
    footer_tg = f"\n{summary_icon}"

    return all_ok, "\n".join(n_lines) + footer_n, "\n".join(tg_lines) + footer_tg


def _send_summary(all_ok, notif_text, telegram_text):
    title = "✅ Watchdog OK" if all_ok else "⚠️ Watchdog — problème(s)"

    service.call(
        "persistent_notification",
        "create",
        title=title,
        message=notif_text,
        notification_id="watchdog_summary"
    )

    service.call(
        "telegram_bot",
        "send_message",
        target=[TELEGRAM_CHAT_ID],
        message=telegram_text
    )


@time_trigger(SUMMARY_CRON)
def watchdog_summary():
    log.info("▶ watchdog_summary démarré")
    all_ok, notif_text, telegram_text = _build_summary()
    _send_summary(all_ok, notif_text, telegram_text)
    status_txt = "tout OK" if all_ok else "problème(s) détecté(s)"
    log.info(f"✅ watchdog_summary terminé — {status_txt}")


@service
def watchdog_summary_now():
    """Déclenche manuellement le résumé watchdog."""
    log.info("▶ watchdog_summary_now démarré (manuel)")
    all_ok, notif_text, telegram_text = _build_summary()
    _send_summary(all_ok, notif_text, telegram_text)
    log.info("✅ watchdog_summary_now terminé")
