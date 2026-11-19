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
    frida_server_path: str | None = Field(default=None, pattern=r"^/[A-Za-z0-9._/-]+$")
    frida_device_id: str | None = None


class Beanstalk(Model):
    host: str = "127.0.0.1"
    port: int = Field(default=11300, ge=1, le=65535)
    instagram_tube: str = "sniffer.instagram"
    reserve_timeout: int = Field(default=5, ge=1)
    touch_interval: int = Field(default=20, ge=1)
    retry_delay: int = Field(default=30, ge=0)
    max_reserves: int = Field(default=3, ge=1)


class ResultsQueue(Model):
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=11300, ge=1, le=65535)
    tube: str = Field(default="sniffer_instagram_result", pattern=NAME_PATTERN)
    timeout: int = Field(default=5, ge=1, le=15)
    max_message_bytes: int = Field(default=65535, ge=1024, le=1024 * 1024)


class RemoteMitmweb(Model):
    # Web UI/API origin, NOT the Android HTTP proxy listener.
    url: str | None = None
    client_ip: str | None = None
    poll_interval: float = Field(default=1, ge=0.5, le=5)
    timeout: int = Field(default=3, ge=1, le=10)
    settle_seconds: int = Field(default=5, ge=1, le=15)


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
    results: ResultsQueue = Field(default_factory=ResultsQueue)
    remote_mitmweb: RemoteMitmweb = Field(default_factory=RemoteMitmweb)
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
    results = data.setdefault("results", {})
    for env, key in (
        ("SNIFFER_RESULTS_HOST", "host"), ("SNIFFER_RESULTS_PORT", "port"),
        ("SNIFFER_RESULTS_TUBE", "tube"),
    ):
        if env in os.environ:
            results[key] = os.environ[env]
    remote = data.setdefault("remote_mitmweb", {})
    for env, key in (
        ("SNIFFER_MITMWEB_URL", "url"), ("SNIFFER_MITMWEB_CLIENT_IP", "client_ip"),
    ):
        if env in os.environ:
            remote[key] = os.environ[env]
    return Settings.model_validate(data)
