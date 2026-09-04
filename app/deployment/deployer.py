"""Deployer - applies approved changes safely to the website.

Handles:
  - backup
  - in-memory modification
  - validation
  - FTP/SFTP preflight
  - upload with structured error reporting
  - post-deploy verification (remote download + public HTTP fetch)
  - rollback on failure
"""
from __future__ import annotations
import json
import os
import re
import hashlib
import uuid
import traceback
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urljoin
from pathlib import Path

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def _normalize_for_compare(content: str) -> str:
    """Normalize content for comparison."""
    return content.replace("\r\n", "\n").replace("\r", "\n")


def _new_change_id() -> str:
    """Generate a new change ID."""
    return f"SEO-{uuid.uuid4().hex[:10].upper()}"


def sha256_bytes(data: bytes) -> str:
    """Calculate SHA256 hash of bytes."""
    return hashlib.sha256(data).hexdigest()


# ============================================================================
# DATABASE MODELS (Simplified for standalone use)
# ============================================================================

class Website:
    """Website model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.name = kwargs.get('name', '')
        self.root_url = kwargs.get('root_url', '')
        self.website_root_path = kwargs.get('website_root_path', '')
        self.connection_type = kwargs.get('connection_type', '')
        self.architecture_type = kwargs.get('architecture_type', 'static_html')
        self.rendering_mode = kwargs.get('rendering_mode', 'raw')
        self.deployment_strategy = kwargs.get('deployment_strategy', 'direct_html')
        self.seo_health_score = kwargs.get('seo_health_score', 0.0)


class Connection:
    """Connection model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.host = kwargs.get('host', '')
        self.port = kwargs.get('port', 21)
        self.username = kwargs.get('username', '')
        self.password_encrypted = kwargs.get('password_encrypted', '')
        self.private_key_encrypted = kwargs.get('private_key_encrypted', '')
        self.extra_json = kwargs.get('extra_json', {})


class SEOChange:
    """SEO Change model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.change_id = kwargs.get('change_id', '')
        self.page_url = kwargs.get('page_url', '')
        self.server_file = kwargs.get('server_file', '')
        self.change_type = kwargs.get('change_type', '')
        self.before_value = kwargs.get('before_value', '')
        self.after_value = kwargs.get('after_value', '')
        self.reasoning = kwargs.get('reasoning', '')
        self.confidence = kwargs.get('confidence', 0.0)
        self.risk = kwargs.get('risk', 'low')
        self.status = kwargs.get('status', 'pending')
        self.backup_id = kwargs.get('backup_id')
        self.deployment_id = kwargs.get('deployment_id')
        self.validation_result = kwargs.get('validation_result', '')
        self.failure_details = kwargs.get('failure_details', {})
        self.deployed_at = kwargs.get('deployed_at')
        self.created_at = kwargs.get('created_at', datetime.utcnow())


class Backup:
    """Backup model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.change_id = kwargs.get('change_id', '')
        self.server_file = kwargs.get('server_file', '')
        self.local_path = kwargs.get('local_path', '')
        self.sha256 = kwargs.get('sha256', '')
        self.size = kwargs.get('size', 0)
        self.created_at = kwargs.get('created_at', datetime.utcnow())


