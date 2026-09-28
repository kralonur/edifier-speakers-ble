"""HA button entity tests; require Home Assistant to be installed."""

import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock


class PlaybackButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_separate_play_and_pause_actions(self):
        try:
            module = importlib.import_module("custom_components.edifier_ble.button")
        except ModuleNotFoundError as exc:
            if exc.name == "homeassistant":
                self.skipTest("Home Assistant is not installed")
            raise
        for model in ("M60", "M90"):
            coordinator = SimpleNamespace(
                device=SimpleNamespace(model=model, firmware=None),
                async_playback_command=AsyncMock(),
                async_disruptive_command=AsyncMock(),
                async_link_command=AsyncMock(),
            )
            entry = SimpleNamespace(runtime_data=coordinator, unique_id="test-speaker")
            entities = []
            await module.async_setup_entry(None, entry, entities.extend)
            self.assertEqual([entity.name for entity in entities[:4]], ["Play", "Pause", "Next track", "Previous track"])
            self.assertEqual([entity.unique_id for entity in entities[:4]], [
                "test-speaker_play", "test-speaker_pause", "test-speaker_next", "test-speaker_previous"
            ])
            self.assertEqual(entities[4].name, "Power off speaker" if model == "M90" else "Disconnect Bluetooth audio")
            for index, action in enumerate(("play", "pause", "next", "previous")):
                await entities[index].async_press()
            self.assertEqual(
                [call.args[0] for call in coordinator.async_playback_command.await_args_list],
                ["play", "pause", "next", "previous"],
            )
            await entities[4].async_press()
            coordinator.async_disruptive_command.assert_awaited_with("power_off" if model == "M90" else "disconnect_audio")
            self.assertEqual([entity.name for entity in entities[5:]], ["Force connect", "Force disconnect"])
            self.assertEqual([entity.unique_id for entity in entities[5:]], ["test-speaker_link_connect", "test-speaker_link_disconnect"])
            coordinator.last_update_success = False
            self.assertTrue(entities[5].available, "link buttons must stay pressable while the speaker is unreachable")
            coordinator.last_update_success = True
            await entities[5].async_press()
            await entities[6].async_press()
            self.assertEqual([call.args[0] for call in coordinator.async_link_command.await_args_list], ["connect", "disconnect"])


if __name__ == "__main__":
    unittest.main()
