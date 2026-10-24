"""Trading sessions, on each city's own clock (so daylight saving is handled).

  Asian (Tokyo)   09:00-18:00 Tokyo       (00:00-09:00 UTC, Japan has no DST)
  London          08:00-17:00 London      (07:00-16:00 UTC in summer, 08:00-17:00 in winter)
  New York        08:00-17:00 New York    (12:00-21:00 UTC in summer, 13:00-22:00 in winter)
  Overlap         London and New York both open (the most liquid hours)
"""

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

SESSIONS = {
    "asia": (ZoneInfo("Asia/Tokyo"), 9, 18),
    "london": (ZoneInfo("Europe/London"), 8, 17),
    "newyork": (ZoneInfo("America/New_York"), 8, 17),
}


def session_flags(times) -> pd.DataFrame:
    """One 0/1 column per session plus the London/New York overlap. Index follows `times`."""
    idx = pd.DatetimeIndex(pd.to_datetime(times, utc=True))
    out = {}
    for name, (tz, start, end) in SESSIONS.items():
        local = idx.tz_convert(tz)
        weekday = local.dayofweek < 5
        out[f"session_{name}"] = ((local.hour >= start) & (local.hour < end) & weekday).astype(np.int8)
    out["session_overlap"] = (out["session_london"] & out["session_newyork"]).astype(np.int8)
    return pd.DataFrame(out, index=getattr(times, "index", None))


def current_session_name(ts) -> str:
    flags = session_flags(pd.Series([pd.Timestamp(ts)])).iloc[0]
    if flags["session_overlap"]:
        return "London / New York overlap"
    names = [label for key, label in (("session_asia", "Asian"), ("session_london", "London"),
                                      ("session_newyork", "New York")) if flags[key]]
    return " / ".join(names) if names else "Off-hours"
