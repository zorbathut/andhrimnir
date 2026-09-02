from dataclasses import dataclass
from datetime import datetime

PROBE_COUNT = 6


@dataclass(frozen=True, slots=True)
class ProbeReading:
    """A snapshot of all probe temperatures, in probe order. `None` means disconnected."""

    timestamp: datetime
    probes: tuple[float | None, ...] = (None,) * PROBE_COUNT

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "probes": {str(i): t for i, t in enumerate(self.probes, 1)},
        }
