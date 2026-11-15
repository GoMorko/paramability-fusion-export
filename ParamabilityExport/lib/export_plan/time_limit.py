"""The time limit of the size tries: the choices the dialog offers, the default and the words for a duration. Pure:
no Fusion imports.

The tries rebuild the design once per try, so a large design can spend most of the export there. The limit is a
number of minutes, or None for no limit. When it is reached the tries stop at the next try (`pipeline.ProbeRun`).
"""

# What an export gets when the designer does not change it. Small designs finish their tries in seconds; the slowest
# design measured took about a minute per try, so ten minutes still gives it about ten tries.
DEFAULT_MINUTES = 10
DEFAULT_SECONDS = DEFAULT_MINUTES * 60

# The minutes the dialog offers, shortest first; None is "no limit".
CHOICES = (1, 5, 10, 20, 30, 60, 120, None)

NO_LIMIT = "No limit"


def choice_text(minutes):
    """The dialog's text of a choice: "10 minutes", "1 hour" or "No limit"."""
    if minutes is None:
        return NO_LIMIT
    if minutes >= 60 and minutes % 60 == 0:
        hours = minutes // 60
        return "%d %s" % (hours, "hour" if hours == 1 else "hours")
    return "%d %s" % (minutes, "minute" if minutes == 1 else "minutes")


def minutes_of(text):
    """The choice a dialog text stands for, `DEFAULT_MINUTES` when it is none of them. None means no limit."""
    for minutes in CHOICES:
        if choice_text(minutes) == text:
            return minutes
    return DEFAULT_MINUTES


def seconds_of(minutes):
    """Seconds of a choice in minutes, None for no limit."""
    return None if minutes is None else minutes * 60.0


def duration_text(seconds):
    """A time for a person: "45 s", "2 min 10 s", "1 h 5 min". Rounded to the second, or to the minute from an hour."""
    total = max(0, int(round(seconds)))
    if total < 60:
        return "%d s" % total
    if total < 3600:
        minutes, rest = divmod(total, 60)
        return "%d min %d s" % (minutes, rest) if rest else "%d min" % minutes
    hours, rest = divmod(total, 3600)
    minutes = int(round(rest / 60.0))
    if minutes == 60:
        hours, minutes = hours + 1, 0
    return "%d h %d min" % (hours, minutes) if minutes else "%d h" % hours


def limit_text(seconds):
    """A limit in seconds for a person ("10 min"), or "no limit"."""
    return "no limit" if seconds is None else duration_text(seconds)
