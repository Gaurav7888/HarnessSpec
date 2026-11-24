"""Optional device-wide CPU package and NVIDIA GPU energy accounting."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
from threading import Event, Thread
import time
from typing import Callable

from harnessspec.results import result_key

POWER_CAP = Path("/sys/class/powercap")


def counter_delta(previous: int, current: int, maximum: int) -> int:
    """Delta in microjoules, assuming at most one wrap between readings."""
    if maximum <= 0 or not 0 <= previous < maximum or not 0 <= current < maximum:
        raise ValueError("RAPL counter outside its advertised range")
    return (current - previous) % maximum


def power_joules(previous_w: float, current_w: float, seconds: float) -> float:
    if not all(math.isfinite(value) and value >= 0 for value in (previous_w, current_w, seconds)):
        raise ValueError("invalid power reading or sample interval")
    return (previous_w + current_w) * seconds / 2


@dataclass(frozen=True)
class Counter:
    path: Path
    maximum: int

    def read(self) -> int:
        value = int(self.path.read_text(encoding="ascii"))
        if not 0 <= value < self.maximum:
            raise ValueError(f"{self.path}: counter outside its advertised range")
        return value


def rapl_counters(root: Path) -> tuple[str, dict[str, Counter]]:
    """Select one family of top-level package counters, skipping subdomains."""
    for family in ("intel-rapl", "amd-rapl", "intel-rapl-mmio"):
        counters = {}
        for path in sorted(root.glob(f"{family}:*")):
            if not re.fullmatch(re.escape(family) + r":\d+", path.name):
                continue
            name = (path / "name").read_text(encoding="ascii").strip()
            if not re.fullmatch(r"package-\d+", name):
                continue
            if name in counters:
                raise ValueError(f"duplicate RAPL package {name}")
            maximum = int((path / "max_energy_range_uj").read_text(encoding="ascii"))
            counters[name] = Counter(path / "energy_uj", maximum)
        if counters:
            return family, counters
    raise OSError(f"no RAPL package counters in {root}")


def nvidia_power(executable: str) -> dict[str, float]:
    """Sample device power in watts, keyed by NVIDIA GPU UUID."""
    completed = subprocess.run(
        [executable, "--query-gpu=uuid,power.draw", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=5, check=False,
    )
    if completed.returncode:
        raise OSError(completed.stderr.strip() or completed.stdout.strip() or "nvidia-smi failed")
    readings = {}
    for line in completed.stdout.splitlines():
        uuid, raw = (part.strip() for part in line.split(",", 1))
        if not uuid.startswith("GPU-") or uuid in readings:
            raise ValueError("invalid GPU inventory from nvidia-smi")
        try:
            watts = float(raw)
        except ValueError as error:
            raise ValueError(f"{uuid}: unsupported power reading {raw!r}") from error
        power_joules(watts, watts, 0)
        readings[uuid] = watts
    if not readings:
        raise OSError("nvidia-smi returned no GPU device readings")
    return readings


@dataclass
class Integrator:
    method: str
    read: Callable
    delta: Callable
    clock: Callable = time.monotonic
    previous: dict | None = None
    previous_time: float | None = None
    joules: dict = field(default_factory=dict)
    error: str | None = None
    samples: int = 0
    max_interval_s: float = 0.0

    def sample(self) -> None:
        if self.error is not None:
            return
        try:
            started = self.clock()
            values = self.read()
            now = (started + self.clock()) / 2
            if not values:
                raise ValueError("no device readings")
            if self.previous is None:
                self.joules = dict.fromkeys(values, 0.0)
            else:
                if values.keys() != self.previous.keys():
                    raise ValueError("device inventory changed during measurement")
                elapsed = now - self.previous_time
                self.max_interval_s = max(elapsed, self.max_interval_s)
                for name, value in values.items():
                    self.joules[name] += self.delta(name, self.previous[name], value, elapsed)
            self.previous, self.previous_time = values, now
            self.samples += 1
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            self.error = f"{type(error).__name__}: {error}"

    def result(self) -> dict:
        measured = self.error is None and self.samples >= 2
        joules = sum(self.joules.values()) if measured else None
        return {
            "status": ("estimated" if self.method == "nvidia-smi-power-trapezoid" else "measured")
            if measured else "unavailable",
            "method": self.method, "scope": "device_wide", "samples": self.samples,
            "max_sample_interval_s": self.max_interval_s if measured else None,
            "joules": joules, "watt_hours": joules / 3600 if measured else None,
            "device_joules": self.joules if measured else None,
            "reason": self.error if self.error is not None else (None if measured else "insufficient samples"),
        }


class EnergyMeter:
    """Measure local hardware during the enclosed interval using monotonic time."""

    def __init__(self, powercap: Path = POWER_CAP, interval_s: float = 1.0):
        if not math.isfinite(interval_s) or interval_s <= 0:
            raise ValueError("energy sample interval must be positive")
        self.powercap = powercap
        self.interval_s = interval_s
        self.stop = Event()
        self.channels = {}
        self.result = None

    def __enter__(self):
        try:
            family, counters = rapl_counters(self.powercap)
            self.channels["cpu"] = Integrator(
                f"{family}-package-counter",
                lambda: {name: counter.read() for name, counter in counters.items()},
                lambda name, before, after, _: counter_delta(before, after, counters[name].maximum) / 1e6,
            )
        except (OSError, ValueError) as error:
            self.channels["cpu"] = Integrator("rapl-package-counter", None, None, error=str(error))
        executable = shutil.which("nvidia-smi")
        self.channels["gpu"] = Integrator(
            "nvidia-smi-power-trapezoid", lambda: nvidia_power(executable),
            lambda _, before, after, seconds: power_joules(before, after, seconds),
            error=None if executable else "nvidia-smi not found",
        )
        # Arm the two sensors independently so subprocess latency cannot delay
        # measurement of another sensor throughout the run.
        self.started = time.monotonic()
        self.workers = []
        for channel in self.channels.values():
            channel.sample()
            if channel.error is None:
                worker = Thread(target=self._sample, args=(channel,), daemon=True)
                worker.start()
                self.workers.append(worker)
        return self

    def _sample(self, channel: Integrator) -> None:
        while not self.stop.wait(self.interval_s):
            channel.sample()
            if channel.error is not None:
                break

    def __exit__(self, *_exc) -> None:
        ended = time.monotonic()
        self.stop.set()
        for worker in self.workers:
            worker.join()
        for channel in self.channels.values():
            channel.sample()
        self.result = {
            "wall_clock_s": ended - self.started, "sample_period_s": self.interval_s,
            **{source: channel.result() for source, channel in self.channels.items()},
        }


def summarize_energy(rows: list[dict], energy: dict, benchmark: str) -> list[dict]:
    """Report efficiencies for measured runs, stratified by device inventory."""
    groups = defaultdict(list)
    attempted = defaultdict(int)
    for row in rows:
        if row["benchmark"] != benchmark:
            continue
        attempted[row["designer"]] += 1
        for source in ("cpu", "gpu"):
            sample = energy.get(result_key(row), {}).get(source, {})
            joules = sample.get("joules")
            if sample.get("status") not in {"measured", "estimated"}:
                continue
            if (type(joules) not in {int, float} or not math.isfinite(joules) or joules < 0
                    or not isinstance(sample.get("device_joules"), dict) or not sample["device_joules"]):
                raise ValueError(f"{result_key(row)}: invalid {source} energy measurement")
            inventory = tuple(sorted(sample["device_joules"]))
            group = (row["designer"], source, sample["method"], sample["scope"], inventory)
            groups[group].append((joules, row["resolved"]))
    output = []
    for (designer, source, method, scope, inventory), data in sorted(groups.items()):
        total = sum(joules for joules, _ in data)
        correct = sum(resolved for _, resolved in data)
        output.append({
            "designer": designer, "source": source, "method": method, "scope": scope,
            "devices": list(inventory), "attempted_runs": attempted[designer], "measured_runs": len(data),
            "resolved_measured_runs": correct, "joules": total, "watt_hours": total / 3600,
            "success_per_kwh": correct * 3.6e6 / total if total > 0 else None,
        })
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if not math.isfinite(args.probe_seconds) or args.probe_seconds <= 0:
        parser.error("--probe-seconds must be positive")
    with EnergyMeter() as meter:
        time.sleep(args.probe_seconds)
    print(json.dumps(meter.result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
