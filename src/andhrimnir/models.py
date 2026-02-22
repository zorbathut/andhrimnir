from dataclasses import dataclass
from datetime import datetime, timezone


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
                "1": self.probe1,
                "2": self.probe2,
                "3": self.probe3,
                "4": self.probe4,
                "5": self.probe5,
                "6": self.probe6,
            },
        }
