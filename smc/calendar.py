"""Conservative session validation without an additional data-provider request.

Unknown weekday gaps are invalid, never inferred to be exchange holidays.
Users may explicitly supply known closure dates; existing monitor state is untouched.
"""
from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class TradingCalendar:
    years: frozenset
    closed: frozenset
    observed: tuple = ()

    def sessions(self, start, end):
        start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
        if any(year not in self.years for year in range(start.year, end.year+1)):
            raise ValueError("Calendar coverage unavailable; cannot confirm candles")
        weekdays = pd.bdate_range(start,end)
        if self.observed:
            known = set(self.observed)
            first,last = self.observed[0],self.observed[-1]
            weekdays = [day for day in weekdays if day < first or day > last or day in known]
        return pd.DatetimeIndex([day for day in weekdays if day not in self.closed])


def parse_year(payload, year):
    if str(payload.get("stat", "")).lower() != "ok" or not payload.get("data"):
        raise ValueError("TWSE calendar unavailable")
    if int(payload.get("queryYear", 0)) != year:
        raise ValueError("TWSE calendar year mismatch")
    closed = set()
    for row in payload["data"]:
        day = pd.Timestamp(row[0]).normalize()
        if day.year != year:
            raise ValueError("Unexpected calendar date")
        # Informational first/last trading sessions are open, not holidays.
        if "開始交易" not in row[1] and "最後交易" not in row[1]:
            closed.add(day)
    return closed


def conservative_calendar(start_year, end_year, extra_closed=()):
    closed = {pd.Timestamp(day).normalize() for day in extra_closed}
    return TradingCalendar(frozenset(range(start_year-1, end_year+2)), frozenset(closed))


def yahoo_session_calendar(histories, asof, extra_closed=()):
    """Align stocks to sessions observed in the downloaded Yahoo universe.

    A missing bar for one stock remains missing when another stock traded.
    Beyond observed coverage, weekdays remain expected so stale data is not
    relabeled current. A market-wide provider outage cannot be distinguished
    from a closure using Yahoo alone; expose this provenance to the user.
    """
    from .data import completed_cutoff
    cutoff = completed_cutoff(asof)
    dates = set()
    for frame in histories.values():
        if frame.empty or not isinstance(frame.index,pd.DatetimeIndex) or not {'Close','Volume'}.issubset(frame.columns):
            continue
        index = frame.index
        if index.tz is not None:
            index = index.tz_convert('Asia/Taipei').tz_localize(None)
        valid = pd.to_numeric(frame.Close,errors='coerce').gt(0) & pd.to_numeric(frame.Volume,errors='coerce').gt(0)
        dates.update(day.normalize() for day in index[valid] if day.normalize() <= cutoff)
    if not dates:
        raise ValueError('No completed Yahoo sessions available')
    ordered = tuple(sorted(dates))
    return TradingCalendar(frozenset(range(ordered[0].year-1,cutoff.year+2)),
                           frozenset(pd.Timestamp(d).normalize() for d in extra_closed),ordered)
