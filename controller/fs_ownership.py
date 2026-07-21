"""Hand a finished recording directory back to the host user.

The recorder and controller run as root over the bind-mounted `recordings/`
volume, so every `recording.mka`/dir lands `root:root` and the host user can't
post-process, back up, or clean it. The controller (the last writer) calls this
to `chown` the final dir tree to `HOST_UID:HOST_GID`.

Kept free of the controller's heavy deps (slixmpp/aiortc) so it stays unit-testable.
"""
import os
from pathlib import Path


def chown_tree_to_host(root: Path,           # finished recording dir
                       uid: int | None,      # HOST_UID; None if unset
                       gid: int | None,      # HOST_GID; None if unset
                       is_root: bool) -> int:  # whether the caller runs as root
    "chown `root` and everything under it to `uid`:`gid`. No-op (returns 0) unless is_root and both ids set. Returns paths changed."
    if uid is None or gid is None or not is_root: return 0
    os.chown(root, uid, gid)
    n = 1
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            os.chown(os.path.join(dirpath, name), uid, gid)
            n += 1
    return n
