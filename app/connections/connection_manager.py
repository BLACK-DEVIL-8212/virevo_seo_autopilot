"""Connection manager - abstracts FTP/SFTP/SSH/Public URL modes."""
from __future__ import annotations
import io
import os
import traceback
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from ..utils import is_js_verification_page

from ..security.encryption import encrypt, decrypt


@dataclass
class ConnectionTestResult:
    ok: bool
    message: str
    website_root_candidates: List[str]
    access_capability: str  # analysis_only | read | read_write
    technology_hint: str = "unknown"
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FTPResult:
    ok: bool
    operation: str
    error_type: str = ""
    error_message: str = ""
    traceback: str = ""
    host: str = ""
    port: int = 21
    username: str = ""
    remote_path: str = ""
    local_path: str = ""
    remote_directory: str = ""
    ftp_command: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "operation": self.operation,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "traceback": self.traceback,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "remote_path": self.remote_path,
            "local_path": self.local_path,
            "remote_directory": self.remote_directory,
            "ftp_command": self.ftp_command,
            "extra": self.extra,
        }


class PublicUrlAccess:
    """Pure public URL mode - HTTP requests only."""

    def __init__(self, root_url: str):
        self.root_url = root_url.rstrip("/")

    def fetch(self, url: str, timeout: int = 15) -> tuple[int, str, str]:
        import requests
        try:
            r = requests.get(
                url, timeout=timeout, allow_redirects=True,
                headers={"User-Agent": "AI-SEO-Autopilot/1.0"},
            )
            html = r.text or ""
            challenge = is_js_verification_page(
                html=html,
                headers=dict(r.headers),
                cookies=dict(r.cookies),
                final_url=r.url,
            )
            if challenge.get("is_challenge"):
                # Preserve the real HTTP status code instead of masking it as 0.
                # The caller can check for challenge details separately.
                return r.status_code, html, r.url
            return r.status_code, html, r.url
        except Exception as e:
            return 0, f"Fetch error: {e}", url

    def head(self, url: str, timeout: int = 10) -> dict:
        import requests
        try:
            r = requests.head(url, timeout=timeout, allow_redirects=True)
            return {"status_code": r.status_code, "headers": dict(r.headers)}
        except Exception as e:
            return {"status_code": 0, "error": str(e)}


class FTPConnection:
    """Simple FTP using ftplib."""

    def __init__(self, host, port, username, password, root):
        import ftplib
        self.host = host
        self.port = int(port or 21)
        self.username = username
        self.password = password
        self.root = (root or "/").rstrip("/") or "/"
        self._conn: Optional[ftplib.FTP] = None

    def connect(self) -> ConnectionTestResult:
        import ftplib
        try:
            self._conn = ftplib.FTP()
            self._conn.connect(self.host, self.port, timeout=15)
            self._conn.login(self.username, self.password)
            cwd = ""
            try:
                cwd = self._conn.pwd()
            except Exception:
                pass
            return ConnectionTestResult(
                True, "FTP login successful", [self.root], "read_write",
                details={"current_working_directory": cwd, "host": self.host, "port": self.port},
            )
        except Exception as e:
            tb = traceback.format_exc()
            return ConnectionTestResult(
                False, f"FTP error: {e}", [], "analysis_only",
                details={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "traceback": tb,
                    "host": self.host,
                    "port": self.port,
                    "username": self.username,
                },
            )

    def _result(self, ok: bool, operation: str, error: Optional[Exception] = None,
                remote_path: str = "", local_path: str = "", ftp_command: str = "", extra: Dict[str, Any] = None) -> FTPResult:
        if error:
            return FTPResult(
                ok=False, operation=operation,
                error_type=type(error).__name__,
                error_message=str(error),
                traceback=traceback.format_exc(),
                host=self.host, port=self.port, username=self.username,
                remote_path=remote_path, local_path=local_path,
                remote_directory=self.root, ftp_command=ftp_command,
                extra=extra or {},
            )
        return FTPResult(
            ok=True, operation=operation,
            host=self.host, port=self.port, username=self.username,
            remote_path=remote_path, local_path=local_path,
            remote_directory=self.root, ftp_command=ftp_command,
            extra=extra or {},
        )

    def listdir(self, path: str) -> List[str]:
        if not self._conn:
            raise RuntimeError("FTP not connected")
        try:
            self._conn.cwd(path)
            items: list[str] = []
            self._conn.retrlines("LIST", items.append)
            return items
        except Exception:
            raise

    def download(self, remote_path: str) -> Optional[bytes]:
        if not self._conn:
            return None
        try:
            buf = io.BytesIO()
            self._conn.retrbinary(f"RETR {remote_path}", buf.write)
            return buf.getvalue()
        except Exception:
            return None

    def upload(self, remote_path: str, data: bytes) -> FTPResult:
        if not self._conn:
            return self._result(False, "upload", error=RuntimeError("FTP not connected"),
                                remote_path=remote_path, ftp_command="STOR")
        try:
            target = remote_path
            if self.root and not remote_path.startswith(self.root):
                target = "/".join([self.root.rstrip("/"), remote_path.lstrip("/")])
            target = target.replace("\\", "/")
            buf = io.BytesIO(data)
            self._conn.storbinary(f"STOR {target}", buf)
            return self._result(True, "upload", remote_path=target, ftp_command=f"STOR {target}")
        except Exception as e:
            return self._result(False, "upload", error=e, remote_path=remote_path,
                                ftp_command=f"STOR {remote_path}")

    def close(self):
        if self._conn:
            try:
                self._conn.quit()
            except Exception:
                pass
            self._conn = None


