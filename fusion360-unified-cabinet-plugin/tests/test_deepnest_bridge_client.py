import io
import json
import os
import socket
import sys
import threading
import time
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from nesting.engines import deepnest_bridge_client as client
from nesting.engines import deepnest


class _FakeProcess:
    next_pid = 100

    def __init__(self, command, responder):
        self.command = command
        self.responder = responder
        self.requests = []
        self.returncode = None
        self.pid = _FakeProcess.next_pid
        _FakeProcess.next_pid += 1
        self.stderr = io.StringIO("")
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen()
        port_file = command[command.index("--port-file") + 1]
        with open(port_file, "w", encoding="utf-8") as stream:
            json.dump({"port": self._server.getsockname()[1], "pid": self.pid}, stream)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while self.returncode is None:
            try:
                connection, _address = self._server.accept()
            except OSError:
                return
            with connection:
                with connection.makefile(
                    "r", encoding="utf-8", newline="\n"
                ) as stream:
                    line = stream.readline()
                if not line:
                    continue
                request = json.loads(line)
                self.requests.append(request)
                response = self.responder(request)
                if response:
                    connection.sendall(response.encode("utf-8"))
                if request.get("op") == "shutdown":
                    self.returncode = 0
                    self._server.close()
                    return

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9
        self._server.close()

    def wait(self, timeout=None):
        deadline = time.monotonic() + (timeout or 0)
        while self.returncode is None and time.monotonic() < deadline:
            time.sleep(0.005)
        if self.returncode is None:
            raise TimeoutError()
        return self.returncode


