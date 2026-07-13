import subprocess
from datetime import datetime

@time_trigger("cron(*/5 * * * *)")
def check_and_pull():
    result = subprocess.run(
        ["git", "-C", "/config/pyscript", "pull"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        log.error(f"Erreur git pull : {result.stderr.strip()}")
        hass.services.call("persistent_notification", "create", {
            "title": "❌ Git pull échoué",
            "message": f"{result.stderr.strip()}\n\nHeure : {datetime.now().strftime('%H:%M:%S')}",
            "notification_id": "gitpull_error"
        })
        return

    if "up to date" in result.stdout.lower():
        log.info("Aucun nouveau commit")
        # rien d'affiché, pas de notification pour ne pas spammer
    else:
        log.info(f"Nouveau commit récupéré : {result.stdout.strip()}")
        hass.services.call("pyscript", "reload", {})
        hass.services.call("persistent_notification", "create", {
            "title": "✅ Nouveau commit synchronisé",
            "message": f"{result.stdout.strip()}\n\nPyscript rechargé à {datetime.now().strftime('%H:%M:%S')}",
            "notification_id": "gitpull_success"
        })
        hass.services.call("persistent_notification", "dismiss", {
            "notification_id": "gitpull_error"
        })
