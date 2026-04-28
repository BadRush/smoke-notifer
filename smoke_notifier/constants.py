"""
Status constants and emoji mappings for link health evaluation.
"""

# ── Status Levels ─────────────────────────────────────────────────
STATUS_OK       = "OK"
STATUS_WARN     = "WARN"
STATUS_CRIT     = "CRIT"
STATUS_DOWN     = "DOWN"
STATUS_FLAPPING = "FLAPPING"
STATUS_UNKNOWN  = "UNKNOWN"
STATUS_UNREACHABLE = "UNREACHABLE"

# ── Status Emoji Map ─────────────────────────────────────────────
STATUS_EMOJI = {
    STATUS_OK:       "🟢",
    STATUS_WARN:     "🟡",
    STATUS_CRIT:     "🟠",
    STATUS_DOWN:     "🔴",
    STATUS_FLAPPING: "⚠️",
    STATUS_UNKNOWN:  "⚪",
    STATUS_UNREACHABLE: "🔕",
}
