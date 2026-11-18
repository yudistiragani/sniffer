import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("src/sniffer/scripts/shared/tls_observer.js")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is optional; used only for JS simulation")
@pytest.mark.parametrize("scenario", [
    "native", "matching_arm", "translated", "unreadable", "missing",
    "forwarded", "hook_error", "unload", "limit",
])
def test_observer_in_simulated_gumjs(scenario):
    result = subprocess.run(
        ["node", "tests/fixtures/tls_observer_harness.cjs", str(SCRIPT), scenario],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"]
