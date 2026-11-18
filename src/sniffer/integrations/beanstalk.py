from __future__ import annotations

import socket
import threading
from contextlib import AbstractContextManager

import greenstalk

from sniffer.jobs import InvalidJob
from sniffer.settings import Beanstalk


def connect(config: Beanstalk) -> greenstalk.Client:
    # Bound both connect and read operations; reserve timeout is shorter than socket timeout.
    sock = socket.create_connection(
        (config.host, config.port), timeout=config.reserve_timeout + 3
    )
    try:
        return greenstalk.Client(sock, watch=[config.instagram_tube], use=config.instagram_tube)
    except BaseException:
        sock.close()
        raise


class LeaseLost(RuntimeError):
    pass


class Heartbeat(AbstractContextManager):
    """Touch using the RESERVING connection; never another Beanstalk connection.

    The main thread must not use this client until the heartbeat has stopped.
    greenstalk is not thread-safe, so no client commands are concurrent.
    """

    def __init__(self, client, job, config: Beanstalk, ttr: int):
        if ttr < max(30, (config.reserve_timeout + 3) * 3):
            raise InvalidJob("Job TTR is too short; use at least 30 seconds (recommended: 120).")
        self.client = client
        self.job = job
        self.interval = min(config.touch_interval, ttr / 3)
        self.stop = threading.Event()
        self.lost = threading.Event()
        self.thread = None

    def __enter__(self):
        self.client.touch(self.job)
        self.thread = threading.Thread(target=self._run, daemon=True, name="beanstalk-touch")
        self.thread.start()
        return self

    def _run(self):
        while not self.stop.wait(self.interval):
            try:
                self.client.touch(self.job)
            except Exception:
                self.lost.set()
                return

    def check(self):
        if self.lost.is_set():
            raise LeaseLost("Beanstalk reservation lost; stopping job before acknowledgement.")

    def __exit__(self, *_):
        self.stop.set()
        if self.thread:
            # Socket reads are bounded by connect(); don't issue ACK while a touch is in flight.
            self.thread.join()
