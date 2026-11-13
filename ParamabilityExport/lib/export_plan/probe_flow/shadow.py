"""The `derived` block of a probe for the report."""
from ...probe import derived


def shadow_of(probe, log, name=""):
    """The `derived` block of a probe, or `{ "error": text }` when working it out failed: shadow mode never stops an
    export. `log(text)` gets one line about it (`name` leads the line of a part)."""
    try:
        block = probe.derived_record()
    except Exception as exc:
        block = {"error": ("%s: %s" % (type(exc).__name__, exc))[:300]}
        line = "sketch reading, shadow: failed (%s)" % block["error"]
    else:
        line = derived.log_line(block) if block is not None else ""
    if log is not None and line:
        log("%s%s" % ("%s: " % name if name else "", line))
    return block
