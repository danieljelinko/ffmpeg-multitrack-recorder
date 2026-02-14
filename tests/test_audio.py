"""E2E tests for audio-only multitrack recording.

Uses synthetic audio (Web Audio API OscillatorNode) injected via inject_audio.js
to simulate real participants with distinguishable tones (440Hz, 880Hz, 660Hz).
"""

import asyncio, uuid
from pathlib import Path

import pytest

from helpers import (
    create_participant, close_participant, complete_recording,
    wait_for_recording_active, wait_for_recording_stopped,
    find_latest_recording, find_mka_file, count_audio_tracks,
    has_audio_content,
)

pytestmark = pytest.mark.asyncio


def _room(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class TestBasicRecording:
    """Auto-recording starts, MKA + metadata are created."""

    async def test_recording_pipeline(self, browser, jitsi_url, controller_url, recordings_dir):
        """Two participants join -> auto-recording starts -> recording directory, MKA, and metadata produced."""
        room = _room("test-audio-basic")
        rec_dir = await complete_recording(
            browser, jitsi_url, controller_url, recordings_dir, room,
            [("Alice", 440), ("Bob", 880)],
        )
        mka = find_mka_file(rec_dir)
        assert mka is not None, f"No MKA file in {rec_dir}"
        assert mka.stat().st_size > 0, "MKA file is empty"
        assert (rec_dir / "metadata.json").exists(), "metadata.json not found"

    async def test_two_participant_track_count(self, browser, jitsi_url, controller_url, recordings_dir):
        """MKA has exactly 2 audio tracks (requires real audio)."""
        room = _room("test-audio-tracks")
        rec_dir = await complete_recording(
            browser, jitsi_url, controller_url, recordings_dir, room,
            [("Alice", 440), ("Bob", 880)],
        )
        mka = find_mka_file(rec_dir)
        assert mka is not None
        assert count_audio_tracks(mka) == 2, f"Expected 2, got {count_audio_tracks(mka)}"


class TestAutoStartThreshold:
    """Auto-recording respects MIN_PARTICIPANTS threshold."""

    async def test_single_participant_no_recording(self, browser, jitsi_url, controller_url):
        """One participant below MIN_PARTICIPANTS should NOT trigger recording."""
        room = _room("test-threshold")
        alice = await create_participant(browser, jitsi_url, room, "Alice", freq=440)

        try:
            # Wait longer than POLL_INTERVAL (default 5s)
            await asyncio.sleep(10)
            import httpx
            async with httpx.AsyncClient(verify=False) as client:
                r = await client.get(f"{controller_url}/health", timeout=5)
                data = r.json()
            assert data["auto_recording"]["active_recordings"] == 0, \
                "Recording started with only 1 participant"

            # Second participant joins -> recording should start
            bob = await create_participant(browser, jitsi_url, room, "Bob", freq=880)
            try:
                await wait_for_recording_active(controller_url, timeout=60)
            finally:
                await close_participant(bob)
        finally:
            await close_participant(alice)

        await wait_for_recording_stopped(controller_url, timeout=60)


class TestLateJoin:
    """Third participant joining mid-recording."""

    async def test_late_join_recording_continues(self, browser, jitsi_url, controller_url, recordings_dir):
        """A third participant joining mid-recording does not break the recording."""
        room = _room("test-latejoin")
        alice = await create_participant(browser, jitsi_url, room, "Alice", freq=440)
        bob = await create_participant(browser, jitsi_url, room, "Bob", freq=880)

        try:
            await wait_for_recording_active(controller_url, timeout=60)
            await asyncio.sleep(5)

            charlie = await create_participant(browser, jitsi_url, room, "Charlie", freq=660)
            try:
                await asyncio.sleep(5)
            finally:
                await close_participant(charlie)
        finally:
            await close_participant(alice)
            await close_participant(bob)

        await wait_for_recording_stopped(controller_url, timeout=60)
        await asyncio.sleep(5)

        rec_dir = find_latest_recording(recordings_dir)
        assert rec_dir is not None
        mka = find_mka_file(rec_dir)
        assert mka is not None

    async def test_late_join_adds_track(self, browser, jitsi_url, controller_url, recordings_dir):
        """Third participant adds a 3rd audio track (requires real audio)."""
        room = _room("test-latejoin-trk")
        alice = await create_participant(browser, jitsi_url, room, "Alice", freq=440)
        bob = await create_participant(browser, jitsi_url, room, "Bob", freq=880)

        try:
            await wait_for_recording_active(controller_url, timeout=60)
            await asyncio.sleep(5)
            charlie = await create_participant(browser, jitsi_url, room, "Charlie", freq=660)
            try:
                await asyncio.sleep(5)
            finally:
                await close_participant(charlie)
        finally:
            await close_participant(alice)
            await close_participant(bob)

        await wait_for_recording_stopped(controller_url, timeout=60)
        await asyncio.sleep(5)
        rec_dir = find_latest_recording(recordings_dir)
        mka = find_mka_file(rec_dir)
        assert count_audio_tracks(mka) == 3


class TestEarlyLeave:
    """Participant who leaves early is captured in metadata."""

    async def test_early_leaver_in_metadata(self, browser, jitsi_url, controller_url, recordings_dir):
        """A participant who leaves early still appears in accumulated metadata snapshot."""
        room = _room("test-earlyleave")
        alice = await create_participant(browser, jitsi_url, room, "Alice", freq=440)
        bob = await create_participant(browser, jitsi_url, room, "Bob", freq=880)
        charlie = await create_participant(browser, jitsi_url, room, "Charlie", freq=660)

        try:
            await wait_for_recording_active(controller_url, timeout=60)
            await asyncio.sleep(5)
            # Charlie leaves early
            await close_participant(charlie)
            await asyncio.sleep(5)
        finally:
            await close_participant(alice)
            await close_participant(bob)

        await wait_for_recording_stopped(controller_url, timeout=60)
        await asyncio.sleep(5)

        rec_dir = find_latest_recording(recordings_dir)
        assert rec_dir is not None
        from helpers import read_metadata
        meta = read_metadata(rec_dir)
        participants = meta.get("participants", {})
        # Accumulated snapshot should have 3 participants (including early leaver)
        assert len(participants) >= 3, \
            f"Expected >=3 participants in metadata (including early leaver), got {len(participants)}: {participants}"
