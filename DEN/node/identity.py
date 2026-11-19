"""Persistent node identity and exclusive data-directory ownership."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import TextIO

if os.name != "nt":
    import fcntl


class NodeIdentity:
    def __init__(self, node_id: str, lock_file: TextIO) -> None:
        self.node_id = node_id
        self._lock_file = lock_file

    @classmethod
    def open(cls, data_dir: Path) -> NodeIdentity:
        data_dir.mkdir(parents=True, exist_ok=True)
        lock_file = (data_dir / ".node.lock").open("a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                if not lock_file.read(1):
                    lock_file.seek(0)
                    lock_file.write("\0")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            lock_file.close()
            raise RuntimeError(f"data directory is already in use: {data_dir}") from exc

        identity_path = data_dir / "node-id"
        try:
            if identity_path.exists():
                node_id = identity_path.read_text(encoding="utf-8").strip()
                uuid.UUID(node_id)
            else:
                node_id = str(uuid.uuid4())
                identity_path.write_text(f"{node_id}\n", encoding="utf-8")
            return cls(node_id, lock_file)
        except (OSError, ValueError) as exc:
            lock_file.close()
            raise RuntimeError(f"cannot load or create node identity at {identity_path}: {exc}") from exc

    def close(self) -> None:
        if not self._lock_file.closed:
            if os.name == "nt":
                import msvcrt

                self._lock_file.seek(0)
                msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            self._lock_file.close()