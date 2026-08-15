"""Unit tests for recording_dirs.consolidate_recording_dir.

Real temp filesystem; no mocks. Reproduces the audio/video dir-split bug: the
composite video recorder creates `{id}/` first, so the audio recorder's
collision-avoidance diverts the MKA to `{id}-1/`. Finalize must merge the pair
into one dir holding both `recording.mka` and `video.webm`.
"""
from pathlib import Path
from typing import Callable

import pytest

from recording_dirs import consolidate_recording_dir


@pytest.fixture
def make_recordings(tmp_path: Path) -> Callable[..., Path]:
    "Factory: build a recordings/ parent with named subdirs holding given files."
    def _build(dirs: dict[str, list[str]]) -> Path:
        root = tmp_path / "recordings"
        root.mkdir()
        for name, files in dirs.items():
            d = root / name
            d.mkdir()
            for f in files:
                (d / f).write_bytes(b"x")
        return root
    return _build


def test_consolidate_merges_video_into_mka_dir_when_recorder_split_them(make_recordings):
    # Given the split the recorder produces: video in {id}, MKA diverted to {id}-1
    rec_id = "30fee4aa-a442-43ad-abc2-da2aad5485ab"
    recordings = make_recordings({
        rec_id: ["video.webm"],
        f"{rec_id}-1": ["recording.mka"],
    })

    # When finalize consolidates the dir for the recorder id
    rec_dir = consolidate_recording_dir(recordings, rec_id)

    # Then one dir holds BOTH artifacts and the emptied video-only sibling is gone
    assert (rec_dir / "recording.mka").exists()
    assert (rec_dir / "video.webm").exists()
    assert not (recordings / rec_id).exists()


def test_consolidate_returns_unified_dir_when_audio_won_the_race(make_recordings):
    # Given audio claimed {id} first, so video wrote into the same dir (no split)
    rec_id = "abc-unified"
    recordings = make_recordings({rec_id: ["recording.mka", "video.webm"]})

    # When we consolidate
    rec_dir = consolidate_recording_dir(recordings, rec_id)

    # Then it is that single dir, untouched
    assert rec_dir == recordings / rec_id
    assert (rec_dir / "recording.mka").exists()
    assert (rec_dir / "video.webm").exists()


def test_consolidate_falls_back_to_mka_dir_when_id_dir_absent(make_recordings):
    # Given no dir named for the id, but one MKA-bearing dir exists (audio-only Phase-1 path)
    mka_dir_name = "abca796b-2222-3333-4444-555555555555"
    recordings = make_recordings({mka_dir_name: ["recording.mka"]})

    # When we resolve with an id that has no matching dir
    rec_dir = consolidate_recording_dir(recordings, "no-such-id")

    # Then the fallback picks the most-recent MKA-bearing dir
    assert rec_dir == recordings / mka_dir_name


def test_consolidate_creates_dir_when_nothing_matches(make_recordings):
    # Given an empty recordings/ parent
    recordings = make_recordings({})
    rec_id = "brand-new-id"

    # When we consolidate with an id that matches nothing
    rec_dir = consolidate_recording_dir(recordings, rec_id)

    # Then it creates and returns the id-named dir
    assert rec_dir == recordings / rec_id
    assert rec_dir.is_dir()
