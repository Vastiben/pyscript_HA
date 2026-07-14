import subprocess
from datetime import datetime

@time_trigger("startup")
def dismiss_telegram_error():
    log.info("▶ dismiss_telegram_error démarré")
    service.call("persistent_notification", "dismiss",
        notification_id="telegram_error"
    )
    log.info("✅ dismiss_telegram_error terminé")

@time_trigger("cron(*/1 * * * *)")
def check_and_pull():
    log.info("▶ check_and_pull démarré")
    result = subprocess.run(
        ["git", "-C", "/config/pyscript", "pull"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        log.error(f"❌ check_and_pull — git pull échoué : {result.stderr.strip()}")
        service.call("persistent_notification", "create",
            title="❌ Git pull échoué",
            message=f"{result.stderr.strip()}\n\nHeure : {datetime.now().strftime('%H:%M:%S')}",
            notification_id="gitpull_error"
        )
        return

    if "up to date" in result.stdout.lower():
        log.info("✅ check_and_pull — aucun nouveau commit")
    else:
        log.info(f"✅ check_and_pull — nouveau commit récupéré : {result.stdout.strip()}")
        service.call("persistent_notification", "create",
            title="🔄 Nouveau commit récupéré",
            message=f"{result.stdout.strip()}\n\nHeure : {datetime.now().strftime('%H:%M:%S')}",
            notification_id="gitpull_success"
        )
        service.call("persistent_notification", "dismiss",
            notification_id="gitpull_error"
        )