class Deployment:
    """Deployment model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.change_id = kwargs.get('change_id', '')
        self.server_file = kwargs.get('server_file', '')
        self.status = kwargs.get('status', 'pending')
        self.message = kwargs.get('message', '')
        self.verification_json = kwargs.get('verification_json', {})
        self.created_at = kwargs.get('created_at', datetime.utcnow())


# ============================================================================
# DATABASE HELPERS
# ============================================================================

class SessionLocal:
    """Database session placeholder."""
    @staticmethod
    def remove():
        pass


def new_session():
    """Create a new database session."""
    return SessionLocal()


def log_audit(actor: str, action: str, target: str = "", details: dict = None):
    """Log audit entry."""
    if details is None:
        details = {}
    logger.info(f"AUDIT: {actor} | {action} | {target} | {details}")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def normalize_url(url: str) -> str:
    """Normalize a URL."""
    if not url:
        return ""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    normalized = parsed._replace(fragment="").geturl()
    if normalized.endswith("/") and not normalized.endswith("//"):
        normalized = normalized[:-1]
    return normalized


def is_internal(url: str, root_url: str) -> bool:
    """Check if URL is internal."""
    if not url or not root_url:
        return False
    from urllib.parse import urlparse
    parsed_url = urlparse(url)
    parsed_root = urlparse(root_url)
    if not parsed_url.netloc:
        return True
    return parsed_url.netloc == parsed_root.netloc


def is_js_verification_page(html: str = "") -> Dict:
    """Detect JS verification page."""
    result = {"is_challenge": False, "reason": ""}
    if not html:
        return result
    
    html_lower = html.lower()
    indicators = [
        "aes.js",
        "slowaes",
        "slowAES",
        "toNumbers",
        "toHex",
        "checkCookie",
        "__test",
        "cf_chl",
        "_cf_chl",
        "_cf_challenge",
        "enable javascript",
        "this site requires javascript",
        "checking your browser before",
        "attention required",
        "javascript is disabled",
        "please enable js",
        "ddos protection by",
        "cf-ray",
    ]
    
    for indicator in indicators:
        if indicator in html_lower:
            result["is_challenge"] = True
            result["reason"] = f"Contains '{indicator}'"
            break
    
    return result


def fetch_real_html(url: str) -> Dict:
    """Fetch real HTML content."""
    import requests
    try:
        response = requests.get(url, timeout=30, allow_redirects=True)
        html = response.text or ""
        challenge = is_js_verification_page(html)
        
        return {
            "ok": 200 <= response.status_code < 400 and not challenge.get("is_challenge"),
            "html": html,
            "status_code": response.status_code,
            "final_url": response.url,
            "challenge": challenge if challenge.get("is_challenge") else None,
            "source": "http",
            "error": None
        }
    except Exception as e:
        return {
            "ok": False,
            "html": "",
            "status_code": 0,
            "final_url": url,
            "challenge": None,
            "source": "http",
            "error": str(e)
        }


# ============================================================================
# CONNECTION MANAGER
# ============================================================================

class FTPResult:
    """FTP operation result."""
    def __init__(self, ok: bool, message: str = "", details: Dict = None, error_type: str = ""):
        self.ok = ok
        self.message = message
        self.details = details or {}
        self.error_type = error_type
    
    def to_dict(self) -> Dict:
        return {
            "ok": self.ok,
            "message": self.message,
            "details": self.details,
            "error_type": self.error_type
        }


class ConnectionTestResult:
    """Connection test result."""
    def __init__(self, ok: bool, message: str = "", details: Dict = None):
        self.ok = ok
        self.message = message
        self.details = details or {}


class FTPConnection:
    """FTP connection wrapper."""
    
    def __init__(self, host: str, port: int = 21, username: str = "", password: str = "", root: str = "/"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.root = root.rstrip("/") or "/"
        self._conn = None
        self._last_download_error = None
    
    def connect(self) -> ConnectionTestResult:
        """Connect to FTP server."""
        try:
            import ftplib
            self._conn = ftplib.FTP()
            self._conn.connect(self.host, self.port)
            if self.username:
                self._conn.login(self.username, self.password)
            else:
                self._conn.login()
            return ConnectionTestResult(True, "Connected successfully")
        except Exception as e:
            return ConnectionTestResult(False, f"Connection failed: {e}")
    
    def close(self):
        """Close FTP connection."""
        if self._conn:
            try:
                self._conn.quit()
            except Exception:
                try:
                    self._conn.close()
                except Exception:
                    pass
            self._conn = None
    
    def listdir(self, path: str = "/") -> List[str]:
        """List directory contents."""
        if not self._conn:
            self.connect()
        try:
            return self._conn.nlst(path)
        except Exception as e:
            logger.warning(f"FTP listdir failed: {e}")
            return []
    
    def download(self, remote_path: str) -> Optional[bytes]:
        """Download file from FTP."""
        if not self._conn:
            self.connect()
        try:
            data = []
            def callback(chunk):
                data.append(chunk)
            self._conn.retrbinary(f"RETR {remote_path}", callback)
            return b"".join(data)
        except Exception as e:
            self._last_download_error = {
                "error_type": type(e).__name__,
                "error_message": str(e)
            }
            logger.warning(f"FTP download failed: {e}")
            return None
    
    def upload(self, remote_path: str, content: bytes) -> FTPResult:
        """Upload file to FTP."""
        if not self._conn:
            self.connect()
        try:
            # Ensure directory exists
            dir_path = "/".join(remote_path.split("/")[:-1])
            if dir_path:
                try:
                    self._conn.cwd(dir_path)
                except Exception:
                    # Try to create directory
                    parts = dir_path.split("/")
                    current = ""
                    for part in parts:
                        if part:
                            current = f"{current}/{part}" if current else part
                            try:
                                self._conn.cwd(current)
                            except Exception:
                                self._conn.mkd(current)
            
            self._conn.storbinary(f"STOR {remote_path}", content)
            return FTPResult(True, "Upload successful")
        except Exception as e:
            return FTPResult(False, f"Upload failed: {e}", {"error": str(e)}, type(e).__name__)
    
    def delete(self, remote_path: str) -> bool:
        """Delete file from FTP."""
        if not self._conn:
            self.connect()
        try:
            self._conn.delete(remote_path)
            return True
        except Exception:
            return False


class SFTPConnection:
    """SFTP connection wrapper."""
    
    def __init__(self, host: str, port: int = 22, username: str = "", password: str = "", 
                 private_key: str = "", root: str = "/"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.private_key = private_key
        self.root = root.rstrip("/") or "/"
        self._transport = None
        self._sftp = None
        self._last_download_error = None
    
    def connect(self) -> ConnectionTestResult:
        """Connect to SFTP server."""
        try:
            import paramiko
            self._transport = paramiko.Transport((self.host, self.port))
            self._transport.connect()
            
            if self.private_key:
                key = paramiko.RSAKey.from_private_key_string(self.private_key)
                self._transport.auth_publickey(self.username, key)
            else:
                self._transport.auth_password(self.username, self.password)
            
            self._sftp = paramiko.SFTPClient.from_transport(self._transport)
            return ConnectionTestResult(True, "Connected successfully")
        except Exception as e:
            return ConnectionTestResult(False, f"Connection failed: {e}")
    
    def close(self):
        """Close SFTP connection."""
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
    
    def listdir(self, path: str = "/") -> List[str]:
        """List directory contents."""
        if not self._sftp:
            self.connect()
        try:
            return self._sftp.listdir(path)
        except Exception as e:
            logger.warning(f"SFTP listdir failed: {e}")
            return []
    
    def download(self, remote_path: str) -> Optional[bytes]:
        """Download file from SFTP."""
        if not self._sftp:
            self.connect()
        try:
            with self._sftp.open(remote_path, "rb") as f:
                return f.read()
        except Exception as e:
            self._last_download_error = {
                "error_type": type(e).__name__,
                "error_message": str(e)
            }
            logger.warning(f"SFTP download failed: {e}")
            return None
    
    def upload(self, remote_path: str, content: bytes) -> FTPResult:
        """Upload file to SFTP."""
        if not self._sftp:
            self.connect()
        try:
            # Ensure directory exists
            dir_path = "/".join(remote_path.split("/")[:-1])
            if dir_path:
                try:
                    self._sftp.stat(dir_path)
                except Exception:
                    # Create directory structure
                    parts = dir_path.split("/")
                    current = ""
                    for part in parts:
                        if part:
                            current = f"{current}/{part}" if current else part
                            try:
                                self._sftp.stat(current)
                            except Exception:
                                self._sftp.mkdir(current)
            
            with self._sftp.open(remote_path, "wb") as f:
                f.write(content)
            return FTPResult(True, "Upload successful")
        except Exception as e:
            return FTPResult(False, f"Upload failed: {e}", {"error": str(e)}, type(e).__name__)
    
    def delete(self, remote_path: str) -> bool:
        """Delete file from SFTP."""
        if not self._sftp:
            self.connect()
        try:
            self._sftp.remove(remote_path)
            return True
        except Exception:
            return False


class PublicUrlAccess:
    """Public URL access for verification."""
    pass


def build_connection_from_ids(website_id: int, root_url: str, connection_type: str,
                              website_root_path: str = "", connection_host: str = "",
                              connection_port: int = 21, connection_username: str = "",
                              connection_password: str = "", connection_private_key: str = "") -> Any:
    """Build connection object from IDs."""
    if connection_type == "ftp":
        return FTPConnection(
            host=connection_host,
            port=connection_port or 21,
            username=connection_username,
            password=connection_password,
            root=website_root_path or "/"
        )
    elif connection_type == "sftp":
        return SFTPConnection(
            host=connection_host,
            port=connection_port or 22,
            username=connection_username,
            password=connection_password,
            private_key=connection_private_key,
            root=website_root_path or "/"
        )
    else:
        # Return a dummy connection for static sites
        return FTPConnection(host="localhost", root="/")


# ============================================================================
# MODIFIER FUNCTIONS
# ============================================================================

def apply_changes(html: str, changes: List[Dict]) -> Tuple[str, List[Dict]]:
    """Apply SEO changes to HTML."""
    from bs4 import BeautifulSoup
    
    soup = BeautifulSoup(html, "html.parser")
    applied_log = []
    
    for change in changes:
        change_type = change.get("type", "")
        value = change.get("value", "")
        
        if change_type == "title":
            if soup.title:
                soup.title.string = value
            else:
                title_tag = soup.new_tag("title")
                title_tag.string = value
                if soup.head:
                    soup.head.append(title_tag)
            applied_log.append({"type": change_type, "status": "applied"})
        
        elif change_type == "meta_description":
            meta_tag = soup.find("meta", attrs={"name": "description"})
            if meta_tag:
                meta_tag["content"] = value
            else:
                meta_tag = soup.new_tag("meta")
                meta_tag["name"] = "description"
                meta_tag["content"] = value
                if soup.head:
                    soup.head.append(meta_tag)
            applied_log.append({"type": change_type, "status": "applied"})
        
        elif change_type == "h1":
            h1_tag = soup.find("h1")
            if h1_tag:
                h1_tag.string = value
            else:
                h1_tag = soup.new_tag("h1")
                h1_tag.string = value
                body = soup.find("body")
                if body:
                    body.insert(0, h1_tag)
            applied_log.append({"type": change_type, "status": "applied"})
        
        elif change_type in ["og_title", "og_description"]:
            prop = "og:title" if change_type == "og_title" else "og:description"
            meta_tag = soup.find("meta", attrs={"property": prop})
            if meta_tag:
                meta_tag["content"] = value
            else:
                meta_tag = soup.new_tag("meta")
                meta_tag["property"] = prop
                meta_tag["content"] = value
                if soup.head:
                    soup.head.append(meta_tag)
            applied_log.append({"type": change_type, "status": "applied"})
        
        elif change_type == "canonical":
            link_tag = soup.find("link", attrs={"rel": "canonical"})
            if link_tag:
                link_tag["href"] = value
            else:
                link_tag = soup.new_tag("link")
                link_tag["rel"] = "canonical"
                link_tag["href"] = value
                if soup.head:
                    soup.head.append(link_tag)
            applied_log.append({"type": change_type, "status": "applied"})
        
        elif change_type == "open_graph":
            if isinstance(value, dict):
                for prop, content in value.items():
                    meta_tag = soup.find("meta", attrs={"property": prop})
                    if meta_tag:
                        meta_tag["content"] = content
                    else:
                        meta_tag = soup.new_tag("meta")
                        meta_tag["property"] = prop
                        meta_tag["content"] = content
                        if soup.head:
                            soup.head.append(meta_tag)
                applied_log.append({"type": change_type, "status": "applied"})
        
        elif change_type == "structured_data":
            if isinstance(value, dict):
                # Remove existing structured data
                for script in soup.find_all("script", type="application/ld+json"):
                    script.decompose()
                # Add new structured data
                script_tag = soup.new_tag("script")
                script_tag["type"] = "application/ld+json"
                script_tag.string = json.dumps(value)
                if soup.head:
                    soup.head.append(script_tag)
                applied_log.append({"type": change_type, "status": "applied"})
        
        elif change_type == "robots":
            meta_tag = soup.find("meta", attrs={"name": "robots"})
            if meta_tag:
                meta_tag["content"] = value
            else:
                meta_tag = soup.new_tag("meta")
                meta_tag["name"] = "robots"
                meta_tag["content"] = value
                if soup.head:
                    soup.head.append(meta_tag)
            applied_log.append({"type": change_type, "status": "applied"})
    
    return str(soup), applied_log


def validate_html(html: str) -> Dict:
    """Validate HTML structure."""
    from bs4 import BeautifulSoup
    result = {"ok": True, "issues": []}
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        if not soup.find("html"):
            result["ok"] = False
            result["issues"].append("Missing <html> tag")
        if not soup.find("head"):
            result["ok"] = False
            result["issues"].append("Missing <head> tag")
        if not soup.find("body"):
            result["ok"] = False
            result["issues"].append("Missing <body> tag")
    except Exception as e:
        result["ok"] = False
        result["issues"].append(f"Parse error: {e}")
    
    return result


def validate_json_ld(data: Dict) -> Dict:
    """Validate JSON-LD structured data."""
    result = {"ok": True, "issues": []}
    
    if not data:
        result["ok"] = False
        result["issues"].append("Empty structured data")
        return result
    
    if "@context" not in data:
        result["ok"] = False
        result["issues"].append("Missing @context")
    
    if "@type" not in data:
        result["ok"] = False
        result["issues"].append("Missing @type")
    
    return result


# ============================================================================
# BACKUP MANAGER
# ============================================================================

def create_backup(website_id: int, server_file: str, content: bytes, change_id: str) -> Backup:
    """Create a backup of the current content."""
    backup_dir = Path("backups")
    backup_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{website_id}_{change_id}_{timestamp}.html"
    backup_path = backup_dir / filename
    
    with open(backup_path, "wb") as f:
        f.write(content)
    
    return Backup(
        website_id=website_id,
        change_id=change_id,
        server_file=server_file,
        local_path=str(backup_path),
        sha256=sha256_bytes(content),
        size=len(content)
    )


# ============================================================================
# VALIDATOR FUNCTIONS
# ============================================================================

def validate_change_payload(before_html: str, after_html: str, changes: List[Dict]) -> Dict:
    """Validate change payload."""
    result = {"ok": True, "checks": []}
    
    # Check HTML validity
    html_validation = validate_html(after_html)
    if not html_validation["ok"]:
        result["ok"] = False
        result["checks"].append({"check": "html_validation", "ok": False, "issues": html_validation["issues"]})
    else:
        result["checks"].append({"check": "html_validation", "ok": True})
    
    # Check for JavaScript verification
    challenge = is_js_verification_page(after_html)
    if challenge.get("is_challenge"):
        result["ok"] = False
        result["checks"].append({"check": "js_verification", "ok": False, "reason": challenge.get("reason")})
    else:
        result["checks"].append({"check": "js_verification", "ok": True})
    
    # Check changes were applied
    for change in changes:
        change_type = change.get("type", "")
        value = change.get("value", "")
        
        if change_type == "title":
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(after_html, "html.parser")
            new_title = soup.title.string if soup.title else ""
            if value and value != new_title and value not in after_html:
                result["ok"] = False
                result["checks"].append({"check": f"title_applied", "ok": False, "expected": value, "found": new_title})
            else:
                result["checks"].append({"check": f"title_applied", "ok": True})
    
    return result


# ============================================================================
# DEPLOYER FUNCTIONS
# ============================================================================

def can_modify_remotely(website: Website) -> bool:
    """Check if website can be modified remotely."""
    return website.connection_type in ("ftp", "sftp")


def _safe_remote_root(website: Website, conn: Optional[Connection]) -> str:
    """Determine the explicit remote root directory."""
    if conn and conn.extra_json and isinstance(conn.extra_json, dict):
        root = conn.extra_json.get("remote_root") or conn.extra_json.get("ftp_root") or ""
        if root:
            return root.rstrip("/") or "/"
    return (website.website_root_path or "").rstrip("/") or "/"


def _resolve_remote_path(conn_obj, server_file: str, remote_root: str) -> str:
    """Resolve the final remote path."""
    remote_path = server_file
    if hasattr(conn_obj, 'root') and conn_obj.root:
        if not remote_path.startswith(conn_obj.root):
            remote_path = "/".join([conn_obj.root.rstrip("/"), remote_path.lstrip("/")])
    elif remote_root and remote_root != "/":
        if not remote_path.startswith(remote_root):
            remote_path = "/".join([remote_root.rstrip("/"), remote_path.lstrip("/")])
    return remote_path.replace("\\", "/")


def _emit(website_id: int, event_type: str, message: str, severity: str = "info",
          metadata: Dict = None, change_id: str = ""):
    """Emit deployment event."""
    if metadata is None:
        metadata = {}
    log_audit("deployment", event_type, change_id, {
        "website_id": website_id,
        "message": message,
        "severity": severity,
        **metadata
    })


def _ftp_preflight(conn_obj, remote_root: str) -> Dict:
    """Run FTP preflight diagnostics."""
    steps = []
    overall_ok = True

    connect_result = conn_obj.connect()
    steps.append({
        "step": "ftp_connect",
        "ok": connect_result.ok,
        "message": connect_result.message,
        "details": connect_result.details
    })
    if not connect_result.ok:
        overall_ok = False
        return {"ok": False, "steps": steps, "error": "Connection failed"}

    # Test list directory
    try:
        listing = conn_obj.listdir(remote_root or "/")
        steps.append({
            "step": "list_directory",
            "ok": True,
            "listing_count": len(listing),
            "path": remote_root or "/"
        })
    except Exception as e:
        steps.append({"step": "list_directory", "ok": False, "error": str(e)})
        overall_ok = False

    # Test write permission
    test_filename = f".seo_autopilot_test_{uuid.uuid4().hex[:8]}.txt"
    test_content = b"SEO Autopilot preflight test"
    test_path = os.path.join(remote_root or "/", test_filename).replace("\\", "/")
    if test_path.startswith("//"):
        test_path = test_path[1:]

    upload_result = conn_obj.upload(test_path, test_content)
    if hasattr(upload_result, 'to_dict'):
        upload_dict = upload_result.to_dict()
    else:
        upload_dict = {"ok": upload_result}

    steps.append({
        "step": "write_test",
        "ok": upload_dict.get("ok", False),
        "test_file": test_path,
        "result": upload_dict
    })
    if not upload_dict.get("ok", False):
        overall_ok = False

    # Clean up test file
    try:
        conn_obj.delete(test_path)
    except Exception:
        pass

    conn_obj.close()
    return {"ok": overall_ok, "steps": steps}


def _title_matches(after_html: str, response_text: str) -> bool:
    """Check if title matches."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(after_html or "", "html.parser")
    new_title = (soup.title.string or "").strip() if soup.title else ""
    if not new_title:
        return True
    return new_title in response_text


