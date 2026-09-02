import math
from dataclasses import dataclass
from datetime import datetime


def _sanitize(value: float | None) -> float | str | None:
    if value is not None and math.isnan(value):
        return "NaN"
    return value


@dataclass(frozen=True, slots=True)
class ProbeReading:
    """A snapshot of all probe temperatures."""

    timestamp: datetime
    probe1: float | None = None
    probe2: float | None = None
    probe3: float | None = None
    probe4: float | None = None
    probe5: float | None = None
    probe6: float | None = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "probes": {
                "1": _sanitize(self.probe1),
                "2": _sanitize(self.probe2),
                "3": _sanitize(self.probe3),
                "4": _sanitize(self.probe4),
                "5": _sanitize(self.probe5),
                "6": _sanitize(self.probe6),
            },
        }
