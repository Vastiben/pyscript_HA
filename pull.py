import subprocess
from datetime import datetime


def _notify(msg, chat_id=None):
    data = {"message": msg}
    if chat_id:
        data["target"] = chat_id
    service.call("telegram_bot", "send_message", **data)


@time_trigger("startup")
def dismiss_telegram_error():
    log.info("▶ dismiss_telegram_error démarré")
    service.call("persistent_notification", "dismiss",
        notification_id="telegram_error"
    )
    log.info("✅ dismiss_telegram_error terminé")


def check_and_pull(chat_id=None):
    log.info("▶ check_and_pull (manuel) démarré")

    # Mettre de côté les modifications locales pour ne pas bloquer le pull
    subprocess.run(
        ["git", "-C", "/config/pyscript", "stash"],
        capture_output=True,
        text=True
    )

    result = subprocess.run(
        ["git", "-C", "/config/pyscript", "pull"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        msg = result.stderr.strip()
        log.error(f"❌ check_and_pull — git pull échoué : {msg}")
        service.call("persistent_notification", "create",
            title="❌ Git pull échoué",
            message=f"{msg}\n\nHeure : {datetime.now().strftime('%H:%M:%S')}",
            notification_id="gitpull_error"
        )
        _notify(f"❌ /ghpull échoué :\n{msg}", chat_id)
        return

    if "up to date" in result.stdout.lower():
        log.info("✅ check_and_pull — aucun nouveau commit")
        _notify("✅ Pyscript déjà à jour, aucun nouveau commit.", chat_id)
    else:
        output = result.stdout.strip()
        log.info(f"✅ check_and_pull — nouveau commit récupéré : {output}")
        service.call("persistent_notification", "create",
            title="🔄 Nouveau commit récupéré",
            message=f"{output}\n\nHeure : {datetime.now().strftime('%H:%M:%S')}",
            notification_id="gitpull_success"
        )
        service.call("persistent_notification", "dismiss",
            notification_id="gitpull_error"
        )
        _notify(f"🔄 Nouveau code récupéré depuis GitHub :\n{output}", chat_id)


@event_trigger("pyscript_gh")
def handle_pyscript_gh(action=None, chat_id=None, **kwargs):
    """Réagit aux commandes /ghpull."""
    if action == "pull":
        check_and_pull(chat_id=chat_id)
