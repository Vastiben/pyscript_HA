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
    "/help": {"type": "help"},

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
    "/fstest":   {"type": "event", "action": "test"},
    "/fsreset":  {"type": "event", "action": "reset"},

    # === GitHub / Pyscript ===
    "/ghpull": {
        "type": "event",
        "event": "pyscript_gh",
        "action": "pull",
    },
    "/ghpush": {
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
    service.call("telegram_bot", "send_message", **data)


def parse_args(args):
    if isinstance(args, list):
        return " ".join([str(x) for x in args])
    return str(args or "").strip()


# =========================
# ROUTER
# =========================
@event_trigger("telegram_command")
def router(**kwargs):

    dbg(f"RAW: {kwargs}")

    cmd = (kwargs.get("command") or "").lower().replace("_", "").replace("-", "")
    text = parse_args(kwargs.get("args"))
    chat = kwargs.get("chat_id")

    dbg(f"CMD={cmd} TEXT_LEN={len(text)}")

    spec = COMMANDS.get(cmd)

    if not spec:
        notify("❌ Commande inconnue. Tape /help pour la liste.", chat)
        return

    # =====================
    # HELP
    # =====================
    if spec["type"] == "help":
        notify(
            "🤖 Commandes disponibles :\n\n"
            "📊 FusionSolar\n"
            "/fscookie — mettre à jour le cookie\n"
            "/fsroarand — mettre à jour le roarand\n"
            "/fsstatus — statut\n"
            "/fshealth — diagnostic complet\n"
            "/fstest — test\n"
            "/fsreset — reset\n\n"
            "🔧 GitHub / Pyscript\n"
            "/ghpull — récupérer le dernier code GitHub\n"
            "/ghpush — pousser les logs HA vers GitHub",
            chat,
        )

    # =====================
    # WRITE FILE
    # =====================
    elif spec["type"] == "write":

        if len(text) < spec.get("min", 0):
            notify("❌ Contenu trop court.", chat)
            return

        path = spec["path"]

        if path not in ALLOWED_PATHS:
            notify("❌ Accès interdit.", chat)
            return

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text.strip())

        dbg(f"Fichier écrit: {path}")
        notify("✅ Enregistré.", chat)

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
