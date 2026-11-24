import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from harnessspec.energy import (EnergyMeter, Integrator, counter_delta, nvidia_power,
                                power_joules, rapl_counters, summarize_energy)
from harnessspec.results import result_key
from test_results import row


class EnergyTests(unittest.TestCase):
    def test_counter_wrap_and_invalid_values(self):
        self.assertEqual(counter_delta(95, 5, 100), 10)
        self.assertEqual(counter_delta(5, 15, 100), 10)
        self.assertEqual(counter_delta(5, 5, 100), 0)
        with self.assertRaises(ValueError):
            counter_delta(0, 100, 100)

    def test_package_only_and_no_overlap(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, label in (("intel-rapl:0", "package-0"), ("intel-rapl:1", "package-1"),
                                ("intel-rapl:0:0", "core"), ("intel-rapl-mmio:0", "package-0")):
                target = root / name
                target.mkdir()
                (target / "name").write_text(label)
                (target / "max_energy_range_uj").write_text("500")
                (target / "energy_uj").write_text("25")
            method, counters = rapl_counters(root)
            self.assertEqual(method, "intel-rapl")
            self.assertEqual({k: v.read() for k, v in counters.items()}, {"package-0": 25, "package-1": 25})

    def test_unavailable_energy_is_null(self):
        with TemporaryDirectory() as directory, patch("harnessspec.energy.shutil.which", return_value=None):
            with EnergyMeter(Path(directory)) as meter:
                pass
        for device in ("cpu", "gpu"):
            self.assertEqual(meter.result[device]["status"], "unavailable")
            self.assertIsNone(meter.result[device]["joules"])
            self.assertIsNone(meter.result[device]["watt_hours"])

    def test_power_integration_and_sampling_failure(self):
        self.assertEqual(power_joules(10, 20, 2), 30)
        with self.assertRaises(ValueError):
            power_joules(math.nan, 20, 2)
        readings = iter([{"GPU-X": 10}, {"GPU-X": 20}, {"GPU-Y": 5}])
        times = iter([0, 0, 2, 2, 3, 3])
        channel = Integrator("nvidia-smi-power-trapezoid", lambda: next(readings),
                             lambda _, a, b, t: power_joules(a, b, t), lambda: next(times))
        channel.sample()
        channel.sample()
        self.assertEqual(channel.result()["status"], "estimated")
        self.assertEqual(channel.result()["joules"], 30)
        channel.sample()
        self.assertIsNone(channel.result()["joules"])

    def test_nvidia_unsupported_reading(self):
        with patch("harnessspec.energy.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "GPU-X, [N/A]\n"
            with self.assertRaisesRegex(ValueError, "unsupported power"):
                nvidia_power("nvidia-smi")

    def test_efficiency_uses_same_measured_subset(self):
        a = row(resolved=True)
        b = row(seed=2, resolved=True)
        c = row(seed=3, resolved=False)
        sample = {"cpu": {"status": "measured", "method": "rapl", "joules": 1800,
                          "scope": "device_wide", "device_joules": {"package-0": 1800}}}
        summary = summarize_energy([a, b, c], {result_key(a): sample, result_key(c): sample}, "sweqa")[0]
        self.assertEqual(summary["measured_runs"], 2)
        self.assertEqual(summary["watt_hours"], 1)
        self.assertEqual(summary["success_per_kwh"], 1000)
