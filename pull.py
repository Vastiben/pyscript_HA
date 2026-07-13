import subprocess

@time_trigger("cron(*/5 * * * *)")
def check_and_pull():
    result = subprocess.run(
        ["git", "-C", "/config/pyscript", "pull"],
        capture_output=True,
        text=True
    )
    if "Already up to date" in result.stdout:
        log.info("Aucun nouveau commit")
    elif result.returncode == 0:
        log.info(f"Nouveau commit récupéré : {result.stdout.strip()}")
        hass.services.call("pyscript", "reload", {})
    else:
        log.error(f"Erreur git pull : {result.stderr.strip()}")
