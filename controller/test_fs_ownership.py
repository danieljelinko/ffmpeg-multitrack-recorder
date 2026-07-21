"""Unit tests for fs_ownership.chown_tree_to_host.

Real temp filesystem tree; only os.chown (the privileged OS boundary) is mocked,
so the tests run without root and without touching real ownership.
"""
from pathlib import Path
from typing import Callable

import pytest

from fs_ownership import chown_tree_to_host


@pytest.fixture
def make_rec_tree(tmp_path: Path) -> Callable[..., Path]:
    "Factory: build a recording-like dir tree and return its root path."
    def _build() -> Path:
        root = tmp_path / "260721_070601_room_uuid"
        (root / "sub").mkdir(parents=True)
        (root / "recording.mka").write_bytes(b"mka")
        (root / "metadata.json").write_text("{}")
        (root / "sub" / "nested.txt").write_text("x")
        return root
    return _build


@pytest.fixture
def record_chown(monkeypatch) -> list[tuple[str, int, int]]:
    "Patch os.chown to record (path, uid, gid) calls instead of touching real ownership."
    calls: list[tuple[str, int, int]] = []
    monkeypatch.setattr("os.chown", lambda p, u, g: calls.append((str(p), u, g)))
    return calls


def test_chown_tree_to_host_chowns_every_path_when_root_and_ids_set(make_rec_tree, record_chown):
    # Given a finished recording tree (dir + files + a subdir) and a root caller with ids set
    root = make_rec_tree()

    # When we chown the tree to the host user
    n = chown_tree_to_host(root, uid=1000, gid=1000, is_root=True)

    # Then every path is chowned to 1000:1000 and the returned count matches
    chowned = {p for p, u, g in record_chown if (u, g) == (1000, 1000)}
    expected = {str(root), str(root / "recording.mka"), str(root / "metadata.json"),
                str(root / "sub"), str(root / "sub" / "nested.txt")}
    assert chowned == expected
    assert n == len(expected)


def test_chown_tree_to_host_is_noop_when_not_root(make_rec_tree, record_chown):
    # Given a recording tree but a non-root caller
    root = make_rec_tree()

    # When we attempt the chown
    n = chown_tree_to_host(root, uid=1000, gid=1000, is_root=False)

    # Then nothing is chowned and the count is zero
    assert n == 0
    assert record_chown == []


def test_chown_tree_to_host_is_noop_when_uid_unset(make_rec_tree, record_chown):
    # Given a root caller but HOST_UID unset
    root = make_rec_tree()

    # When we attempt the chown
    n = chown_tree_to_host(root, uid=None, gid=1000, is_root=True)

    # Then nothing is chowned and the count is zero
    assert n == 0
    assert record_chown == []


def test_chown_tree_to_host_is_idempotent_when_run_twice(make_rec_tree, record_chown):
    # Given a recording tree already chowned once
    root = make_rec_tree()
    chown_tree_to_host(root, uid=1000, gid=1000, is_root=True)
    first = {p for p, u, g in record_chown}
    record_chown.clear()

    # When we chown the same tree again
    n = chown_tree_to_host(root, uid=1000, gid=1000, is_root=True)

    # Then it re-chowns the same set of paths without error (safe to repeat)
    assert {p for p, u, g in record_chown} == first
    assert n == len(first)