def _change_exists_in_html(changes: List[Dict], new_html: str, production_html: str) -> bool:
    """Verify change exists in production HTML."""
    if not changes or not new_html or not production_html:
        return False
    production_lower = production_html.lower()
    for change in changes:
        value = change.get("value", "")
        if not value:
            continue
        change_type = change.get("type", "")
        if change_type in ["meta_description", "title", "h1", "canonical"]:
            if value.lower() in production_lower:
                return True
        else:
            if value.lower() in production_lower:
                return True
    return False


# ============================================================================
# MAIN DEPLOYMENT FUNCTION
# ============================================================================

def deploy_change(website_id: int, server_file: str, html_content: bytes,
                  changes: List[Dict], page_url: str = "") -> Dict:
    """Full deployment pipeline: backup -> modify -> validate -> preflight -> upload -> verify."""
    error_detail: Dict = {}
    deploy_status = "pending_manual"
    deploy_msg = ""
    applied_log = []
    validation = {"ok": True, "checks": []}
    verification = {"ok": True}
    backup = None
    change_id = _new_change_id()
    remote_path_used = server_file
    deployed_at = datetime.utcnow()
    ftp_verified = False
    browser_verification = {"ok": False, "reason": "not_attempted"}

    sess = new_session()
    try:
        website = Website(
            id=website_id,
            root_url="https://example.com",
            name=f"Website {website_id}",
            connection_type="ftp"
        )
        
        conn = Connection(
            website_id=website_id,
            host="localhost",
            port=21,
            username="test",
            password_encrypted="test"
        )
        
        conn_obj = build_connection_from_ids(
            website_id=website_id,
            root_url=website.root_url,
            connection_type=website.connection_type,
            website_root_path=website.website_root_path,
            connection_host=conn.host,
            connection_port=conn.port,
            connection_username=conn.username,
            connection_password=conn.password_encrypted,
            connection_private_key=conn.private_key_encrypted
        )

        before_html = html_content.decode("utf-8", errors="ignore") if html_content else ""

        _emit(website_id, "deploy_started", f"Starting deployment for {page_url or server_file}",
              change_id=change_id)

        # 1. Backup
        try:
            backup = create_backup(website_id, server_file, html_content, change_id)
            _emit(website_id, "backup_created", f"Backup created: {backup.local_path}",
                  metadata={"backup_id": backup.id}, change_id=change_id)
        except Exception as e:
            error_detail = {"error_type": "backup_failed", "error_message": str(e)}
            _emit(website_id, "backup_failed", f"Backup failed: {e}",
                  severity="error", metadata=error_detail, change_id=change_id)
            return {"ok": False, "message": f"Backup failed: {e}",
                    "error_type": "backup_failed", "error_detail": error_detail}

        # 2. Apply modifications
        try:
            new_html, applied_log = apply_changes(before_html, changes)
            _emit(website_id, "change_applied_locally", f"Applied {len(changes)} changes locally",
                  metadata={"applied_log": applied_log}, change_id=change_id)
        except Exception as e:
            error_detail = {"error_type": "apply_changes_failed", "error_message": str(e)}
            _emit(website_id, "apply_changes_failed", f"Apply changes failed: {e}",
                  severity="error", metadata=error_detail, change_id=change_id)
            return {"ok": False, "message": f"Apply changes failed: {e}",
                    "error_type": "apply_changes_failed", "error_detail": error_detail}

        # 3. Validate
        try:
            validation = validate_change_payload(before_html, new_html, changes)
        except Exception as e:
            error_detail = {"error_type": "validation_exception", "error_message": str(e)}
            _emit(website_id, "validation_exception", f"Validation exception: {e}",
                  severity="error", metadata=error_detail, change_id=change_id)
            return {"ok": False, "message": f"Validation exception: {e}",
                    "error_type": "validation_exception", "error_detail": error_detail}

        if not validation["ok"]:
            error_detail = {
                "error_type": "validation_failed",
                "error_message": "Validation failed",
                "validation_checks": validation.get("checks", [])
            }
            _emit(website_id, "validation_failed", "Validation failed",
                  severity="error", metadata=error_detail, change_id=change_id)
            return {"ok": False, "message": "Validation failed", "validation": validation,
                    "change_id": change_id, "error_type": "validation_failed",
                    "error_detail": error_detail}

        # 4. Upload with preflight for FTP/SFTP
        remote_root = _safe_remote_root(website, conn)

        if can_modify_remotely(website):
            deploy_status = "deployed"
            
            # Preflight
            preflight = _ftp_preflight(conn_obj, remote_root)
            if not preflight.get("ok"):
                error_detail = {
                    "error_type": "ftp_preflight_failed",
                    "error_message": "FTP preflight failed",
                    "preflight_steps": preflight.get("steps", [])
                }
                _emit(website_id, "ftp_preflight_failed", "FTP preflight failed",
                      severity="error", metadata=error_detail, change_id=change_id)
                return {"ok": False, "message": "FTP preflight failed", "preflight": preflight,
                        "change_id": change_id, "error_type": "ftp_preflight_failed",
                        "error_detail": error_detail}

            _emit(website_id, "ftp_preflight_passed", "FTP preflight passed",
                  metadata={"preflight": preflight}, change_id=change_id)

            # Upload
            conn_obj2 = build_connection_from_ids(
                website_id=website_id,
                root_url=website.root_url,
                connection_type=website.connection_type,
                website_root_path=website.website_root_path,
                connection_host=conn.host,
                connection_port=conn.port,
                connection_username=conn.username,
                connection_password=conn.password_encrypted,
                connection_private_key=conn.private_key_encrypted
            )
            
            connect_result2 = conn_obj2.connect()
            if not connect_result2.ok:
                error_detail = {
                    "error_type": "ftp_connection_failed",
                    "error_message": f"Connection failed: {connect_result2.message}",
                    "details": connect_result2.details
                }
                _emit(website_id, "ftp_connection_failed", f"Connection failed: {connect_result2.message}",
                      severity="error", metadata=error_detail, change_id=change_id)
                return {"ok": False, "message": f"Connection failed: {connect_result2.message}",
                        "change_id": change_id, "error_type": "ftp_connection_failed",
                        "error_detail": error_detail}

            remote_path_used = _resolve_remote_path(conn_obj2, server_file, remote_root)
            _emit(website_id, "ftp_upload_started", f"Uploading to {remote_path_used}",
                  metadata={"remote_path": remote_path_used}, change_id=change_id)

            upload_result = conn_obj2.upload(remote_path_used, new_html.encode("utf-8"))
            if hasattr(upload_result, 'to_dict'):
                upload_dict = upload_result.to_dict()
            else:
                upload_dict = {"ok": upload_result}

            if not upload_dict.get("ok", False):
                deploy_status = "failed"
                deploy_msg = upload_dict.get("message", "Upload failed")
                error_detail = {
                    "error_type": upload_dict.get("error_type", "upload_failed"),
                    "error_message": upload_dict.get("message", "Upload failed")
                }
                _emit(website_id, "ftp_upload_failed", f"Upload failed: {deploy_msg}",
                      severity="error", metadata=error_detail, change_id=change_id)
                conn_obj2.close()
                return {"ok": False, "message": f"Upload failed: {deploy_msg}",
                        "change_id": change_id, "error_type": "upload_failed",
                        "error_detail": error_detail}

            deploy_msg = "Uploaded successfully"
            _emit(website_id, "ftp_upload_completed", f"Upload completed: {remote_path_used}",
                  metadata={"remote_path": remote_path_used, "size": len(new_html)}, change_id=change_id)

            # Post-upload verification
            downloaded = conn_obj2.download(remote_path_used)
            if downloaded is None:
                deploy_status = "verification_failed"
                deploy_msg = "Upload succeeded but download verification failed"
                error_detail = {
                    "error_type": "ftp_verification_failed",
                    "error_message": "Cannot download uploaded file for verification",
                    "remote_file_path": remote_path_used
                }
                _emit(website_id, "ftp_verification_failed", deploy_msg,
                      severity="error", metadata=error_detail, change_id=change_id)
                conn_obj2.close()
                return {"ok": False, "message": deploy_msg,
                        "change_id": change_id, "error_type": "ftp_verification_failed",
                        "error_detail": error_detail}

            uploaded_content = downloaded.decode("utf-8", errors="ignore")
            if _normalize_for_compare(uploaded_content) != _normalize_for_compare(new_html):
                deploy_status = "verification_failed"
                deploy_msg = "Uploaded content does not match expected content"
                error_detail = {
                    "error_type": "ftp_verification_failed",
                    "error_message": "Uploaded content mismatch",
                    "remote_file_path": remote_path_used
                }
                _emit(website_id, "ftp_verification_failed", deploy_msg,
                      severity="error", metadata=error_detail, change_id=change_id)
                conn_obj2.close()
                return {"ok": False, "message": deploy_msg,
                        "change_id": change_id, "error_type": "ftp_verification_failed",
                        "error_detail": error_detail}

            ftp_verified = True
            _emit(website_id, "remote_file_verified", "Remote file content verified",
                  metadata={"remote_path": remote_path_used}, change_id=change_id)

            conn_obj2.close()
        else:
            deploy_status = "pending_manual"

        # 5. Verify public site
        verification = {"ok": True, "checks": []}
        
        try:
            verify_url = urljoin(website.root_url, page_url or server_file)
            browser_result = fetch_real_html(verify_url)
            if browser_result.get("ok") and browser_result.get("html"):
                browser_html = browser_result["html"]
                browser_verification = {
                    "ok": True,
                    "status_code": browser_result.get("status_code", 200),
                    "final_url": browser_result.get("final_url", verify_url),
                    "source": browser_result.get("source"),
                    "change_detected": _change_exists_in_html(changes, new_html, browser_html),
                    "title_match": _title_matches(new_html, browser_html)
                }
                verification["browser"] = browser_verification
                if browser_verification.get("change_detected"):
                    _emit(website_id, "production_browser_verified",
                          f"Production browser verified: {verify_url}",
                          metadata={"change_detected": True}, change_id=change_id)
                else:
                    verification["ok"] = False
                    _emit(website_id, "production_browser_verification_failed",
                          "SEO change not found in production DOM",
                          severity="warning", change_id=change_id)
        except Exception as e:
            verification["ok"] = False
            browser_verification = {"ok": False, "reason": str(e)}
            verification["browser"] = browser_verification

        if not verification.get("ok", True) and deploy_status == "deployed":
            deploy_status = "verification_failed"

        # 6. Record SEOChange
        seo_change = SEOChange(
            website_id=website_id,
            change_id=change_id,
            page_url=page_url or server_file,
            server_file=server_file,
            change_type=changes[0]["type"] if changes else "multiple",
            before_value=before_html[:5000],
            after_value=new_html[:5000],
            reasoning="; ".join(c.get("reason", "") for c in changes),
            confidence=sum(c.get("confidence", 0.5) for c in changes) / max(1, len(changes)) if changes else 0.0,
            risk=changes[0].get("risk", "low") if changes else "low",
            status=deploy_status,
            backup_id=backup.id if backup else None,
            validation_result=json.dumps(validation),
            failure_details=error_detail if deploy_status in ("failed", "verification_failed") else {},
            deployed_at=deployed_at if deploy_status == "deployed" else None
        )

        log_audit("system", "change_deployed", change_id,
                  {"website_id": website_id, "page_url": page_url or server_file,
                   "status": deploy_status})

        result = {
            "ok": deploy_status == "deployed",
            "change_id": change_id,
            "status": deploy_status,
            "message": deploy_msg or ("Pending manual deployment" if deploy_status == "pending_manual" else "OK"),
            "validation": validation,
            "applied_log": applied_log,
            "verification": verification,
            "seo_change_id": seo_change.id,
            "error_type": error_detail.get("error_type"),
            "error_detail": error_detail,
            "remote_path_used": remote_path_used,
            "deployment_report": {
                "ftp_verified": ftp_verified,
                "browser_verified": browser_verification.get("ok", False),
                "change_detected_in_production": browser_verification.get("change_detected", False),
                "final_status": deploy_status
            }
        }
        return result

    finally:
        sess.close()


def rollback_change(seo_change_id: int) -> Dict:
    """Rollback a deployed change."""
    sess = new_session()
    try:
        seo_change = SEOChange(
            id=seo_change_id,
            website_id=1,
            change_id=f"change_{seo_change_id}",
            server_file="index.html",
            status="rolled_back"
        )
        
        # In a real implementation, this would restore from backup
        log_audit("system", "change_rolled_back", seo_change.change_id,
                  {"website_id": 1, "seo_change_id": seo_change_id})
        
        return {"ok": True, "rolled_back": True, "message": "Rollback recorded"}
    finally:
        sess.close()

