"""EDDN ZeroMQ subscriber — receives real-time game data from the network."""

import asyncio
import json
import logging
import queue
import threading
import time
import zlib
from typing import Callable

import zmq

from archons_eye.config import config

log = logging.getLogger(__name__)

SCHEMA_COMMODITY = "https://eddn.edcd.io/schemas/commodity/3"
SCHEMA_JOURNAL   = "https://eddn.edcd.io/schemas/journal/1"

MessageHandler = Callable[[dict], None]

_RECV_TIMEOUT_MS   = 5_000   # ZMQ recv poll interval
_QUEUE_MAXSIZE     = 2_000   # buffer for bursts
_MAX_ERRORS        = 10      # consecutive recv errors before reconnect
_SILENCE_TIMEOUT_S = 120     # reconnect if no message for 2 minutes
_RECONNECT_DELAY_S = 5       # wait before reconnecting
_BATCH_SIZE        = 100     # messages processed per asyncio yield
_POLL_SLEEP_S      = 0.001   # 1ms idle sleep — avoids busy-loop, keeps latency low

_RECV_OK      = 0
_RECV_TIMEOUT = 1
_RECV_ERROR   = 2

# Diagnostic thresholds
_WARN_BATCH_MS    = 100   # warn if processing a batch of 100 takes > 100ms
_WARN_SLEEP_MS    = 150   # warn if asyncio.sleep(0) blocks > 150ms (Qt blocking the loop)
_WATCHDOG_SECS    = 5.0   # watchdog fires if no progress for this long
_HEARTBEAT_EVERY  = 500   # log consumer heartbeat every N messages


