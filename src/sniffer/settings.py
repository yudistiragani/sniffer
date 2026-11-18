from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$"


def safe_name(value: str) -> str:
    if not re.fullmatch(NAME_PATTERN, value):
        raise ValueError("Name must be 1-96 letters/digits/underscores/dots/hyphens.")
    return value


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Device(Model):
    adb_serial: str = Field(min_length=1, pattern=r"^[^\s]+$")
    container: str | None = None
    appium_url: str = "http://127.0.0.1:4723"
    system_port: int = Field(default=8201, ge=1024, le=65535)
    proxy_host: str = "127.0.0.1"
    proxy_port: int = Field(default=8081, ge=1024, le=65535)
    frida_endpoint: str | None = None
    frida_device_id: str | None = None


class Beanstalk(Model):
    host: str = "127.0.0.1"
    port: int = Field(default=11300, ge=1, le=65535)
    instagram_tube: str = "sniffer.instagram"
    reserve_timeout: int = Field(default=5, ge=1)
    touch_interval: int = Field(default=20, ge=1)
    retry_delay: int = Field(default=30, ge=0)
    max_reserves: int = Field(default=3, ge=1)


class Redroid(Model):
    image: str | None = None
    data_dir: Path = Path("data/redroid")
    boot_args: list[str] = Field(default_factory=list)


class Platform(Model):
    package: str
    domains: list[str]
    frida_scripts: list[str] = Field(default_factory=list)
    selectors: dict[str, list[tuple[str, str]]] = Field(default_factory=dict)


class STF(Model):
    compose_project: str = "stf"


class Settings(Model):
    state_dir: Path = Path(".state")
    output_dir: Path = Path("output")
    mitm_confdir: Path = Path(".state/mitmproxy")
    devices: dict[str, Device] = Field(default_factory=dict)
    platforms: dict[str, Platform] = Field(default_factory=dict)
    beanstalk: Beanstalk = Field(default_factory=Beanstalk)
    redroid: Redroid = Field(default_factory=Redroid)
    stf: STF = Field(default_factory=STF)

    @model_validator(mode="after")
    def unique_devices(self):
        for name in self.devices:
            safe_name(name)
        for attribute in ("adb_serial", "system_port", "proxy_port"):
            values = [getattr(d, attribute) for d in self.devices.values()]
            if len(set(values)) != len(values):
                raise ValueError(f"Device {attribute} values must be unique on this executor host.")
        return self


def load_settings(path: Path | None = None) -> Settings:
    if path is None:
        path = Path(os.getenv("SNIFFER_CONFIG", "config/local.yaml"))
        if not path.exists() and "SNIFFER_CONFIG" not in os.environ:
            path = Path("config/example.yaml")
    if not path.is_file():
        raise ValueError(f"Configuration not found: {path}. Run from the repo root or use --config.")
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    queue = data.setdefault("beanstalk", {})
    for env, key in (("SNIFFER_BEANSTALK_HOST", "host"), ("SNIFFER_BEANSTALK_PORT", "port")):
        if env in os.environ:
            queue[key] = os.environ[env]
    return Settings.model_validate(data)
