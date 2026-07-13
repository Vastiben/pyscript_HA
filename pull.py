import urllib.request
import json
import os

REPO = "Vastiben/pyscript_HA"
BRANCH = "main"
SHA_FILE = "/config/pyscript/.last_sha"

@time_trigger("cron(*/5 * * * *)")
def check_new_commit():
    url = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})

    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    latest_sha = data["sha"]

    last_sha = ""
    if os.path.exists(SHA_FILE):
        with open(SHA_FILE) as f:
            last_sha = f.read().strip()

    if latest_sha != last_sha:
        log.info(f"Nouveau commit détecté : {latest_sha}")
        with open(SHA_FILE, "w") as f:
            f.write(latest_sha)
        sync_files()
    else:
        log.info("Aucun nouveau commit")
