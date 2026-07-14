"""Thread-safe client for the persistent Deepnest Electron bridge."""

from __future__ import annotations

import atexit
import collections
import json
import os
import queue
import socket
import subprocess
import tempfile
import threading
import time
import uuid


POOL_SIZE = 2
DEFAULT_TIME_BUDGET_MS = 45000


class BridgeClientError(RuntimeError):
    """Raised when a persistent bridge worker cannot complete a request."""


def _runtime_paths():
    nesting_dir = os.path.dirname(os.path.dirname(__file__))
    vendor_dir = os.path.join(nesting_dir, "vendor", "deepnest-next")
    bridge_main = os.path.join(
        nesting_dir, "engines", "deepnest_bridge", "main.cjs"
    )
    electron = os.path.join(
        vendor_dir, "node_modules", "electron", "dist", "electron.exe"
    )
    return vendor_dir, bridge_main, electron


def _startup_options():
    startup_info = None
    creation_flags = 0
    if os.name == "nt":
        startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return startup_info, creation_flags


class _Worker:
    def __init__(self, index, popen_factory=subprocess.Popen, runtime_paths=None):
        self.index = index
        self._popen_factory = popen_factory
        self._runtime_paths = runtime_paths or _runtime_paths()
        self._lock = threading.Lock()
        self._process = None
        self._port = None
        self._temporary_directory = None
        self._stderr_lines = collections.deque(maxlen=200)
        self._stderr_thread = None
        self._requests = 0
        self._restarts = 0
        self._last_error = None

    def start(self):
        with self._lock:
            self._start_locked()

    def _start_locked(self):
        if self._process is not None and self._process.poll() is None:
            return
        vendor_dir, bridge_main, electron = self._runtime_paths
        startup_info, creation_flags = _startup_options()
        environment = os.environ.copy()
        environment.pop("ELECTRON_RUN_AS_NODE", None)
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="cabinetnc-deepnest-{}-".format(self.index)
        )
        port_file = os.path.join(self._temporary_directory.name, "port.json")
        user_data_dir = os.path.join(
            self._temporary_directory.name, "electron-user-data"
        )
        os.makedirs(user_data_dir, exist_ok=True)
        # Writable per-worker userData avoids Electron disk_cache Access denied
        # when Fusion's default cache folder is locked or shared.
        self._process = self._popen_factory(
            [
                electron,
                bridge_main,
                "--port-file",
                port_file,
                "--user-data-dir={}".format(user_data_dir),
            ],
            cwd=vendor_dir,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            startupinfo=startup_info,
            creationflags=creation_flags,
        )
        self._stderr_thread = threading.Thread(
            target=self._pump_stderr,
            args=(self._process,),
            name="cabinetnc-deepnest-stderr-{}".format(self.index),
            daemon=True,
        )
        self._stderr_thread.start()
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            return_code = self._process.poll()
            if return_code is not None:
                raise BridgeClientError(
                    "Deepnest bridge exited during startup (code {}).".format(
                        return_code
                    )
                )
            try:
                with open(port_file, "r", encoding="utf-8") as stream:
                    details = json.load(stream)
                port = details.get("port")
                if (
                    isinstance(port, int)
                    and 0 < port < 65536
                    and details.get("pid") == self._process.pid
                ):
                    self._port = port
                    return
            except (OSError, ValueError, TypeError):
                pass
            time.sleep(0.05)
        raise TimeoutError("Deepnest bridge did not publish a port within 30s.")

    def _pump_stderr(self, process):
        try:
            for line in process.stderr:
                self._stderr_lines.append(line.rstrip())
        except Exception as ex:
            self._stderr_lines.append("stderr reader failed: {}".format(ex))

    def _stop_locked(self, graceful=False):
        process = self._process
        port = self._port
        temporary_directory = self._temporary_directory
        self._process = None
        self._port = None
        self._temporary_directory = None
        if process is not None and graceful and process.poll() is None and port:
            try:
                request_id = "shutdown-{}".format(uuid.uuid4().hex)
                self._exchange(
                    port,
                    {"id": request_id, "op": "shutdown"},
                    2.0,
                )
                process.wait(timeout=2.0)
            except Exception:
                pass
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except Exception:
                pass
        if process is not None:
            try:
                process.wait(timeout=5.0)
            except Exception:
                pass
            try:
                process.stderr.close()
            except Exception:
                pass
        if temporary_directory is not None:
            try:
                temporary_directory.cleanup()
            except Exception:
                pass

    @staticmethod
    def _exchange(port, request, timeout_seconds):
        payload = (
            json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        try:
            with socket.create_connection(
                ("127.0.0.1", port), timeout_seconds
            ) as connection:
                connection.settimeout(timeout_seconds)
                connection.sendall(payload)
                with connection.makefile("r", encoding="utf-8", newline="\n") as stream:
                    while True:
                        line = stream.readline()
                        if not line or line.strip():
                            return line
        except socket.timeout as ex:
            raise TimeoutError(
                "Deepnest bridge timed out after {:.0f}s.".format(timeout_seconds)
            ) from ex

    def _request_once_locked(self, request, timeout_seconds):
        self._start_locked()
        process = self._process
        line = self._exchange(self._port, request, timeout_seconds)
        if not line:
            raise BridgeClientError(
                "Deepnest bridge exited without a response (code {}).".format(
                    process.poll()
                )
            )
        try:
            response = json.loads(line)
        except ValueError as ex:
            raise BridgeClientError(
                "Deepnest bridge returned invalid JSON: {!r}".format(line[-500:])
            ) from ex
        if response.get("id") != request["id"]:
            raise BridgeClientError(
                "Deepnest bridge response ID mismatch (expected {}, got {}).".format(
                    request["id"], response.get("id")
                )
            )
        if not response.get("ok"):
            raise BridgeClientError(str(response.get("error") or "Deepnest failed."))
        return response

    def request(self, op, job=None, timeout_seconds=120.0):
        request = {"id": uuid.uuid4().hex, "op": op}
        if job is not None:
            request["job"] = job
        with self._lock:
            self._requests += 1
            errors = []
            for attempt in range(2):
                try:
                    response = self._request_once_locked(request, timeout_seconds)
                    self._last_error = None
                    return response
                except Exception as ex:
                    errors.append(ex)
                    self._last_error = str(ex)
                    self._stop_locked()
                    self._restarts += 1
            # Keep the fixed pool healthy even when both attempts fail.
            try:
                self._start_locked()
            except Exception as ex:
                self._last_error = "{}; replacement failed: {}".format(
                    self._last_error, ex
                )
            detail = "\n".join(self._stderr_lines)[-2000:]
            message = "Deepnest request failed twice: {}".format(errors[-1])
            if detail:
                message += "\nBridge stderr:\n" + detail
            raise BridgeClientError(message) from errors[-1]

    def shutdown(self):
        with self._lock:
            self._stop_locked(graceful=True)

    def health(self):
        with self._lock:
            process = self._process
            return {
                "worker": self.index,
                "running": process is not None and process.poll() is None,
                "pid": process.pid if process is not None and process.poll() is None else None,
                "requests": self._requests,
                "restarts": self._restarts,
                "lastError": self._last_error,
                "stderrTail": list(self._stderr_lines)[-20:],
            }


class BridgePool:
    """A fixed pool that assigns each request to one available Electron worker."""

    def __init__(self, worker_factory=None):
        factory = worker_factory or (lambda index: _Worker(index))
        self._workers = [factory(index) for index in range(POOL_SIZE)]
        try:
            for worker in self._workers:
                start = getattr(worker, "start", None)
                if start is not None:
                    start()
        except BaseException:
            for worker in self._workers:
                try:
                    worker.shutdown()
                except Exception:
                    pass
            raise
        self._available = queue.Queue(maxsize=POOL_SIZE)
        for worker in self._workers:
            self._available.put(worker)
        self._closed = False
        self._state_lock = threading.Lock()

    def run(self, job, timeout_seconds=None):
        if timeout_seconds is None:
            budget_ms = float(
                (job.get("options") or {}).get("timeBudgetMs")
                or DEFAULT_TIME_BUDGET_MS
            )
            timeout_seconds = max(budget_ms / 1000.0 + 120.0, 180.0)
        with self._state_lock:
            if self._closed:
                raise BridgeClientError("Deepnest worker pool is shut down.")
        worker = self._available.get()
        try:
            return worker.request("run", job, timeout_seconds)["result"]
        finally:
            self._available.put(worker)

    def health(self):
        with self._state_lock:
            return {
                "closed": self._closed,
                "size": len(self._workers),
                "available": self._available.qsize(),
                "workers": [worker.health() for worker in self._workers],
            }

    def shutdown(self):
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        for worker in self._workers:
            worker.shutdown()


_pool = None
_pool_lock = threading.Lock()
_pool_process_id = None


def _get_pool():
    global _pool, _pool_process_id
    process_id = os.getpid()
    with _pool_lock:
        if _pool is None or _pool_process_id != process_id:
            # A forked child must not terminate the parent's inherited workers.
            # It replaces the singleton with a pool owned by its own PID.
            _pool = BridgePool()
            _pool_process_id = process_id
        return _pool


def run_job(job, timeout_seconds=None):
    return _get_pool().run(job, timeout_seconds)


def health_diagnostics():
    with _pool_lock:
        if _pool is None:
            return {
                "closed": False,
                "size": POOL_SIZE,
                "available": POOL_SIZE,
                "workers": [],
            }
        return _pool.health()


def shutdown_pool():
    global _pool, _pool_process_id
    with _pool_lock:
        pool = _pool
        _pool = None
        _pool_process_id = None
    if pool is not None:
        pool.shutdown()


atexit.register(shutdown_pool)