class DeepnestBridgeClientTests(unittest.TestCase):
    @staticmethod
    def _part_with_hole():
        return {
            "_deepnestSourceId": "0",
            "widthMm": 100,
            "depthMm": 50,
            "boardTypeTag": "ply",
            "colorTag": "",
            "outline": {
                # Deliberately clockwise; the adapter must correct it.
                "points": [[10, 20], [10, 70], [110, 70], [110, 20], [10, 20]],
                # Deliberately counter-clockwise; holes must become clockwise.
                "holes": [
                    {
                        "points": [
                            [30, 30],
                            [60, 30],
                            [60, 50],
                            [30, 50],
                            [30, 30],
                        ]
                    }
                ],
            },
        }

    @staticmethod
    def _params(allow_parts_in_part):
        return {
            "borderMm": 0,
            "spacingMm": 0,
            "allowRotation": True,
            "allowPartsInPart": allow_parts_in_part,
            "rotationIncrementDeg": 90,
        }

    def test_geometry_signature_ignores_search_limits(self):
        job = {
            "parts": [{"id": "a", "points": [[0, 0], [1, 0], [1, 1]]}],
            "sheet": {"widthMm": 10, "heightMm": 10},
            "options": {"spacingMm": 1, "timeBudgetMs": 1000, "maxResults": 1},
        }
        changed_limits = {
            **job,
            "options": {
                **job["options"],
                "timeBudgetMs": 9000,
                "maxResults": 20,
            },
        }
        self.assertEqual(
            deepnest._geometry_signature(job),
            deepnest._geometry_signature(changed_limits),
        )

    def test_job_schema_winding_hole_gating_and_signature(self):
        captured = []

        def run(job):
            captured.append(job)
            return {"placements": [], "fitness": 1}

        part = self._part_with_hole()
        sheet = {"boardTypeTag": "ply", "widthMm": 300, "heightMm": 200}
        with mock.patch.object(deepnest, "_run_bridge", side_effect=run):
            _sheets, _unplaced, enabled = deepnest._pack_job(
                [part], sheet, self._params(True)
            )
            _sheets, _unplaced, disabled = deepnest._pack_job(
                [part], sheet, self._params(False)
            )

        enabled_part = captured[0]["parts"][0]
        disabled_part = captured[1]["parts"][0]
        self.assertGreater(deepnest.nesting_outline.signed_polygon_area(enabled_part["points"]), 0)
        self.assertLess(deepnest.nesting_outline.signed_polygon_area(enabled_part["holes"][0]), 0)
        self.assertNotEqual(enabled_part["points"][0], enabled_part["points"][-1])
        self.assertNotEqual(enabled_part["holes"][0][0], enabled_part["holes"][0][-1])
        self.assertEqual(disabled_part["holes"], [])
        self.assertEqual(enabled["holeOutlineCount"], 1)
        self.assertEqual(disabled["holeOutlineCount"], 0)
        self.assertNotEqual(
            captured[0]["geometrySignature"], captured[1]["geometrySignature"]
        )

    def test_packed_holes_share_outer_rotation_and_min_corner_frame(self):
        part = self._part_with_hole()
        sheet = {"boardTypeTag": "ply", "widthMm": 300, "heightMm": 200}

        def run(_job):
            return {
                "placements": [
                    {
                        "sheetplacements": [
                            {
                                "filename": "0",
                                "x": 5,
                                "y": 7,
                                "rotation": 90,
                                "inHole": True,
                            }
                        ]
                    }
                ],
                "fitness": 1,
            }

        with mock.patch.object(deepnest, "_run_bridge", side_effect=run):
            sheets, _unplaced, diagnostics = deepnest._pack_job(
                [part], sheet, self._params(True)
            )

        placement = sheets[0]["placements"][0]
        _outer, holes = deepnest._outline_tree(part, include_holes=True)
        expected_hole = deepnest.nesting_outline.translate_polygon(
            deepnest.nesting_outline.rotate_polygon(holes[0], 90), 5, 7
        )
        self.assertEqual(len(placement["packedHoles"]), 1)
        for actual, expected in zip(placement["packedHoles"][0], expected_hole):
            self.assertAlmostEqual(actual[0], expected[0])
            self.assertAlmostEqual(actual[1], expected[1])
        self.assertEqual(placement["localX"], -65)
        self.assertEqual(placement["localY"], 17)
        self.assertTrue(placement["inHole"])
        self.assertEqual(diagnostics["holeOutlineCount"], 1)
        self.assertEqual(diagnostics["nestedInHoleCount"], 1)

    def test_layout_reports_parts_in_part_only_when_holes_were_sent(self):
        item = self._part_with_hole()
        item.pop("_deepnestSourceId")

        def packed(_parts, _sheet, params):
            count = 1 if params["allowPartsInPart"] else 0
            return [], [], {
                "fitness": 1,
                "evaluatedResults": 1,
                "holeOutlineCount": count,
                "nestedInHoleCount": 0,
            }

        with mock.patch.object(deepnest, "_pack_job", side_effect=packed):
            enabled = deepnest.layout(
                [item], {"allowPartsInPart": True}, 0, 0
            )
            disabled = deepnest.layout(
                [item], {"allowPartsInPart": False}, 0, 0
            )
        self.assertTrue(enabled["partsInPartApplied"])
        self.assertEqual(enabled["holeOutlineCount"], 1)
        self.assertFalse(disabled["partsInPartApplied"])
        self.assertEqual(disabled["holeOutlineCount"], 0)

    def test_worker_reuses_process_and_matches_request_ids(self):
        processes = []
        popen_options = []

        def popen(command, **kwargs):
            popen_options.append(kwargs)

            def respond(request):
                response = {"id": request["id"], "ok": True}
                if request["op"] == "run":
                    response["result"] = request["job"]
                return json.dumps(response) + "\n"

            process = _FakeProcess(
                command,
                respond,
            )
            processes.append(process)
            return process

        worker = client._Worker(
            0,
            popen_factory=popen,
            runtime_paths=("vendor", "main.cjs", "electron"),
        )
        self.assertEqual(worker.request("run", {"value": 1})["result"]["value"], 1)
        self.assertEqual(worker.request("run", {"value": 2})["result"]["value"], 2)
        self.assertEqual(len(processes), 1)
        self.assertEqual(worker.health()["requests"], 2)
        port_file = processes[0].command[
            processes[0].command.index("--port-file") + 1
        ]
        self.assertTrue(os.path.exists(port_file))
        self.assertEqual(popen_options[0]["stdin"], client.subprocess.DEVNULL)
        self.assertEqual(popen_options[0]["stdout"], client.subprocess.DEVNULL)
        worker.shutdown()
        self.assertFalse(os.path.exists(port_file))

    def test_worker_restarts_and_retries_once_after_eof(self):
        processes = []

        def popen(command, **_kwargs):
            if not processes:
                responder = lambda _request: ""
            else:
                def responder(request):
                    response = {"id": request["id"], "ok": True}
                    if request["op"] == "run":
                        response["result"] = {"ok": True}
                    return json.dumps(response) + "\n"
            process = _FakeProcess(command, responder)
            processes.append(process)
            return process

        worker = client._Worker(
            0,
            popen_factory=popen,
            runtime_paths=("vendor", "main.cjs", "electron"),
        )
        self.assertTrue(worker.request("run", {})["result"]["ok"])
        self.assertEqual(len(processes), 2)
        self.assertEqual(worker.health()["restarts"], 1)
        worker.shutdown()

    def test_pool_limits_concurrency_to_two_workers(self):
        state = {"active": 0, "maximum": 0}
        state_lock = threading.Lock()

        class SlowWorker:
            def __init__(self, index):
                self.index = index

            def request(self, _op, job, _timeout):
                with state_lock:
                    state["active"] += 1
                    state["maximum"] = max(state["maximum"], state["active"])
                time.sleep(0.05)
                with state_lock:
                    state["active"] -= 1
                return {"result": job}

            def health(self):
                return {"worker": self.index}

            def shutdown(self):
                pass

        pool = client.BridgePool(worker_factory=SlowWorker)
        results = []
        threads = [
            threading.Thread(target=lambda value=i: results.append(pool.run({"value": value})))
            for i in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 4)
        self.assertEqual(state["maximum"], 2)
        self.assertEqual(pool.health()["size"], 2)
        pool.shutdown()


if __name__ == "__main__":
    unittest.main()
