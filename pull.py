import subprocess
from datetime import datetime

@time_trigger("startup")
def dismiss_telegram_error():
    """Efface la notification d'erreur Telegram au démarrage de pyscript."""
    service.call("persistent_notification", "dismiss",
        notification_id="telegram_error"
    )

@time_trigger("cron(*/1 * * * *)")
def check_and_pull():
    result = subprocess.run(
        ["git", "-C", "/config/pyscript", "pull"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        log.error(f"Erreur git pull : {result.stderr.strip()}")
        service.call("persistent_notification", "create",
            title="❌ Git pull échoué",
            message=f"{result.stderr.strip()}\n\nHeure : {datetime.now().strftime('%H:%M:%S')}",
            notification_id="gitpull_error"
        )
        return

    if "up to date" in result.stdout.lower():
        log.info("Aucun nouveau commit")
    else:
        log.info(f"Nouveau commit récupéré : {result.stdout.strip()}")
        service.call("persistent_notification", "create",
            title="🔄 Nouveau commit récupéré",
            message=f"{result.stdout.strip()}\n\nHeure : {datetime.now().strftime('%H:%M:%S')}",
            notification_id="gitpull_success"
        )
        service.call("persistent_notification", "dismiss",
            notification_id="gitpull_error"
        )
