from __future__ import annotations

import importlib.util
import json
import logging
import re
import shutil
import signal
import subprocess
import uuid
from functools import wraps
from pathlib import Path
from typing import Annotated

import typer
from filelock import Timeout

from sniffer.device import ADB, register, registry, resolve
from sniffer.device import configure as configure_device
from sniffer.executor import execute
from sniffer.jobs import SearchJob
from sniffer.runtime import atomic_json, lock, reachable, require_free_port
from sniffer.settings import Device, Settings, load_settings, safe_name

app = typer.Typer(no_args_is_help=True, help="Device-scoped capture and Instagram search executor.")
devices = typer.Typer(no_args_is_help=True, help="Adopt existing or manage newly created devices.")
stf = typer.Typer(no_args_is_help=True, help="Operate existing STF containers only.")
appium = typer.Typer(no_args_is_help=True)
mitm = typer.Typer(no_args_is_help=True)
frida_cli = typer.Typer(no_args_is_help=True, help="Explicit Frida metadata diagnostics, no TLS bypass.")
automation = typer.Typer(no_args_is_help=True)
instagram = typer.Typer(no_args_is_help=True)
parse_cli = typer.Typer(no_args_is_help=True, help="Offline parsing; no network or device access.")
results_cli = typer.Typer(no_args_is_help=True, help="Publish/resume only a saved result outbox.")
app.add_typer(devices, name="device")
app.add_typer(stf, name="stf")
app.add_typer(appium, name="appium")
app.add_typer(mitm, name="mitmproxy")
app.add_typer(frida_cli, name="frida")
app.add_typer(automation, name="automation")
app.add_typer(parse_cli, name="parse")
app.add_typer(results_cli, name="results")
automation.add_typer(instagram, name="instagram")
DeviceOption = Annotated[str, typer.Option("--device", "-d", help="Configured device name.")]


def guarded(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Timeout:
            typer.secho("Resource busy: another operation owns this device/service.", fg="red", err=True)
            raise typer.Exit(1) from None
        except (typer.Exit, typer.Abort):
            raise
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
            typer.secho(f"{type(error).__name__}: {error}", fg="red", err=True)
            raise typer.Exit(1) from None
        except Exception as error:
            typer.secho(
                f"Integration failed ({type(error).__name__}); inspect the session and service logs.",
                fg="red", err=True,
            )
            raise typer.Exit(1) from None
    return wrapper


def emit(value):
    typer.echo(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def on_terminate(*_):
    raise KeyboardInterrupt


@parse_cli.command("instagram-search")
@guarded
def parse_instagram_search(
    request: Annotated[Path, typer.Option(help="JSON metadata with method/url/content_type/body.")],
    response: Annotated[Path, typer.Option(help="Decoded response body, JSON or JSON sequence.")],
    keyword: Annotated[str, typer.Option(help="Expected exact search keyword.")],
    output: Annotated[Path, typer.Option(help="New, nonexistent output directory.")],
):
    """Normalize an exported TopSerpQuery response; does not attach to remote mitmweb."""
    from sniffer.capture.offline import parse_instagram_search as parse_export
    emit(parse_export(request, response, keyword, output))


@app.callback()
@guarded
def configure(
    ctx: typer.Context,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
):
    """Paths in YAML are relative to the working directory; run from the repository root."""
    ctx.obj = load_settings(config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, on_terminate)


@devices.command("list")
@guarded
def device_list(ctx: typer.Context):
    settings: Settings = ctx.obj
    result = {
        name: {"device": d.model_dump(), "ownership": "adopted"}
        for name, d in settings.devices.items()
    }
    result.update(registry(settings))
    emit(result)


@devices.command("adopt")
@guarded
def adopt(
    ctx: typer.Context,
    name: str,
    adb: Annotated[str, typer.Option("--adb")],
    system_port: Annotated[int, typer.Option(min=1024, max=65535)],
    proxy_port: Annotated[int, typer.Option(min=1024, max=65535)],
    container: str | None = None,
):
    """Register metadata only; no connect/restart/provision. Use doctor to verify."""
    device = Device(
        adb_serial=adb, container=container, system_port=system_port, proxy_port=proxy_port
    )
    register(ctx.obj, name, device, ownership="adopted")
    emit({"registered": name, "runtime_changed": False})


@devices.command("forget")
@guarded
def forget(ctx: typer.Context, name: str):
    """Forget a local adopted registration only; never delete runtime or managed tracking."""
    settings: Settings = ctx.obj
    safe_name(name)
    with lock(settings, f"device-{name}"), lock(settings, "inventory"):
        entries = registry(settings)
        if name in settings.devices:
            raise ValueError("This adopted device is defined in YAML; edit your local config instead.")
        if name not in entries or entries[name].get("ownership") != "adopted":
            raise ValueError("Only local adopted registrations can be forgotten.")
        entries.pop(name)
        atomic_json(settings.state_dir / "devices.json", entries)
    emit({"forgotten": name, "runtime_changed": False})


@devices.command("configure")
@guarded
def device_configure(
    ctx: typer.Context,
    name: str,
    appium_url: str | None = None,
    system_port: Annotated[int | None, typer.Option(min=1024, max=65535)] = None,
    proxy_host: str | None = None,
    proxy_port: Annotated[int | None, typer.Option(min=1024, max=65535)] = None,
    frida_endpoint: str | None = None,
    frida_device_id: str | None = None,
    clear_frida: bool = False,
):
    """Update locally registered device connections; preserve container identity/ownership."""
    if clear_frida and (frida_endpoint or frida_device_id):
        raise ValueError("--clear-frida cannot be combined with a Frida target.")
    changes = {
        key: value for key, value in {
            "appium_url": appium_url, "system_port": system_port,
            "proxy_host": proxy_host, "proxy_port": proxy_port,
            "frida_endpoint": frida_endpoint, "frida_device_id": frida_device_id,
        }.items() if value is not None
    }
    if clear_frida:
        changes.update(frida_endpoint=None, frida_device_id=None)
    emit({
        "device": configure_device(ctx.obj, name, changes).model_dump(),
        "runtime_changed": False,
    })


@devices.command("create")
@guarded
def create_devices(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument()] = None,
    image: str | None = None,
    prefix: str | None = None,
    count: Annotated[int, typer.Option(min=1, max=20)] = 1,
    adb_port: Annotated[int, typer.Option(min=1024, max=65535)] = 5557,
    system_port: Annotated[int, typer.Option(min=1024, max=65535)] = 8203,
    proxy_port: Annotated[int, typer.Option(min=1024, max=65535)] = 8083,
):
    """Create stopped devices. Image must already exist locally; no implicit pull or start."""
    from sniffer.integrations.redroid import create
    settings: Settings = ctx.obj
    if bool(name) == bool(prefix) or (name and count != 1):
        raise ValueError("Choose NAME for one device, or --prefix NAME --count N.")
    selected_image = image or settings.redroid.image
    if not selected_image:
        raise ValueError("Supply --image or redroid.image with an audited local Magisk image.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@+-]*", selected_image):
        raise ValueError("Invalid image reference.")
    for index in range(count):
        selected_name = name or f"{prefix}{index + 1:02d}"
        # Batch is deliberately not transactional: preserve any already-created data on failure.
        emit(create(
            settings, selected_name, selected_image,
            adb_port + index, system_port + index, proxy_port + index,
        ))


@devices.command("start")
@guarded
def start_device(ctx: typer.Context, name: str):
    from sniffer.integrations.redroid import lifecycle
    lifecycle(ctx.obj, name, "start")
    emit({"started": name, "provisioned": False})


@devices.command("stop")
@guarded
def stop_device(ctx: typer.Context, name: str):
    from sniffer.integrations.redroid import lifecycle
    lifecycle(ctx.obj, name, "stop")
    emit({"stopped": name, "data_preserved": True})


@devices.command("destroy")
@guarded
def destroy_device(
    ctx: typer.Context, name: str,
    yes: Annotated[bool, typer.Option("--yes", help="Confirm container removal; data stays.")] = False,
):
    from sniffer.integrations.redroid import lifecycle
    if not yes and not typer.confirm(f"Remove stopped managed container {name}? Keep all data."):
        raise typer.Abort()
    lifecycle(ctx.obj, name, "destroy")
    emit({"destroyed": name, "data_preserved": True})


@stf.command("status")
@guarded
def stf_status(ctx: typer.Context):
    from sniffer.integrations.redroid import stf_containers
    emit(stf_containers(ctx.obj))


@stf.command("start")
@guarded
def stf_start(
    ctx: typer.Context,
    yes: Annotated[bool, typer.Option("--yes")] = False,
):
    from sniffer.integrations.redroid import start_stf
    if not yes and not typer.confirm("Start existing stopped STF containers without recreating?"):
        raise typer.Abort()
    emit({"started_existing_containers": start_stf(ctx.obj)})


@app.command()
@guarded
def doctor(ctx: typer.Context, device: DeviceOption):
    """Read-only device/service checks. Does not install CA, provision, or reserve jobs."""
    from sniffer.integrations.appium import status
    settings: Settings = ctx.obj
    target = resolve(settings, device)
    result = {
        "device": device,
        "adb_serial": target.adb_serial,
        "executables": {n: bool(shutil.which(n)) for n in ("adb", "docker", "appium", "mitmdump")},
        "python_extras": {
            n: importlib.util.find_spec(n) is not None for n in ("appium", "mitmproxy", "frida")
        },
        "appium_ready": status(target.appium_url),
        "beanstalk_reachable": reachable(settings.beanstalk.host, settings.beanstalk.port),
        "ca_trust": "not verified; requires explicit setup and HTTPS capture test",
        "frida_target_configured": bool(target.frida_endpoint or target.frida_device_id),
    }
    try:
        result["android"] = ADB(target.adb_serial).info()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        result["android"] = {"ready": False, "error_type": type(error).__name__}
    result["local_ports"] = {}
    for name, host, port in (
        ("system_port", "127.0.0.1", target.system_port),
        ("proxy_port", target.proxy_host, target.proxy_port),
    ):
        try:
            require_free_port(host, port)
            result["local_ports"][name] = "available"
        except RuntimeError:
            result["local_ports"][name] = "occupied; identify owner before reuse"
    emit(result)


@app.command()
@guarded
def provision(
    ctx: typer.Context,
    device: DeviceOption,
    proxy: Annotated[str | None, typer.Option(help="Explicit HOST:PORT; changes Android global proxy.")] = None,
    reverse_port: Annotated[int | None, typer.Option(min=1024, max=65535)] = None,
    clear_proxy: bool = False,
):
    """Minimal opt-in proxy setup. Without flags, only checks device info. No CA/root installs."""
    settings: Settings = ctx.obj
    if proxy and clear_proxy:
        raise ValueError("--proxy and --clear-proxy are mutually exclusive.")
    if proxy:
        match = re.fullmatch(r"([A-Za-z0-9.-]+):([0-9]{1,5})", proxy)
        if not match or not 1 <= int(match[2]) <= 65535:
            raise ValueError("Proxy must be a hostname/IPv4:PORT without credentials.")
    with lock(settings, f"device-{device}"):
        adb = ADB(resolve(settings, device).adb_serial)
        adb.ready(connect=True)
        if reverse_port:
            adb.command("reverse", f"tcp:{reverse_port}", f"tcp:{reverse_port}")
        if proxy:
            adb.command("shell", "settings", "put", "global", "http_proxy", proxy)
        if clear_proxy:
            adb.command("shell", "settings", "put", "global", "http_proxy", ":0")
        emit({"device": device, "android": adb.info(), "ca_installed_by_command": False})


@appium.command("start")
@guarded
def appium_start(
    ctx: typer.Context,
    host: str = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1024, max=65535)] = 4723,
):
    """Foreground Appium server. Install Node/Appium/UiAutomator2 separately."""
    executable = shutil.which("appium")
    if not executable:
        raise RuntimeError("Appium server is not installed; see docs/server-setup.md.")
    with lock(ctx.obj, f"appium-{port}"):
        require_free_port(host, port)
        result = subprocess.run(
            [executable, "--address", host, "--port", str(port)], check=False
        )
        if result.returncode:
            raise RuntimeError(f"Appium exited with code {result.returncode}.")


@app.command("capture")
@guarded
def capture_command(
    ctx: typer.Context,
    platform: str,
    device: DeviceOption,
    duration: Annotated[int, typer.Option(min=1, max=86400)] = 60,
    raw: Annotated[bool, typer.Option(help="UNREDACTED sensitive .mitm file; off by default.")] = False,
):
    """Standalone capture; no Appium, Frida, or app launch."""
    from sniffer.capture.session import record
    emit(record(ctx.obj, device, platform, duration=duration, raw=raw))


@mitm.command("start")
@guarded
def mitm_start(
    ctx: typer.Context,
    platform: str,
    device: DeviceOption,
    duration: Annotated[int, typer.Option(min=1, max=86400)] = 3600,
    raw: bool = False,
):
    """Foreground proxy + recorder, independently of automation."""
    from sniffer.capture.session import record
    emit(record(ctx.obj, device, platform, duration=duration, raw=raw))


@instagram.command("search")
@guarded
def instagram_search(
    ctx: typer.Context,
    device: DeviceOption,
    keyword: Annotated[str, typer.Option()],
    job_id: str | None = None,
    scroll_count: int = 5,
    scroll_pause_ms: int = 1500,
    capture: bool = True,
    frida: bool = False,
    frida_endpoint: Annotated[
        str | None, typer.Option(help="One-run Frida endpoint override; requires --frida.")
    ] = None,
    frida_script: Annotated[
        list[str] | None,
        typer.Option("--frida-script", help="Packaged .js resource; repeatable; requires --frida."),
    ] = None,
    frida_spawn: Annotated[
        bool,
        typer.Option(
            "--frida-spawn/--no-frida-spawn",
            help="Disable to require running, foreground Instagram; no spawn/activation.",
        ),
    ] = True,
    dry_run: bool = False,
):
    settings: Settings = ctx.obj
    if not frida_spawn and not frida:
        raise ValueError("--no-frida-spawn requires --frida.")
    if frida_endpoint is not None or frida_script:
        if not frida:
            raise ValueError("Frida overrides require explicit --frida.")
        # No YAML/registry mutation: useful for a single controlled diagnostic run.
        settings = settings.model_copy(deep=True)
        if frida_endpoint is not None:
            target = resolve(settings, device)
            settings.devices[device] = target.model_copy(update={
                "frida_endpoint": frida_endpoint, "frida_device_id": None,
            })
        if frida_script:
            if "instagram" not in settings.platforms:
                raise ValueError("Instagram configuration missing.")
            settings.platforms["instagram"].frida_scripts = frida_script
    job = SearchJob(
        job_id=job_id or f"manual-{uuid.uuid4().hex}",
        keyword=keyword, scroll_count=scroll_count, scroll_pause_ms=scroll_pause_ms,
    )
    emit(execute(
        settings, device, "instagram", job, capture=capture, frida=frida,
        frida_spawn=frida_spawn, dry_run=dry_run,
    ))


