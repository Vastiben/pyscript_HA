# pyscript/sleep_score.py
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

def _score_duration(total_sec):
    h = total_sec / 3600
    if   7.5 <= h <= 8.5: return 25.0
    elif 7.0 <= h < 7.5:  return 20 + (h - 7.0) / 0.5 * 5
    elif 8.5 < h <= 9.0:  return 20 + (9.0 - h) / 0.5 * 5
    elif 6.0 <= h < 7.0:  return 10 + (h - 6.0) / 1.0 * 10
    elif 9.0 < h <= 10.0: return 10 + (10.0 - h) / 1.0 * 10
    elif 5.0 <= h < 6.0:  return 3  + (h - 5.0) / 1.0 * 7
    else:                  return max(0, 3 - (5.0 - h) * 3)

def _score_architecture(dur, total_sec):
    pct_p = dur["Profond"]   / total_sec * 100
    pct_r = dur["Paradoxal"] / total_sec * 100
    pct_w = dur["Réveillé"]  / total_sec * 100

    if   13 <= pct_p <= 23: s_p = 15.0
    elif 10 <= pct_p < 13:  s_p = 15 * (pct_p - 5) / 8
    elif pct_p > 23:         s_p = max(10, 15 - (pct_p - 23) * 0.5)
    elif  5 <= pct_p < 10:  s_p = 15 * (pct_p - 5) / 8
    else:                    s_p = 2.0

    if   20 <= pct_r <= 25: s_r = 15.0
    elif 15 <= pct_r < 20:  s_r = 10 + (pct_r - 15) / 5 * 5
    elif 25 < pct_r <= 30:  s_r = 15 - (pct_r - 25) / 5 * 3
    elif 10 <= pct_r < 15:  s_r = 5  + (pct_r - 10) / 5 * 5
    else:                    s_r = max(2, pct_r / 5)

    if   pct_w < 2:  s_w = 5.0
    elif pct_w < 5:  s_w = 5  - (pct_w - 2) / 3 * 2
    elif pct_w < 10: s_w = 3  - (pct_w - 5) / 5 * 2
    else:            s_w = max(0, 1 - pct_w * 0.1)

    return s_p, s_r, s_w, round(pct_p, 1), round(pct_r, 1), round(pct_w, 1)

def _score_rhr(rhr):
    if   rhr <= 45: return 20.0
    elif rhr <= 50: return 17 + (50 - rhr) / 5 * 3
    elif rhr <= 55: return 13 + (55 - rhr) / 5 * 4
    elif rhr <= 60: return  8 + (60 - rhr) / 5 * 5
    elif rhr <= 65: return  4 + (65 - rhr) / 5 * 4
    elif rhr <= 75: return  2 + (75 - rhr) / 10 * 2
    else:           return max(0, 2 - (rhr - 75) * 0.1)

def _score_onset(onset_dt):
    h = onset_dt.hour + onset_dt.minute / 60
    if h < 6: h += 24
    if   21.0 <= h <= 23.5: return 20.0
    elif 23.5 < h <= 24.5:  return 13 + (24.5 - h) / 1.0 * 7
    elif 24.5 < h <= 26.0:  return  5 + (26.0 - h) / 1.5 * 8
    elif h > 26.0:           return max(0, 5 - (h - 26) * 2)
    elif 20.0 <= h < 21.0:  return 15 + (h - 20.0) / 1.0 * 5
    elif 19.0 <= h < 20.0:  return  7 + (h - 19.0) / 1.0 * 8
    else:                    return max(0, 7 - (19.0 - h) * 3)

def _score_label(score):
    if score >= 85: return "Excellent"
    elif score >= 70: return "Bon"
    elif score >= 50: return "Moyen"
    else: return "Insuffisant"

@service
def update_sleep_score(**kwargs):
    """Calcule le score de qualité de la nuit (0–100)"""
    log.info("▶ update_sleep_score démarré")

    summary_attrs = state.getattr("sensor.sleep_last_night_summary")
    rhr_raw = state.get("sensor.rhr_data")
    log.debug(f"  summary_attrs={summary_attrs} | rhr_raw={rhr_raw}")

    if not summary_attrs or rhr_raw is None:
        log.error("❌ update_sleep_score — données manquantes (summary_attrs ou rhr)")
        return

    try:
        rhr = float(rhr_raw)
    except Exception as e:
        log.error(f"❌ update_sleep_score — impossible de lire rhr : {e}")
        return

    dur = {
        "Profond":   float(summary_attrs.get("profond_min",   0)) * 60,
        "Paradoxal": float(summary_attrs.get("paradoxal_min", 0)) * 60,
        "Lent":      float(summary_attrs.get("lent_min",      0)) * 60,
        "Réveillé":  float(summary_attrs.get("reveille_min",  0)) * 60,
    }
    total_sec = float(summary_attrs.get("total_min", 0)) * 60

    if total_sec < 60:
        log.warning(f"⚠ update_sleep_score — durée totale trop courte : {total_sec/60:.1f} min")
        return

    tz = ZoneInfo("Europe/Zurich")
    window_start = summary_attrs.get("window_start", "")
    try:
        sleep_attrs = state.getattr("sensor.sleep_data")
        starts = [s.strip() for s in sleep_attrs.get("sleep_start", "").split(",")]
        yesterday_18h = (datetime.now(tz) - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        night_starts = []
        for s in starts:
            try:
                dt = datetime.fromisoformat(s)
                if dt >= yesterday_18h:
                    night_starts.append(dt)
            except: pass
        onset_dt = min(night_starts) if night_starts else datetime.now(tz)
        log.debug(f"  onset_dt={onset_dt} | {len(night_starts)} entrées nuit")
    except Exception as e:
        log.warning(f"⚠ update_sleep_score — erreur parsing onset : {e}")
        onset_dt = datetime.now(tz)

    s_dur              = _score_duration(total_sec)
    s_p, s_r, s_w, pct_p, pct_r, pct_w = _score_architecture(dur, total_sec)
    s_rhr              = _score_rhr(rhr)
    s_onset            = _score_onset(onset_dt)
    total_score        = round(s_dur + s_p + s_r + s_w + s_rhr + s_onset, 1)

    log.info(f"  Score: {total_score}/100 | profond={pct_p}% rem={pct_r}% rhr={rhr:.0f}bpm onset={onset_dt.strftime('%H:%M')}")

    state.set(
        "sensor.sleep_score",
        value=str(int(total_score)),
        new_attributes={
            "friendly_name":        "Score qualité de nuit",
            "icon":                 "mdi:star-circle",
            "unit_of_measurement":  "/100",
            "label":                _score_label(total_score),
            "score_duree":          round(s_dur, 1),
            "score_profond":        round(s_p, 1),
            "score_rem":            round(s_r, 1),
            "score_reveils":        round(s_w, 1),
            "score_rhr":            round(s_rhr, 1),
            "score_onset":          round(s_onset, 1),
            "profond_pct":          pct_p,
            "rem_pct":              pct_r,
            "reveille_pct":         pct_w,
            "rhr_bpm":              rhr,
            "onset_time":           onset_dt.strftime("%H:%M"),
            "total_sleep_h":        round(total_sec / 3600, 2),
            "last_updated":         datetime.now(tz).isoformat(),
        }
    )
    log.info("✅ update_sleep_score terminé")
