"""PROPOSED display-state layer, deliberately separate from the wire contract.

`runtimeState` is preserved verbatim on every row as `qoderRuntimeState`. This
module only adds a label on top, and it is allowed to be wrong: the mapping is
provisional and no consumer may treat an unmapped value as `cold`.

Why the fallback is `UNKNOWN` and not `cold`: a cold row renders as "off-shift",
which is a claim about a worker who has gone home. An unrecognised state is not
evidence of that; silently filing it there turns a contract change into a
plausible-looking lie. `cold` is also the only observed state that a reader is
likely to skim past.
"""

from __future__ import annotations

from typing import Final

from .contract import OBSERVED_RUNTIME_STATES

#: Value emitted for any `runtimeState` this package does not recognise.
UNKNOWN_LABEL: Final = "UNKNOWN"

#: PROPOSED mapping, not approved. Values are this package's vocabulary, not
#: upstream's, and the target names are still open for review.
PROVISIONAL_STATUS_LABELS: Final[dict[str, str]] = {
    "running": "working",
    "ready": "available",
    "waiting-user": "pending_approval",
    "cold": "off_shift",
}


def status_label(qoder_runtime_state: object) -> str:
    """Map an observed `runtimeState` to a PROPOSED label.

    Unknown, non-string, empty and whitespace-padded values all resolve to
    `UNKNOWN_LABEL`; a recognised value is matched exactly, with no case
    folding, so `Running` is unknown rather than quietly coerced.
    """
    if not isinstance(qoder_runtime_state, str):
        return UNKNOWN_LABEL
    return PROVISIONAL_STATUS_LABELS.get(qoder_runtime_state, UNKNOWN_LABEL)


def is_observed_state(qoder_runtime_state: object) -> bool:
    """Whether the value is one of the four states actually seen upstream."""
    return qoder_runtime_state in OBSERVED_RUNTIME_STATES
