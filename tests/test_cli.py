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
