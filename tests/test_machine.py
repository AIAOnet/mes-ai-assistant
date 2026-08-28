import unittest

from machine import MachineSimulator, MachineState, PLCSimulator


class MachineSimulatorTests(unittest.TestCase):
    def test_running_values_change_gradually(self) -> None:
        machine = MachineSimulator(random_seed=7)
        original = (machine.pressure, machine.temperature, machine.rpm)

        machine.tick()

        self.assertLessEqual(abs(machine.pressure - original[0]), 1.5)
        self.assertLessEqual(abs(machine.temperature - original[1]), 0.5)
        self.assertLessEqual(abs(machine.rpm - original[2]), 30)

    def test_production_increases_only_while_running(self) -> None:
        machine = MachineSimulator(random_seed=7)
        for _ in range(5):
            machine.tick()
        self.assertEqual(machine.production_count, 1)

        machine.stop()
        for _ in range(10):
            machine.tick()
        self.assertEqual(machine.production_count, 1)

    def test_pressure_fault_rises_gradually(self) -> None:
        machine = MachineSimulator(random_seed=7)
        machine.raise_pressure()
        previous = machine.pressure

        machine.tick()

        self.assertGreater(machine.pressure, previous)
        self.assertLess(machine.pressure - previous, 6)

    def test_reset_restores_normal_conditions(self) -> None:
        machine = MachineSimulator(random_seed=7)
        machine.raise_pressure()
        machine.raise_temperature()
        machine.stop()

        machine.reset()

        self.assertEqual(machine.state, MachineState.RUNNING)
        self.assertEqual(machine.pressure, 70.0)
        self.assertEqual(machine.temperature, 55.0)
        self.assertEqual(machine.rpm, 1400)


class PLCSimulatorTests(unittest.TestCase):
    def test_scan_exposes_industrial_style_tags(self) -> None:
        machine = MachineSimulator(random_seed=7)
        plc = PLCSimulator(machine)

        tags = plc.scan()

        self.assertEqual(tags["Machine01.Pressure"], machine.pressure)
        self.assertEqual(tags["Machine01.Status"], "RUNNING")
        self.assertIn("Machine01.ProductionCount", tags)
        self.assertFalse(tags["Machine01.AlarmState"])


if __name__ == "__main__":
    unittest.main()
