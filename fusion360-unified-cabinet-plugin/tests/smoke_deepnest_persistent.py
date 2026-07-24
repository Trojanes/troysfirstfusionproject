"""Real Electron smoke test for the persistent Deepnest bridge.

Run directly with Fusion's Python or the development Python interpreter.
"""

import concurrent.futures
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from nesting.engines import deepnest
from nesting.engines import deepnest_bridge_client as client


def rectangle_job(label):
    job = {
        "schemaVersion": 1,
        "parts": [
            {
                "id": label,
                "points": [[0, 0], [100, 0], [100, 50], [0, 50]],
            }
        ],
        "sheet": {
            "widthMm": 500,
            "heightMm": 300,
            "borderMm": 10,
            "quantity": 1,
        },
        "options": {
            "spacingMm": 5,
            "allowRotation": True,
            "rotationIncrementDeg": 90,
            "populationSize": 3,
            "mutationRate": 10,
            "placementType": "gravity",
            "maxResults": 1,
            "timeBudgetMs": 10000,
        },
    }
    job["geometrySignature"] = deepnest._geometry_signature(job)
    return job


def hole_job(label, allow_parts_in_part):
    job = {
        "schemaVersion": 1,
        "parts": [
            {
                "id": "{}-parent".format(label),
                "points": [[0, 0], [200, 0], [200, 200], [0, 200]],
                "holes": [
                    [[50, 50], [50, 150], [150, 150], [150, 50]]
                ],
            },
            {
                "id": "{}-child".format(label),
                "points": [[0, 0], [50, 0], [50, 50], [0, 50]],
                "holes": [],
            },
        ],
        "sheet": {
            "widthMm": 204,
            "heightMm": 204,
            "borderMm": 2,
            "quantity": 2,
        },
        "options": {
            "spacingMm": 0,
            "allowRotation": False,
            "rotationIncrementDeg": 90,
            "allowPartsInPart": allow_parts_in_part,
            "populationSize": 10,
            "mutationRate": 10,
            "placementType": "gravity",
            "maxResults": 5,
            "timeBudgetMs": 15000,
        },
    }
    if not allow_parts_in_part:
        job["parts"][0]["holes"] = []
    job["geometrySignature"] = deepnest._geometry_signature(job)
    return job


def flat_placements(result):
    return [
        placement
        for sheet in result.get("placements") or []
        for placement in sheet.get("sheetplacements") or []
    ]


def main():
    paths = client._runtime_paths()
    worker = client._Worker(0, runtime_paths=paths)
    try:
        first = worker.request("run", rectangle_job("first"), timeout_seconds=120)
        first_pid = first["pid"]
        second = worker.request("run", rectangle_job("second"), timeout_seconds=120)
        assert first["result"]["evaluatedResults"] == 1
        assert second["result"]["evaluatedResults"] == 1
        assert len(first["result"]["placements"]) == 1
        assert len(second["result"]["placements"]) == 1
        assert len(first["result"]["placements"][0]["sheetplacements"]) == 1
        assert len(second["result"]["placements"][0]["sheetplacements"]) == 1
        assert second["pid"] == first_pid
        print("sequential worker: PID {} survived both jobs".format(first_pid))

        enabled = worker.request(
            "run", hole_job("holes-on", True), timeout_seconds=120
        )
        disabled = worker.request(
            "run", hole_job("holes-off", False), timeout_seconds=120
        )
        enabled_placements = flat_placements(enabled["result"])
        disabled_placements = flat_placements(disabled["result"])
        assert len(enabled_placements) == 2
        assert len(disabled_placements) == 2
        assert len(enabled["result"]["placements"]) <= len(
            disabled["result"]["placements"]
        )
        exposed = [entry for entry in enabled_placements if "inHole" in entry]
        if exposed:
            assert any(bool(entry.get("inHole")) for entry in exposed)
            print("parts-in-part smoke: Deepnest exposed inHole=true")
        else:
            print(
                "parts-in-part smoke: completed without crash; "
                "this Deepnest result schema does not expose inHole"
            )
    finally:
        worker.shutdown()

    pool = client.BridgePool()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(
                    pool._workers[index % client.POOL_SIZE].request,
                    "run",
                    rectangle_job("pool-{}".format(index)),
                    120,
                )
                for index in range(4)
            ]
            responses = [future.result() for future in futures]
        assert all(
            response["result"]["evaluatedResults"] == 1
            for response in responses
        )
        pids = {response["pid"] for response in responses}
        assert len(pids) <= 2
        print("four-job pool: used {} Electron PIDs {}".format(len(pids), sorted(pids)))
    finally:
        pool.shutdown()


if __name__ == "__main__":
    main()
