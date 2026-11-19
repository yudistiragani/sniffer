"""One opt-in native official-REPL trial with an explicit bounded duration."""

from __future__ import annotations

import ast
import importlib.metadata
import importlib.resources
import os
import subprocess
import sys
import threading
import time

from sniffer.capture.writer import append_json
from sniffer.device import ADB


class TrialREPL:
    def __init__(self, device, output, *, duration_seconds=120):
        if duration_seconds not in {120, 300}:
            raise ValueError("Targeted trial duration must be 120 or 300 seconds.")
        self.device, self.output = device, output
        self.duration_seconds = duration_seconds
        self.process = None
        self.reader = None
        self.ready = threading.Event()
        self.failure = None
        self.deadline = None
        self.closing = False

    def __enter__(self):
        try:
            if (
                importlib.metadata.version("frida") != "17.27.0"
                or importlib.metadata.version("frida-tools") != "14.13.2"
            ):
                raise RuntimeError("Trial requires pinned Frida17.27.0/frida-tools14.13.2.")
            if not self.device.frida_endpoint:
                raise ValueError("Set the explicit existing Frida endpoint; no server is started.")
            result = ADB(self.device.adb_serial).command(
                "shell", "pidof", "com.instagram.android", check=False,
            )
            pids = result.stdout.split()
            if result.returncode != 0 or len(pids) != 1 or not pids[0].isdecimal():
                raise RuntimeError("Open Instagram manually; expected exactly one main PID.")
            source = importlib.resources.files("sniffer").joinpath(
                "scripts/instagram/facebook_pinning_trial.js",
            ).read_text(encoding="utf-8")
            script = self.output / "collect-trial.js"
            script.write_text(
                f'"use strict";\nglobalThis.__snifferTrialDurationMs = {self.duration_seconds * 1000};\n'
                + source,
                encoding="utf-8",
            )
            self.deadline = time.monotonic() + self.duration_seconds - 2
            self.process = subprocess.Popen(
                [
                    sys.executable, "-u", "-m", "frida_tools.repl",
                    "-H", self.device.frida_endpoint, "-p", pids[0], "--realm", "native",
                    "-q", "-t", str(self.duration_seconds),
                    "--exit-on-error", "--no-auto-reload", "-l", str(script),
                ],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            self.reader = threading.Thread(target=self._read, daemon=True, name="trial-repl-events")
            self.reader.start()
            setup_deadline = time.monotonic() + 20
            while not self.ready.wait(0.1):
                self.check()
                if time.monotonic() >= setup_deadline:
                    raise RuntimeError("Trial readiness timed out; no automatic attach retry.")
            self.check()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _read(self):
        try:
            while line := self.process.stdout.readline(16385):
                self._line(line)
        except Exception:
            self.failure = "trial_event_reader_failed"

    def _line(self, line):
        # Official pinned REPL's send output is a Python repr, not arbitrary executable text.
        if len(line) > 16384 or not line.startswith("message: ") or " data: " not in line:
            return
        try:
            message = ast.literal_eval(line[len("message: "):].split(" data: ", 1)[0])
            payload = message.get("payload") if message.get("type") == "send" else None
            if not isinstance(payload, dict):
                return
            event = payload.get("event")
            if event not in {
                "fb_trial.runtime", "fb_trial.ready", "fb_trial.refused",
                "fb_trial.override", "fb_trial.original_return",
                "fb_trial.preserved_rejection", "fb_trial.limit",
            }:
                return
            # Do not persist REPL lines, raw attach errors, binary data or arbitrary fields.
            safe = {key: value for key, value in payload.items() if key in {
                "event", "durationMs", "callId", "systemTrustObserved", "hostAllowed", "maxEvents",
            } and isinstance(value, (str, int, bool))}
            append_json(self.output / "frida.jsonl", safe)
            if event == "fb_trial.refused":
                self.failure = "trial_refused"
            elif event == "fb_trial.ready":
                if payload.get("durationMs") != self.duration_seconds * 1000:
                    self.failure = "trial_duration_mismatch"
                else:
                    self.ready.set()
        except (ValueError, TypeError, AttributeError, RecursionError):
            self.failure = "invalid_trial_event"

    def check(self):
        if self.failure:
            raise RuntimeError(f"Targeted trial stopped: {self.failure}; no automatic retry.")
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("Frida REPL exited; stop and inspect server/app before another run.")
        if time.monotonic() >= self.deadline:
            raise RuntimeError(
                f"Targeted trial {self.duration_seconds}s window expired; automation stopped."
            )

    def __exit__(self, *_):
        self.closing = True
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()  # only this run's REPL child, never IG/server/STF
                    self.process.wait(timeout=5)
            if self.reader:
                self.reader.join(timeout=2)
            if self.process.stdout:
                self.process.stdout.close()