class SFTPConnection:
    """SFTP using paramiko."""

    def __init__(self, host, port, username, password, private_key, root):
        self.host = host
        self.port = int(port or 22)
        self.username = username
        self.password = password
        self.private_key = private_key
        self.root = (root or "/").rstrip("/") or "/"
        self._client = None
        self._sftp = None

    def connect(self) -> ConnectionTestResult:
        import paramiko
        try:
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            pkey = None
            if self.private_key:
                try:
                    pkey = paramiko.RSAKey.from_private_key(io.StringIO(self.private_key))
                except Exception:
                    try:
                        pkey = paramiko.Ed25519Key.from_private_key(io.StringIO(self.private_key))
                    except Exception:
                        pkey = None
            self._client.connect(
                self.host, port=self.port, username=self.username,
                password=self.password or None, pkey=pkey, timeout=15,
                look_for_keys=False, allow_agent=False,
            )
            self._sftp = self._client.open_sftp()
            cwd = ""
            try:
                cwd = self._sftp.getcwd() or ""
            except Exception:
                pass
            return ConnectionTestResult(
                True, "SFTP connection successful", [self.root], "read_write",
                details={"current_working_directory": cwd, "host": self.host, "port": self.port},
            )
        except Exception as e:
            tb = traceback.format_exc()
            return ConnectionTestResult(
                False, f"SFTP error: {e}", [], "analysis_only",
                details={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "traceback": tb,
                    "host": self.host,
                    "port": self.port,
                    "username": self.username,
                },
            )

    def _result(self, ok: bool, operation: str, error: Optional[Exception] = None,
                remote_path: str = "", local_path: str = "", ftp_command: str = "", extra: Dict[str, Any] = None) -> FTPResult:
        if error:
            return FTPResult(
                ok=False, operation=operation,
                error_type=type(error).__name__,
                error_message=str(error),
                traceback=traceback.format_exc(),
                host=self.host, port=self.port, username=self.username,
                remote_path=remote_path, local_path=local_path,
                remote_directory=self.root, ftp_command=ftp_command,
                extra=extra or {},
            )
        return FTPResult(
            ok=True, operation=operation,
            host=self.host, port=self.port, username=self.username,
            remote_path=remote_path, local_path=local_path,
            remote_directory=self.root, ftp_command=ftp_command,
            extra=extra or {},
        )

    def listdir(self, path: str) -> List[str]:
        if not self._sftp:
            raise RuntimeError("SFTP not connected")
        try:
            return self._sftp.listdir(path)
        except Exception:
            raise

    def download(self, remote_path: str) -> Optional[bytes]:
        if not self._sftp:
            return None
        try:
            buf = io.BytesIO()
            with self._sftp.open(remote_path, "rb") as f:
                buf.write(f.read())
            return buf.getvalue()
        except Exception:
            return None

    def upload(self, remote_path: str, data: bytes) -> FTPResult:
        if not self._sftp:
            return self._result(False, "upload", error=RuntimeError("SFTP not connected"),
                                remote_path=remote_path, ftp_command="open/write")
        try:
            target = remote_path
            if self.root and not remote_path.startswith(self.root):
                target = "/".join([self.root.rstrip("/"), remote_path.lstrip("/")])
            target = target.replace("\\", "/")
            with self._sftp.open(target, "wb") as f:
                f.write(data)
            return self._result(True, "upload", remote_path=target, ftp_command=f"open/write {target}")
        except Exception as e:
            return self._result(False, "upload", error=e, remote_path=remote_path,
                                ftp_command=f"open/write {remote_path}")

    def close(self):
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
            self._sftp = None
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


