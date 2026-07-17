import subprocess
from datetime import datetime


def _notify(msg, chat_id=None):
    data = {"message": msg}
    if chat_id:
        data["target"] = chat_id
    service.call("telegram_bot", "send_message", **data)


@time_trigger("startup")
def dismiss_telegram_error():
    log.info("dismiss_telegram_error demarre")
    service.call("persistent_notification", "dismiss", notification_id="telegram_error")


def check_and_pull(chat_id=None):
    log.info("check_and_pull demarre")

    # Stash les modifs locales (ex: logs/ha_warnings_errors.log) pour ne pas bloquer le pull
    subprocess.run(
        ["git", "-C", "/config/pyscript", "stash"],
        capture_output=True, text=True
    )

    result = subprocess.run(
        ["git", "-C", "/config/pyscript", "pull"],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        msg = result.stderr.strip()
        log.error("check_and_pull -- git pull echoue : " + msg)
        service.call("persistent_notification", "create",
            title="Git pull echoue",
            message=msg + "\n\nHeure : " + datetime.now().strftime("%H:%M:%S"),
            notification_id="gitpull_error"
        )
        _notify("ghpull echoue :\n" + msg, chat_id)
        return

    output = result.stdout.strip()

    if "up to date" in output.lower():
        log.info("check_and_pull -- deja a jour")
        _notify("Pyscript deja a jour, aucun nouveau commit.", chat_id)
    else:
        log.info("check_and_pull -- nouveau commit : " + output)
        service.call("persistent_notification", "create",
            title="Nouveau commit recupere",
            message=output + "\n\nHeure : " + datetime.now().strftime("%H:%M:%S"),
            notification_id="gitpull_success"
        )
        service.call("persistent_notification", "dismiss", notification_id="gitpull_error")
        _notify("Nouveau code recupere depuis GitHub :\n" + output, chat_id)


@event_trigger("pyscript_gh")
def handle_pyscript_gh(action=None, chat_id=None, **kwargs):
    if action == "pull":
        check_and_pull(chat_id=chat_id)
