import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

SOURCE_KINDS = ("ble", "esp")


class ConfigError(Exception):
    """A setting was supplied but could not be used."""


@dataclass
class Settings:
    ble_address: str = ""
    ble_char_uuid: str = "0000ffb2-0000-1000-8000-00805f9b34fb"
    ble_reconnect_delay: float = 5.0
    esp_host: str = ""
    esp_port: int = 6053
    esp_password: str = ""
    esp_noise_psk: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    db_path: str = "andhrimnir.db"
    source: str = ""

    @property
    def source_kind(self) -> str:
        """Which backend to read probes through; defaults to the proxy when one is configured."""
        if self.source:
            return self.source
        return "esp" if self.esp_host else "ble"

    @classmethod
    def load(cls, config_path: Path) -> "Settings":
        kwargs: dict = {}

        if config_path.exists():
            with open(config_path, "rb") as f:
                toml = tomllib.load(f)
            for field in _FIELDS:
                section = toml.get(field.section, {})
                if field.key in section:
                    kwargs[field.name] = section[field.key]
            _toml_unknown_report(toml, config_path)

        # Env vars override the config file.  An empty value reads as unset, so a setting can be overridden here but never cleared.
        for field in _FIELDS:
            value = os.environ.get(field.env)
            if not value:
                continue
            try:
                kwargs[field.name] = field.parse(value)
            except ValueError as exc:
                raise ConfigError(f"{field.env}: {exc}") from exc

        # Resolve before construction so Settings.load and Settings(...) agree on the field.
        kwargs["db_path"] = str(Path(kwargs.get("db_path", cls.db_path)).resolve())

        settings = cls(**kwargs)
        if settings.source and settings.source not in SOURCE_KINDS:
            raise ConfigError(f"source: expected one of {', '.join(SOURCE_KINDS)}, got {settings.source!r}")
        return settings


def _toml_unknown_report(toml: dict, config_path: Path) -> None:
    """Warn about settings that will be ignored, so a stale or misspelled key is not silently dropped."""
    known: dict[str, set[str]] = {}
    for field in _FIELDS:
        known.setdefault(field.section, set()).add(field.key)
    for section, entries in toml.items():
        if not isinstance(entries, dict):
            logger.warning("%s: ignoring top-level key %r; settings must live under a section", config_path, section)
            continue
        for key in entries.keys() - known.get(section, set()):
            logger.warning("%s: ignoring unknown setting [%s] %s", config_path, section, key)


@dataclass(frozen=True, slots=True)
class _Field:
    """One Settings field and where it can be read from: `[section] key` in TOML, or an env var."""

    name: str
    section: str
    key: str
    parse: Callable[[str], object] = str

    @property
    def env(self) -> str:
        return f"ANDHRIMNIR_{self.name.upper()}"


_FIELDS = (
    _Field("ble_address", "ble", "address"),
    _Field("ble_char_uuid", "ble", "char_uuid"),
    _Field("ble_reconnect_delay", "ble", "reconnect_delay", float),
    _Field("esp_host", "esp", "host"),
    _Field("esp_port", "esp", "port", int),
    _Field("esp_password", "esp", "password"),
    _Field("esp_noise_psk", "esp", "noise_psk"),
    _Field("host", "server", "host"),
    _Field("port", "server", "port", int),
    _Field("db_path", "server", "db_path"),
    _Field("source", "server", "source"),
)
