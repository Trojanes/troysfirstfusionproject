"""Live nesting runtime profiler.

Writes ``nesting_runtime_profile.json`` next to this package so the user can
open the file while Fusion is still spinning and see which phase is stuck.
"""

from __future__ import annotations

import json
import os
import time


def _profile_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "nesting_runtime_profile.json")


class NestingProfiler:
    def __init__(self, action):
        self.action = str(action or "nesting")
        self.started = time.perf_counter()
        self.phases = {}
        self.counters = {}
        self.samples = []
        self.notes = []
        self._phase_starts = {}
        self.mark("started")

    def mark(self, label, **extra):
        self.notes.append({
            "tMs": int((time.perf_counter() - self.started) * 1000),
            "label": str(label),
            **extra,
        })
        self.flush(status=str(label))

    def begin(self, phase):
        self._phase_starts[str(phase)] = time.perf_counter()

    def end(self, phase):
        key = str(phase)
        started = self._phase_starts.pop(key, None)
        if started is None:
            return 0
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        self.phases[key] = int(self.phases.get(key, 0)) + elapsed_ms
        return elapsed_ms

    def add(self, counter, amount=1):
        key = str(counter)
        self.counters[key] = int(self.counters.get(key, 0)) + int(amount)

    def sample(self, label, elapsed_ms, **extra):
        self.samples.append({
            "label": str(label),
            "elapsedMs": int(elapsed_ms),
            **extra,
        })
        # Keep the file small; retain the slowest samples.
        self.samples.sort(key=lambda item: int(item.get("elapsedMs") or 0), reverse=True)
        self.samples = self.samples[:40]

    def snapshot(self, status="running"):
        return {
            "action": self.action,
            "status": status,
            "elapsedMs": int((time.perf_counter() - self.started) * 1000),
            "phasesMs": dict(self.phases),
            "counters": dict(self.counters),
            "slowestSamples": list(self.samples),
            "timeline": list(self.notes[-80:]),
            "path": _profile_path(),
        }

    def flush(self, status="running"):
        payload = self.snapshot(status=status)
        path = _profile_path()
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return payload
