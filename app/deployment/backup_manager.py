"""Backup manager - downloads and stores file backups before any modification."""
from __future__ import annotations
import os
import hashlib
from datetime import datetime
from pathlib import Path

from ..config import Config
from ..database.database import new_session
from ..database.models import Backup, Website


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()


def create_backup(website_id: int, server_file: str, content: bytes,
                  change_id: str) -> Backup:
    """Persist a backup of `content` for `server_file` under website_id."""
    Config.BACKUP_DIR.mkdir(exist_ok=True)
    safe_name = server_file.replace("/", "_").replace("\\", "_").strip("_") or "file"
    fname = f"{change_id}_{safe_name}"
    local_path = Config.BACKUP_DIR / fname
    local_path.write_bytes(content or b"")

    sess = new_session()
    try:
        b = Backup(
            website_id=website_id,
            change_id=change_id,
            server_file=server_file,
            local_path=str(local_path),
            sha256_before=sha256_bytes(content),
            content_size=len(content or b""),
        )
        sess.add(b)
        sess.commit()
        sess.refresh(b)
        return b
    finally:
        sess.close()


def restore_backup(backup_id: int) -> tuple[bytes, str]:
    sess = new_session()
    try:
        b = sess.get(Backup, backup_id)
        if not b:
            return (b"", "")
        content = Path(b.local_path).read_bytes() if Path(b.local_path).exists() else b""
        return (content, b.server_file)
    finally:
        sess.close()


def list_backups(website_id: int) -> list:
    sess = new_session()
    try:
        return sess.query(Backup).filter_by(website_id=website_id).order_by(Backup.created_at.desc()).all()
    finally:
        sess.close()
    