"""
/config/pyscript/telegram_commands.py

🔹 Router Telegram générique pour Pyscript
🔹 Centralise toutes les commandes
🔹 Sécurisé (whitelist fichiers)
🔹 Extensible pour d'autres apps

Architecture:
Telegram → telegram_commands → event interne → app (ex: fusionsolar)

Auteur: Bastien + ChatGPT 😄
"""

from pathlib import Path
from datetime import datetime

# =========================
# CONFIGURATION
# =========================
CONFIG = {
    "telegram_domain": "telegram_bot",
    "telegram_service": "send_message",
    "allowed_chat_ids": [],  # sécurité (mettre ton chat_id)
    "debug": True,
}


# =========================
# DEBUG
# =========================
def dbg(msg):
    if CONFIG["debug"]:
        log.info(f"[TG] {msg}")

dbg("✅ telegram_commands.py chargé")

# =========================
# COMMANDES
# =========================
COMMANDS = {
    "/help": {"type": "help", "desc": "Afficher l'aide"},

    "/cookie": {
        "type": "write",
        "path": "/config/fusionsolar/cookie.txt",
        "desc": "Enregistrer cookie FusionSolar",
        "min": 20,
        "contains": "=",
    },

    "/roarand": {
        "type": "write",
        "path": "/config/fusionsolar/roarand.txt",
        "desc": "Enregistrer Roarand",
    },

    "/status": {"type": "event", "event": "fusionsolar_command", "action": "status"},
    "/test": {"type": "event", "event": "fusionsolar_command", "action": "test"},
    "/reset": {"type": "event", "event": "fusionsolar_command", "action": "reset"},
}

ALLOWED_PATHS = {
    "/config/fusionsolar/cookie.txt",
    "/config/fusionsolar/roarand.txt",
}

# =========================
# HELPERS
# =========================
def notify(msg, chat_id=None):
    dbg(f"Notify → {msg[:50]}")
    data = {"message": msg}
    if chat_id:
        data["target"] = chat_id
    service.call(CONFIG["telegram_domain"], CONFIG["telegram_service"], **data)


def allowed(chat_id):
    if not CONFIG["allowed_chat_ids"]:
        return True
    return int(chat_id) in CONFIG["allowed_chat_ids"]


def parse_args(args):
    if isinstance(args, list):
        return " ".join(args)
    return str(args or "").strip()


# =========================
# ACTIONS
# =========================
def handle_write(cmd, spec, text, chat_id):
    dbg(f"WRITE {cmd} len={len(text)}")

    if len(text) < spec.get("min", 0):
        notify("❌ contenu trop court", chat_id)
        return

    if spec.get("contains") and spec["contains"] not in text:
        notify("❌ contenu invalide", chat_id)
        return

    path = spec["path"]

    if path not in ALLOWED_PATHS:
        notify("❌ accès interdit", chat_id)
        return

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text.strip())

    notify("✅ enregistré", chat_id)


def handle_event(spec, text, chat_id):
    dbg(f"EVENT → {spec['event']} / {spec['action']}")
    event.fire(
        spec["event"],
        action=spec["action"],
        chat_id=chat_id,
        text=text,
        ts=datetime.now().isoformat(),
    )


def help_text():
    return "\n".join(
        ["🤖 Commandes disponibles:\n"]
        + [f"{k} → {v.get('desc','')}" for k, v in COMMANDS.items()]
    )


# =========================
# ROUTER PRINCIPAL
# =========================
@event_trigger("telegram_command")
def telegram_router(**kwargs):

    dbg(f"RAW EVENT: {kwargs}")

    chat_id = kwargs.get("chat_id")
    command = kwargs.get("command")
    text = parse_args(kwargs.get("args"))

    if not command:
        return

    if not allowed(chat_id):
        dbg("⛔ chat refusé")
        return

    spec = COMMANDS.get(command)

    if not spec:
        notify("❌ commande inconnue\n\n" + help_text(), chat_id)
        return

    dbg(f"CMD → {command}")

    try:
        if spec["type"] == "help":
            notify(help_text(), chat_id)

        elif spec["type"] == "write":
            handle_write(command, spec, text, chat_id)

        elif spec["type"] == "event":
            handle_event(spec, text, chat_id)

    except Exception as e:
        log.error(f"[TG ERROR] {e}")
        notify(f"❌ erreur: {e}", chat_id)