class SSHConnection:
    """SSH using paramiko for command execution (optional)."""

    def __init__(self, host, port, username, password, private_key):
        self.host = host
        self.port = int(port or 22)
        self.username = username
        self.password = password
        self.private_key = private_key
        self._client = None

    def connect(self) -> ConnectionTestResult:
        import paramiko
        try:
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            pkey = None
            if self.private_key:
                try:
                    pkey = paramiko.RSAKey.from_private_key(io.StringIO(self.private_key))
                except Exception:
                    try:
                        pkey = paramiko.Ed25519Key.from_private_key(io.StringIO(self.private_key))
                    except Exception:
                        pkey = None
            self._client.connect(
                self.host, port=self.port, username=self.username,
                password=self.password or None, pkey=pkey, timeout=15,
                look_for_keys=False, allow_agent=False,
            )
            return ConnectionTestResult(True, "SSH connection successful", [], "read_write")
        except Exception as e:
            return ConnectionTestResult(False, f"SSH error: {e}", [], "analysis_only")

    def run(self, command: str, timeout: int = 30) -> tuple[int, str, str]:
        if not self._client:
            return (1, "", "Not connected")
        try:
            stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
            return (stdout.channel.recv_exit_status(), stdout.read().decode("utf-8", "ignore"),
                    stderr.read().decode("utf-8", "ignore"))
        except Exception as e:
            return (1, "", str(e))

    def close(self):
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


def build_connection_from_ids(website_id: int, root_url: str, connection_type: str,
                              website_root_path: str = "",
                              connection_host: str = "", connection_port: int = 21,
                              connection_username: str = "", connection_password: str = "",
                              connection_private_key: str = "") -> object:
    """Build a connection object from primitive values instead of ORM instances."""
    ctype = connection_type or "public_url"
    if ctype == "public_url":
        return PublicUrlAccess(root_url)
    if not connection_host:
        return PublicUrlAccess(root_url)
    password = decrypt(connection_password) if connection_password else ""
    pkey = decrypt(connection_private_key) if connection_private_key else ""
    if ctype == "ftp":
        return FTPConnection(connection_host, connection_port, connection_username, password, website_root_path)
    if ctype == "sftp":
        return SFTPConnection(connection_host, connection_port, connection_username, password, pkey, website_root_path)
    if ctype == "ssh":
        return SSHConnection(connection_host, connection_port, connection_username, password, pkey)
    return PublicUrlAccess(root_url)


def build_connection_from_website(website) -> object:
    """Build a connection object from a Website + Connection row."""
    conn = website.connections[0] if website.connections else None
    ctype = website.connection_type
    if ctype == "public_url":
        return PublicUrlAccess(website.root_url)
    if not conn:
        return PublicUrlAccess(website.root_url)
    password = decrypt(conn.password_encrypted) if conn.password_encrypted else ""
    pkey = decrypt(conn.private_key_encrypted) if conn.private_key_encrypted else ""
    if ctype == "ftp":
        return FTPConnection(conn.host, conn.port, conn.username, password, website.website_root_path)
    if ctype == "sftp":
        return SFTPConnection(conn.host, conn.port, conn.username, password, pkey, website.website_root_path)
    if ctype == "ssh":
        return SSHConnection(conn.host, conn.port, conn.username, password, pkey)
    return PublicUrlAccess(website.root_url)
    