"""Verify unattended launch and authentication-only mode without external requests."""
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from browser_worker import run_browser


def test_server_modes():
    with tempfile.TemporaryDirectory() as folder:
        state = Path(folder) / "storage-state.json"
        state.write_text('{"cookies": [], "origins": []}')
        cfg = {"browser": {"headless": True, "interactive": False,
                           "channel": "chromium", "profileDir": folder,
                           "storageStatePath": str(state)}}
        manager = MagicMock()
        pw = manager.return_value.__enter__.return_value
        context = pw.chromium.launch.return_value.new_context.return_value
        context.pages = [MagicMock()]
        context.pages[0].is_closed.return_value = True
        with patch.dict(os.environ, {"AVTOKLIKER_LOGIN": "0"}), \
                patch("playwright.sync_api.sync_playwright", manager), \
                patch("builtins.input", side_effect=AssertionError("Server must not prompt")):
            run_browser(cfg)
        pw.chromium.launch.assert_called_once_with(channel="chromium", headless=True)
        pw.chromium.launch.return_value.new_context.assert_called_once_with(storage_state=str(state))
        context.close.assert_called_once()

        login_context = pw.chromium.launch_persistent_context.return_value
        login_context.pages = [MagicMock()]
        with patch.dict(os.environ, {"AVTOKLIKER_LOGIN": "1", "AVTOKLIKER_EXPORT_STATE": str(state)}), \
                patch("playwright.sync_api.sync_playwright", manager), \
                patch("builtins.input", return_value=""), \
                patch("browser_worker.scan_page", side_effect=AssertionError("Login must not click")):
            run_browser(cfg)
        login_context.storage_state.assert_called_once_with(path=str(state), indexed_db=True)
        assert pw.chromium.launch_persistent_context.call_args.kwargs["headless"] is False
        print("Server tests passed: unattended headless launch, state import, login-only export")


if __name__ == "__main__":
    test_server_modes()
