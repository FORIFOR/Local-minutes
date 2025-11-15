from typing import Dict, List


def _ts_to_srt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def export_srt(segs: List[Dict]) -> str:
    out = []
    for i, s in enumerate(segs, start=1):
        out.append(str(i))
        out.append(f"{_ts_to_srt(s['start'])} --> {_ts_to_srt(s['end'])}")
        spk = s.get("speaker") or "S?"
        out.append(f"{spk}: {s['text_ja']}")
        out.append("")
    return "\n".join(out)


def _ts_to_vtt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02}:{m:02}:{s:06.3f}"


def export_vtt(segs: List[Dict]) -> str:
    out = ["WEBVTT", ""]
    for s in segs:
        out.append(f"{_ts_to_vtt(s['start'])} --> {_ts_to_vtt(s['end'])}")
        spk = s.get("speaker") or "S?"
        out.append(f"{spk}: {s['text_ja']}")
        out.append("")
    return "\n".join(out)


def export_rttm(event_id: str, segs: List[Dict]) -> str:
    lines = []
    for s in segs:
        dur = s["end"] - s["start"]
        spk = s.get("speaker") or "S?"
        lines.append(f"SPEAKER {event_id} 1 {s['start']:.3f} {dur:.3f} <NA> <NA> {spk} <NA>")
    return "\n".join(lines)


def export_ics(ev: Dict) -> str:
    from datetime import datetime, timezone
    dt_start = datetime.fromtimestamp(ev["start_ts"], tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dt_end = datetime.fromtimestamp(ev["end_ts"] or (ev["start_ts"] + 3600), tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    uid = ev["id"]
    title = ev.get("title") or "Meeting"
    return "\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART:{dt_start}",
            f"DTEND:{dt_end}",
            f"SUMMARY:{title}",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )

