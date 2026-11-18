import json

from typer.testing import CliRunner

from sniffer.cli import app

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "automation" in result.output and "worker" in result.output


def test_instagram_search_dry_run():
    result = runner.invoke(app, [
        "automation", "instagram", "search", "--device", "android01",
        "--keyword", "kopi lokal", "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["job"]["keyword"] == "kopi lokal"
    assert data["dry_run"] is True


def test_unknown_device_and_invalid_payload():
    result = runner.invoke(app, [
        "automation", "instagram", "search", "--device", "unknown",
        "--keyword", "coffee", "--dry-run",
    ])
    assert result.exit_code == 1 and "Unknown device" in result.output
    result = runner.invoke(app, [
        "automation", "instagram", "search", "--device", "android01",
        "--keyword", "coffee", "--scroll-count", "-1", "--dry-run",
    ])
    assert result.exit_code != 0


def test_tiktok_worker_fails_before_queue_access():
    result = runner.invoke(app, ["worker", "tiktok", "--device", "android01", "--once"])
    assert result.exit_code == 1 and "Instagram" in result.output


def test_device_list_is_metadata_only():
    result = runner.invoke(app, ["device", "list"])
    assert result.exit_code == 0
    assert json.loads(result.output)["android01"]["ownership"] == "adopted"


def test_frida_override_requires_explicit_enable():
    result = runner.invoke(app, [
        "automation", "instagram", "search", "--device", "android01",
        "--keyword", "coffee", "--frida-endpoint", "127.0.0.1:27052", "--dry-run",
    ])
    assert result.exit_code == 1 and "require explicit --frida" in result.output


def test_frida_one_run_overrides_do_not_mutate_settings(settings, monkeypatch):
    import sniffer.cli as cli
    monkeypatch.setattr(cli, "load_settings", lambda _: settings)
    observed = {}
    def fake(current, *_, **kwargs):
        observed["settings"] = current
        return {"frida": kwargs["frida"]}
    monkeypatch.setattr(cli, "execute", fake)
    result = runner.invoke(app, [
        "automation", "instagram", "search", "--device", "android01",
        "--keyword", "coffee", "--no-capture", "--frida",
        "--frida-endpoint", "127.0.0.1:27052",
        "--frida-script", "shared/tls_observer.js",
        "--frida-script", "shared/observe.js", "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    changed = observed["settings"]
    assert changed.devices["android01"].frida_endpoint == "127.0.0.1:27052"
    assert changed.platforms["instagram"].frida_scripts == [
        "shared/tls_observer.js", "shared/observe.js"
    ]
    assert settings.devices["android01"].frida_endpoint is None
    assert settings.platforms["instagram"].frida_scripts == []


def test_frida_inspect_cli_forwards_explicit_realm(monkeypatch):
    import sniffer.integrations.frida as integration
    seen = {}
    def fake(settings, device, endpoint, realm, duration):
        seen.update(device=device, endpoint=endpoint, realm=realm, duration=duration)
        return {"tls_verification_changed": False}
    monkeypatch.setattr(integration, "inspect_runtime", fake)
    result = runner.invoke(app, [
        "frida", "inspect", "--device", "android01", "--endpoint", "127.0.0.1:27052",
        "--realm", "emulated", "--duration", "1",
    ])
    assert result.exit_code == 0, result.output
    assert seen == {
        "device": "android01", "endpoint": "127.0.0.1:27052", "realm": "emulated", "duration": 1
    }
