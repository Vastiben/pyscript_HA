"""
Test : notification persistante toutes les minutes via pyscript (Home Assistant).
La notification reste visible jusqu'à être manuellement effacée (tag fixe).
"""

NOTIFICATION_ID = "test_minuterie"
NOTIFICATION_TITLE = "⏱️ Test Minuterie"
NOTIFICATION_MESSAGE = "Notification persistante — mise à jour toutes les 60 secondes."


@time_trigger("period(now, 60s)")
def notification_minuterie():
    """Crée/met à jour une notification persistante dans HA toutes les 60 secondes."""
    task.unique("notification_minuterie")

    service.call(
        "notify",
        "persistent_notification",
        notification_id=NOTIFICATION_ID,
        title=NOTIFICATION_TITLE,
        message=f"{NOTIFICATION_MESSAGE}\n\nDernière mise à jour : {now.strftime('%H:%M:%S')}",
    )
    log.info(f"[test_minuterie] Notification mise à jour à {now.strftime('%H:%M:%S')}")