@instagram.command("collect")
@guarded
def instagram_collect(
    ctx: typer.Context,
    device: DeviceOption,
    keyword: Annotated[str, typer.Option()],
    targeted_trial: Annotated[
        bool, typer.Option(help="Explicit approved targeted native trial, maximum120seconds.")
    ] = False,
    publish: Annotated[bool, typer.Option(help="Publish normalized posts to the configured results tube.")] = False,
    dry_run: bool = False,
):
    """One foreground search, exactly10 scrolls, read-only remote capture; no worker loop."""
    from sniffer.collect import collect
    job = SearchJob(
        job_id=f"collect-{uuid.uuid4().hex}", keyword=keyword, scroll_count=10,
    )
    emit(collect(
        ctx.obj, device, job, trial=targeted_trial, publish=publish, dry_run=dry_run,
    ))


@results_cli.command("publish")
@guarded
def results_publish(output: Annotated[Path, typer.Option(help="Existing session with result-outbox.json.")]):
    """Resume saved result puts only; never rerun search or reserve input jobs."""
    from sniffer.results import publish_outbox
    emit(publish_outbox(output))


@results_cli.command("prepare")
@guarded
def results_prepare(
    ctx: typer.Context,
    output: Annotated[Path, typer.Option(help="Completed collect capture without an outbox.")],
):
    """Prepare a saved successful capture for publish; does not send any message."""
    from sniffer.results import prepare_saved_outbox
    if ctx.obj.results.tube == ctx.obj.beanstalk.instagram_tube:
        raise ValueError("Results tube must differ from the input job tube.")
    emit(prepare_saved_outbox(output, ctx.obj.results))


@app.command("worker")
@guarded
def worker_command(
    ctx: typer.Context,
    platform: str,
    device: DeviceOption,
    capture: bool = True,
    frida: bool = False,
    once: Annotated[bool, typer.Option(help="Handle at most one reserve; useful for integration tests.")] = False,
):
    from sniffer.worker import run_worker
    run_worker(ctx.obj, device, platform, capture=capture, frida=frida, once=once)


@app.command("worker-keywords")
@guarded
def worker_keywords(
    ctx: typer.Context,
    device: DeviceOption,
    targeted_trial: Annotated[
        bool, typer.Option(help="Explicitly enable approved per-job targeted trial (max120s).")
    ] = False,
    once: Annotated[bool, typer.Option(help="Handle at most one reservation.")] = False,
):
    """Watch keyword-only jobs; proxy captures/publishes externally."""
    from sniffer.worker import run_keyword_worker
    run_keyword_worker(ctx.obj, device, targeted_trial=targeted_trial, once=once)


@frida_cli.command("inspect")
@guarded
def frida_inspect(
    ctx: typer.Context,
    device: DeviceOption,
    endpoint: Annotated[str, typer.Option(help="Explicit reachable Frida endpoint.")],
    realm: str = "native",
    duration: Annotated[int, typer.Option(min=1, max=30)] = 5,
):
    """Metadata-only attach to running Instagram; never spawn, bypass TLS, or alter proxy."""
    from sniffer.integrations.frida import inspect_runtime
    emit(inspect_runtime(ctx.obj, device, endpoint, realm, duration))
