import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("src/sniffer/scripts/instagram/facebook_pinning_trial.js")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node optional; simulated Java bridge only")
@pytest.mark.parametrize("scenario", [
    "override", "fallback", "original_success", "other_host", "suffix_host",
    "no_trust", "wrong_host", "wrong_leaf", "empty_trust", "trust_reject",
    "swallowed_trust_reject", "nonpinning", "plain_js", "wrong_type",
    "expired", "mid_expiry", "stale", "thread_error", "thread_mismatch",
    "metadata_error", "bridge_missing", "abi", "version", "signature",
    "existing_hook", "partial_install", "transport", "limit",
    "peer_exception", "validity", "proof_failure", "ambiguous", "long_message", "cast_error",
    "subclass",
    "cdn", "cdn_suffix", "other_cdn",
    "duration_120", "duration_120_expired", "duration_300", "duration_300_expired",
    "duration_invalid", "duration_string",
])
def test_pinning_trial_in_simulated_bridge(scenario):
    result = subprocess.run(
        ["node", "tests/fixtures/facebook_pinning_trial_harness.cjs", str(SCRIPT), scenario],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"]
