"""Run the Phase 1 simulation in a terminal."""

import time

from .plc import PLCSimulator
from .simulator import MachineSimulator


def main() -> None:
    machine = MachineSimulator()
    plc = PLCSimulator(machine)

    print("Phase 1 running. Press Ctrl+C to stop.\n")
    try:
        while True:
            machine.tick()
            tags = plc.scan()
            print(" | ".join(f"{name}={value}" for name, value in tags.items()))
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nSimulation stopped.")


if __name__ == "__main__":
    main()

