from pathlib import Path

import pytest

from sniffer.settings import load_settings


@pytest.fixture
def settings(tmp_path):
    result = load_settings(Path("config/example.yaml"))
    result.state_dir = tmp_path / ".state"
    result.output_dir = tmp_path / "output"
    result.redroid.data_dir = tmp_path / "data"
    result.mitm_confdir = tmp_path / "mitmproxy"
    return result