class EDDNListener:
    """ZMQ recv runs in a dedicated daemon thread.
    A stdlib queue.Queue bridges the thread to the asyncio consumer — this avoids
    calling call_soon_threadsafe on every message, which on Windows issues a socket
    send per call and eats 10-20% of the event loop at EDDN's burst rate.
    """

    def __init__(self, on_message: MessageHandler) -> None:
        self._on_message      = on_message
        self._running         = False
        self._stop_requested  = False
        self._messages_received = 0
        self._thread: threading.Thread | None = None
        # Drop tracking (written only from ZMQ thread, GIL-safe for int ops)
        self._drop_count    = 0
        self._last_drop_log = 0.0
        # Diagnostic counters (ZMQ thread writes _zmq_recv_count; consumer writes _last_consumed_at)
        self._zmq_recv_count  = 0
        self._last_consumed_at = time.monotonic()

    @property
    def messages_received(self) -> int:
        return self._messages_received

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Asyncio side — polls the stdlib queue; no call_soon_threadsafe needed
    # ------------------------------------------------------------------

    async def run(self) -> None:
        self._stop_requested = False
        msg_queue: queue.Queue[dict] = queue.Queue(maxsize=_QUEUE_MAXSIZE)

        self._thread = threading.Thread(
            target=self._recv_thread,
            args=(msg_queue,),
            daemon=True,
            name="eddn-zmq",
        )
        self._thread.start()
        log.debug("ZMQ thread spawned")

        watchdog = threading.Thread(
            target=self._watchdog,
            args=(msg_queue,),
            daemon=True,
            name="eddn-watchdog",
        )
        watchdog.start()

        try:
            while self._thread.is_alive() or not msg_queue.empty():
                count = self._drain_batch(msg_queue)
                await self._yield_to_qt(count)
        finally:
            self._running = False

    def _drain_batch(self, msg_queue: queue.Queue) -> int:
        """Drain up to _BATCH_SIZE messages and return the count processed."""
        count = 0
        t_start = time.monotonic()
        while count < _BATCH_SIZE:
            try:
                msg = msg_queue.get_nowait()
            except queue.Empty:
                break
            self._messages_received += 1
            try:
                self._on_message(msg)
            except Exception:
                log.exception(
                    "EDDN consumer: _on_message raised (schema=%s) — skipping",
                    msg.get("$schemaRef", "?"),
                )
            count += 1

        if count > 0:
            self._last_consumed_at = time.monotonic()
            elapsed_ms = (self._last_consumed_at - t_start) * 1000
            if elapsed_ms > _WARN_BATCH_MS:
                log.warning("Consumer: batch of %d msgs took %.0f ms", count, elapsed_ms)
            n = self._messages_received
            if n % _HEARTBEAT_EVERY == 0:
                log.debug("Consumer: %d processed, queue depth %d, ZMQ recv %d",
                          n, msg_queue.qsize(), self._zmq_recv_count)
        return count

    async def _yield_to_qt(self, last_count: int) -> None:
        """Yield to the Qt event loop; warn if it stalls us longer than expected."""
        delay = 0 if last_count > 0 else _POLL_SLEEP_S
        t_start = time.monotonic()
        await asyncio.sleep(delay)
        sleep_ms = (time.monotonic() - t_start) * 1000
        if sleep_ms > _WARN_SLEEP_MS:
            log.warning(
                "Consumer: asyncio.sleep(%.0fms) blocked for %.0f ms — Qt may be stalling the loop",
                delay * 1000, sleep_ms,
            )

    def stop(self) -> None:
        self._stop_requested = True
        self._running = False

    # ------------------------------------------------------------------
    # Watchdog thread — fires if consumer goes silent for _WATCHDOG_SECS
    # ------------------------------------------------------------------

    def _watchdog(self, msg_queue: queue.Queue) -> None:
        log.debug("Watchdog started")
        while not self._stop_requested:
            time.sleep(_WATCHDOG_SECS)
            age = time.monotonic() - self._last_consumed_at
            if age > _WATCHDOG_SECS:
                log.error(
                    "Consumer silent for %.1f s — "
                    "zmq_alive=%s  zmq_recv=%d  consumed=%d  queue=%d  full=%s",
                    age,
                    self._thread.is_alive() if self._thread else False,
                    self._zmq_recv_count,
                    self._messages_received,
                    msg_queue.qsize(),
                    msg_queue.full(),
                )

    # ------------------------------------------------------------------
    # Thread side — reconnect loop owns all ZMQ objects
    # ------------------------------------------------------------------

    def _recv_thread(self, msg_queue: queue.Queue) -> None:
        log.debug("ZMQ thread started")
        while not self._stop_requested:
            self._connect_and_recv(msg_queue)
            if self._stop_requested:
                break
            log.info("EDDN: reconnecting in %ds...", _RECONNECT_DELAY_S)
            self._running = False
            for _ in range(_RECONNECT_DELAY_S * 10):
                if self._stop_requested:
                    break
                time.sleep(0.1)
        self._running = False
        log.info("EDDN listener thread stopped")

    def _connect_and_recv(self, msg_queue: queue.Queue) -> None:
        ctx  = zmq.Context()
        sock = ctx.socket(zmq.SUB)
        sock.setsockopt(zmq.RCVTIMEO, _RECV_TIMEOUT_MS)
        sock.setsockopt_string(zmq.SUBSCRIBE, "")
        try:
            sock.connect(config.eddn_relay)
            self._running = True
            log.info("Connected to EDDN: %s", config.eddn_relay)

            consecutive_errors = 0
            last_msg_time      = time.monotonic()

            while not self._stop_requested:
                result = self._recv_one(sock, msg_queue)

                if result == _RECV_OK:
                    consecutive_errors = 0
                    last_msg_time = time.monotonic()
                elif result == _RECV_ERROR:
                    consecutive_errors += 1
                    if consecutive_errors >= _MAX_ERRORS:
                        log.warning("EDDN: %d consecutive errors — reconnecting", consecutive_errors)
                        break

                if time.monotonic() - last_msg_time > _SILENCE_TIMEOUT_S:
                    log.info("EDDN: no messages for %.0fs — reconnecting",
                             time.monotonic() - last_msg_time)
                    break

        except Exception as exc:
            log.error("EDDN connect error: %s", exc)
        finally:
            sock.close()
            ctx.term()
            self._running = False

    def _recv_one(self, sock: zmq.Socket, msg_queue: queue.Queue) -> int:
        try:
            raw = sock.recv()
            msg = _decode(raw)
            if msg:
                self._zmq_recv_count += 1
                if self._zmq_recv_count % _HEARTBEAT_EVERY == 0:
                    log.debug(
                        "ZMQ: received %d msgs, queue depth %d/%d",
                        self._zmq_recv_count, msg_queue.qsize(), _QUEUE_MAXSIZE,
                    )
                try:
                    msg_queue.put_nowait(msg)
                except queue.Full:
                    self._track_drop()
            return _RECV_OK
        except zmq.Again:
            return _RECV_TIMEOUT
        except Exception as exc:
            log.error("EDDN recv error: %s", exc, exc_info=True)
            return _RECV_ERROR

    def _track_drop(self) -> None:
        self._drop_count += 1
        now = time.monotonic()
        if now - self._last_drop_log >= 10.0:
            log.warning("EDDN: dropped %d messages (queue full — consumer falling behind)",
                        self._drop_count)
            self._drop_count    = 0
            self._last_drop_log = now


def _decode(raw: bytes) -> dict | None:
    try:
        return json.loads(zlib.decompress(raw))
    except Exception:
        return None


def schema_of(msg: dict) -> str:
    return msg.get("$schemaRef", "").rstrip("/")


def parse_commodity(msg: dict) -> tuple[str, str, list[dict], str] | None:
    message     = msg.get("message", {})
    system      = message.get("systemName", "")
    station     = message.get("stationName", "")
    commodities = message.get("commodities", [])
    if not system or not commodities:
        return None
    uploader_id = msg.get("header", {}).get("uploaderID", "")
    return system, station, commodities, uploader_id


def parse_journal(msg: dict) -> tuple[str, str, dict, str] | None:
    message     = msg.get("message", {})
    system      = message.get("StarSystem", "")
    event       = message.get("event", "")
    if not system or not event:
        return None
    uploader_id = msg.get("header", {}).get("uploaderID", "")
    return system, event, message, uploader_id
