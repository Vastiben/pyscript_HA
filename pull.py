import subprocess
from datetime import datetime

@time_trigger("cron(*/1 * * * *)")
def check_and_pull():
    result = subprocess.run(
        ["git", "-C", "/config/pyscript", "pull"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        log.error(f"Erreur git pull : {result.stderr.strip()}")
        hass.services.call("persistent_notification", "create", {
            "title": "\u274c Git pull échoué",
            "message": f"{result.stderr.strip()}\n\nHeure : {datetime.now().strftime('%H:%M:%S')}",
            "notification_id": "gitpull_error"
        })
        return

    if "up to date" in result.stdout.lower():
        log.info("Aucun nouveau commit")
    else:
        log.info(f"Nouveau commit récupéré : {result.stdout.strip()}")
        hass.services.call("persistent_notification", "create", {
            "title": "\U0001f504 Nouveau commit disponible",
            "message": f"{result.stdout.strip()}\n\nRecharge pyscript manuellement quand tu es prêt.",
            "notification_id": "gitpull_success"
        })
        hass.services.call("persistent_notification", "dismiss", {
            "notification_id": "gitpull_error"
        })
