import tempfile
from pathlib import Path
from unittest.mock import Mock
from alerts import HealthAlerts


def test_alerts():
    with tempfile.TemporaryDirectory() as directory:
        cfg = {"notify": {"stateFile": str(Path(directory) / "state.json")}}
        sender = Mock(return_value=True)
        clock = Mock(return_value=0)
        monitor = HealthAlerts(cfg, sender, clock)
        monitor.observe("auth")
        monitor.observe("healthy")
        monitor.observe("auth")
        monitor.observe("auth")
        assert sender.call_count == 0
        monitor.observe("auth")
        assert sender.call_count == 1
        for _ in range(20):
            monitor.observe("auth")
        assert sender.call_count == 1
        monitor = HealthAlerts(cfg, sender, clock)
        for _ in range(3):
            monitor.observe("auth")
        assert sender.call_count == 1
        for _ in range(3):
            monitor.observe("healthy")
        assert sender.call_count == 2
        sender.return_value = False
        clock.return_value = 301
        for _ in range(3):
            monitor.observe("unavailable")
        assert sender.call_count == 3
        monitor.observe("unavailable")
        assert sender.call_count == 3
        sender.return_value = True
        clock.return_value = 602
        monitor.observe("unavailable")
        assert sender.call_count == 4
        assert monitor.announced == "unavailable"
    print("Alert tests passed: debounce, dedup across restart, recovery, failed-send retry")


if __name__ == "__main__":
    test_alerts()
