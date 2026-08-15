"""Consolidate the on-disk dir a recording landed in (audio MKA + composite video).

Audio and composite video are two independent pipelines. Both are told the same
meeting id, but the audio recorder's `selectDirectory` avoids collisions: if
`{id}/` already exists (the video recorder creates it to write `video.webm`), it
diverts the MKA to `{id}-1/`. So `recording.mka` and `video.webm` land in sibling
dirs. This resolves the pair to ONE dir (the one holding the MKA) and moves the
video in, so finalize operates on a single dir. Kept dep-free so it stays
unit-testable without the controller stack.
"""
import os
from pathlib import Path


def _has_mka(d: Path) -> bool: return bool(list(d.glob("*.mka")))


def consolidate_recording_dir(recordings_dir: Path,  # parent holding per-recording subdirs
                              dir_id: str) -> Path:   # id the audio recorder used for its dir
    "Return the single dir holding this recording; merge a split {id}/{id}-N pair, else fall back to the newest MKA dir, else create {id}."
    subdirs = [d for d in recordings_dir.iterdir() if d.is_dir()] if recordings_dir.exists() else []
    related = sorted([d for d in subdirs if d.name.startswith(dir_id)], key=lambda d: d.name)

    canonical = next((d for d in related if _has_mka(d)), None)  # the MKA dir among {dir_id}*
    if canonical is not None:
        for sib in related:                                      # pull video.webm (etc.) in
            if sib == canonical: continue
            _merge_dir_into(sib, canonical)
        return canonical

    newest_mka = sorted([d for d in subdirs if _has_mka(d)], key=lambda d: d.stat().st_mtime, reverse=True)
    if newest_mka: return newest_mka[0]  # audio-only Phase-1 fallback (no {dir_id}* MKA dir)
    if related:    return related[0]     # video-only (MKA not yet present)

    candidate = recordings_dir / dir_id
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _merge_dir_into(src: Path, dst: Path) -> None:
    "Move src's files into dst (skip name clashes), then remove src if it empties out."
    for f in src.iterdir():
        if f.is_file() and not (dst / f.name).exists():
            try: os.replace(f, dst / f.name)  # same filesystem; caller runs as root
            except OSError: pass
    try: src.rmdir()
    except OSError: pass
