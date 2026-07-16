from datetime import datetime
import base64
import requests

# --- CONFIG À ADAPTER ---

GITHUB_OWNER = "Vastiben"            # ton user ou org GitHub
GITHUB_REPO  = "pyscript_HA"         # nom du repo
GITHUB_PATH  = "logs/ha_warnings_errors.log"  # chemin du fichier dans le repo

# Token GitHub avec droits 'repo' ou au moins 'contents:write'.
# À définir côté Home Assistant, par ex. via pyscript.config["github_token"].
GITHUB_TOKEN = pyscript.config.get("github_token", "")

# Fichier log de Home Assistant (core).
LOG_FILE = "/config/home-assistant.log"  # emplacement standard sur HA OS


def _filter_warning_error():
    """Retourne uniquement les lignes WARNING/ERROR du log HA."""
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        log.error(f"GitHub logs: impossible de lire {LOG_FILE}: {e}")
        return ""

    filtered = [l for l in lines if "WARNING" in l or "ERROR" in l]
    header = f"Snapshot {datetime.now().isoformat()} — WARNING/ERROR uniquement\n\n"
    return header + "".join(filtered)


def _get_remote_sha():
    """Récupère la SHA du fichier distant s'il existe, sinon None."""
    if not GITHUB_TOKEN:
        log.error("GitHub logs: GITHUB_TOKEN manquant (pyscript.config['github_token'])")
        return None

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 404:
        return None
    try:
        r.raise_for_status()
    except Exception as e:
        log.error(f"GitHub logs: GET contents a échoué ({r.status_code}): {e} — {r.text}")
        return None
    data = r.json()
    return data.get("sha")


def _push_to_github(text: str):
    """Crée / met à jour le fichier sur GitHub via l'API contents."""
    if not GITHUB_TOKEN:
        log.error("GitHub logs: GITHUB_TOKEN manquant (pyscript.config['github_token'])")
        return

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}

    content_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    sha = _get_remote_sha()

    payload = {
        "message": f"HA logs WARNING/ERROR {datetime.now().isoformat()}",
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha  # requis pour update d'un fichier existant

    r = requests.put(url, json=payload, headers=headers)
    try:
        r.raise_for_status()
        commit_url = r.json().get("commit", {}).get("html_url")
        log.info(f"GitHub logs: push OK → {commit_url}")
    except Exception as e:
        log.error(f"GitHub logs: push FAIL ({r.status_code}): {e} — {r.text}")


@time_trigger("period(now, 1min)")
def push_ha_warning_error_logs():
    """Tâche planifiée: toutes les minutes, push WARNING/ERROR vers GitHub."""
    text = _filter_warning_error()
    if not text.strip():
        log.debug("GitHub logs: aucun WARNING/ERROR, pas de push.")
        return

    # Exécution blocante dans un thread → pas de blocage du loop pyscript
    task.executor(_push_to_github, text)
