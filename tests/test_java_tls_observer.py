import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("src/sniffer/scripts/shared/java_tls_observer.js")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node optional; Java bridge simulation only")
@pytest.mark.parametrize("scenario", [
    "observe", "no_bridge", "unavailable", "missing", "limit", "transport", "metadata_error",
    "facebook",
])
def test_java_observer_in_simulated_bridge(scenario):
    result = subprocess.run(
        ["node", "tests/fixtures/java_tls_observer_harness.cjs", str(SCRIPT), scenario],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"]
