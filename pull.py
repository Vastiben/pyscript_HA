import subprocess

@time_trigger("cron(*/1 * * * *)")
def check_and_pull():
    result = subprocess.run(
        ["git", "-C", "/config/pyscript", "pull"],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        log.error(f"Erreur git pull : {result.stderr.strip()}")
        return
    
    if "up to date" in result.stdout.lower():
        log.info("Aucun nouveau commit")
    else:
        log.info(f"Nouveau commit récupéré : {result.stdout.strip()}")
        hass.services.call("pyscript", "reload", {})
