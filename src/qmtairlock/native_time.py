"""QMT native source date and time conversion; missing stays zero."""

import time


def date_time_seconds(raw_date, raw_time):
    """Combine a QMT date + time pair into Unix seconds; 0 when unavailable."""
    if isinstance(raw_time, (int, float)) and (not isinstance(raw_time, bool)):
        value = float(raw_time)
        if value > 100000000000.0:
            value /= 1000.0
        if value > 100000000.0:
            return int(value)
    date_digits = "".join((ch for ch in str(raw_date or "") if ch.isdigit()))
    time_digits = "".join((ch for ch in str(raw_time or "") if ch.isdigit()))
    if len(time_digits) >= 14:
        date_digits, time_digits = (time_digits[:8], time_digits[8:14])
    if not date_digits or len(date_digits) < 8:
        return 0
    if len(time_digits) == 5:
        time_digits = "0" + time_digits
    time_digits = (time_digits + "000000")[:6]
    try:
        parsed = time.strptime(date_digits[:8] + time_digits, "%Y%m%d%H%M%S")
        return int(time.mktime(parsed))
    except ValueError:
        return 0
