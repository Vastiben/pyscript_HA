"""
🔹 Telegram Command Router (générique)
🔹 Centralise toutes les commandes
🔹 Envoie des events vers les apps (FusionSolar, etc.)

Architecture:
Telegram → telegram_commands → event → app

Logs: [TG]
"""

from pathlib import Path
from datetime import datetime

CONFIG = {
    "allowed_chat_ids": [],  # optionnel sécurité
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
    "/tghelp": {"type": "help"},

    "/fshealth": {
        "type": "event",
        "action": "health",
    },
    
    "/fscookie": {
        "type": "write",
        "path": "/config/fusionsolar/cookie.txt",
        "min": 20,
    },

    "/fsroarand": {
        "type": "write",
        "path": "/config/fusionsolar/roarand.txt",
    },

    "/fsstatus": {"type": "event", "action": "status"},
    "/fstest": {"type": "event", "action": "test"},
    "/fsreset": {"type": "event", "action": "reset"},

    # === GitHub / Pyscript ===
    "/gh-pull": {
        "type": "event",
        "event": "pyscript_gh",
        "action": "pull",
    },
    "/gh-push": {
        "type": "event",
        "event": "pyscript_gh",
        "action": "push",
    },
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

    # Pyscript: service.call(domain, name, **data)
    service.call("telegram_bot", "send_message", **data)


def parse_args(args):
    if isinstance(args, list):
        # Pas de generator expression (non supporté par Pyscript) : on force une list comprehension
        return " ".join([str(x) for x in args])
    return str(args or "").strip()


# =========================
# ROUTER
# =========================
@event_trigger("telegram_command")
def router(**kwargs):

    dbg(f"RAW: {kwargs}")

    cmd = (kwargs.get("command") or "").lower().replace("_", "")
    text = parse_args(kwargs.get("args"))
    chat = kwargs.get("chat_id")

    dbg(f"CMD={cmd} TEXT_LEN={len(text)}")

    spec = COMMANDS.get(cmd)

    if not spec:
        notify("❌ commande inconnue", chat)
        return

    # =====================
    # HELP
    # =====================
    if spec["type"] == "help":
        notify(
            "🤖 Commandes:\n"
            "/fscookie\n"
            "/fsstatus\n"
            "/fstest\n"
            "/fshealth\n"
            "/fsreset\n"
            "/gh-pull\n"
            "/gh-push",
            chat,
        )

    # =====================
    # WRITE FILE
    # =====================
    elif spec["type"] == "write":

        if len(text) < spec.get("min", 0):
            notify("❌ contenu trop court", chat)
            return

        path = spec["path"]

        if path not in ALLOWED_PATHS:
            notify("❌ accès interdit", chat)
            return

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text.strip())

        dbg(f"Fichier écrit: {path}")

        notify("✅ enregistré", chat)

    # =====================
    # EVENT
    # =====================
    elif spec["type"] == "event":

        event_name = spec.get("event", "fusionsolar_command")
        dbg(f"Fire event → {event_name}:{spec['action']}")

        event.fire(
            event_name,
            action=spec["action"],
            chat_id=chat,
            text=text,
            ts=datetime.now().isoformat(),
        )
