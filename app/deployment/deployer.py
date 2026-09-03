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
import requests
import uuid
import traceback
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

from ..utils import is_js_verification_page, fetch_real_html
from ..connections.connection_manager import (
    build_connection_from_ids, PublicUrlAccess,
    FTPConnection, SFTPConnection, FTPResult, ConnectionTestResult,
)
from ..database.database import new_session, log_audit
from ..database.models import (
    Website, Connection, SEOChange, Backup, Deployment,
)
from ..modifiers import apply_changes, validate_html, validate_json_ld
from .backup_manager import create_backup, sha256_bytes
from .validator import validate_change_payload


def _normalize_for_compare(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")


def _new_change_id() -> str:
    return f"SEO-{uuid.uuid4().hex[:10].upper()}"


def can_modify_remotely(website: Website) -> bool:
    return website.connection_type in ("ftp", "sftp")


def _safe_remote_root(website: Website, conn: Optional[Connection]) -> str:
    """Determine the explicit remote root directory."""
    if conn and conn.extra_json and isinstance(conn.extra_json, dict):
        root = conn.extra_json.get("remote_root") or conn.extra_json.get("ftp_root") or ""
        if root:
            return root.rstrip("/") or "/"
    return (website.website_root_path or "").rstrip("/") or "/"


def _resolve_remote_path(conn_obj, server_file: str, remote_root: str) -> str:
    """Resolve the final remote path using the connection object's root.
    
    Always uses forward slashes for FTP/SFTP paths.
    """
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
    """Emit deployment event for activity monitoring."""
    try:
        log_audit("deployment", event_type, change_id, {
            "website_id": website_id,
            "message": message,
            "severity": severity,
            **(metadata or {}),
        })
    except Exception:
        pass


def _ftp_preflight(conn_obj, remote_root: str) -> Dict:
    """Run FTP preflight diagnostics and return structured result."""
    steps = []
    overall_ok = True

    connect_result = conn_obj.connect()
    steps.append({
        "step": "ftp_connect",
        "ok": connect_result.ok,
        "message": connect_result.message,
        "details": connect_result.details,
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
            "path": remote_root or "/",
        })
    except Exception as e:
        steps.append({"step": "list_directory", "ok": False, "error": str(e)})
        overall_ok = False

    # Test write permission with temp file
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
        "result": upload_dict,
    })
    if not upload_dict.get("ok", False):
        overall_ok = False

    # Clean up test file
    try:
        if hasattr(conn_obj, '_conn') and conn_obj._conn:
            conn_obj._conn.delete(test_filename)
        elif hasattr(conn_obj, '_sftp') and conn_obj._sftp:
            try:
                conn_obj._sftp.remove(test_path)
            except Exception:
                pass
    except Exception:
        pass

    conn_obj.close()
    return {"ok": overall_ok, "steps": steps}


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
        website: Website = sess.get(Website, website_id)
        if not website:
            return {"ok": False, "message": "Website not found",
                    "error_type": "not_found", "error_detail": {}}

        conn = sess.query(Connection).filter_by(website_id=website_id).first()
        conn_obj = build_connection_from_ids(
            website_id=website_id,
            root_url=website.root_url,
            connection_type=website.connection_type,
            website_root_path=website.website_root_path,
            connection_host=conn.host if conn else "",
            connection_port=conn.port if conn else 21,
            connection_username=conn.username if conn else "",
            connection_password=conn.password_encrypted if conn else "",
            connection_private_key=conn.private_key_encrypted if conn else "",
        )

        before_html = html_content.decode("utf-8", errors="ignore") if html_content else ""

        deployment_meta = {
            "website_id": website_id,
            "website_name": website.name,
            "connection_type": website.connection_type,
            "root_url": website.root_url,
            "website_root_path": website.website_root_path,
            "server_file": server_file,
            "page_url": page_url,
            "change_id": change_id,
            "conn_host": conn.host if conn else "",
            "conn_port": conn.port if conn else 21,
            "conn_username": conn.username if conn else "",
            "conn_has_password": bool(conn.password_encrypted if conn else False),
            "conn_has_private_key": bool(conn.private_key_encrypted if conn else False),
            "optimization_run_id": changes[0].get("optimization_run_id", "") if changes else "",
        }

        # For FTP/SFTP sites, download the actual production source file.
        # This ensures we modify the real hosting file, not a browser-verification-wrapped page.
        remote_path_used = server_file
        if can_modify_remotely(website):
            remote_root = _safe_remote_root(website, conn)
            remote_path_used = _resolve_remote_path(conn_obj, server_file, remote_root)
            try:
                connect_result = conn_obj.connect()
                if connect_result.ok:
                    original_bytes = conn_obj.download(remote_path_used)
                    if original_bytes is not None:
                        before_html = original_bytes.decode("utf-8", errors="ignore")
                        deployment_meta["source_mode"] = "ftp_download"
                        deployment_meta["ftp_remote_path"] = remote_path_used
                        deployment_meta["ftp_file_size"] = len(original_bytes)
                        deployment_meta["ftp_sha256"] = sha256_bytes(original_bytes)
                    else:
                        deployment_meta["source_mode"] = "caller_provided"
                        deployment_meta["ftp_download_error"] = "FTP download returned None"
                else:
                    deployment_meta["source_mode"] = "caller_provided"
                    deployment_meta["ftp_download_error"] = f"FTP connect failed: {connect_result.message}"
            except Exception as e:
                deployment_meta["source_mode"] = "caller_provided"
                deployment_meta["ftp_download_error"] = str(e)
        else:
            deployment_meta["source_mode"] = "caller_provided"

        _emit(website_id, "deploy_started", f"Starting deployment for {page_url}",
              metadata=deployment_meta, change_id=change_id)

        # 1. Backup
        try:
            backup = create_backup(website_id, server_file, html_content, change_id)
            deployment_meta["backup_id"] = backup.id
            deployment_meta["backup_path"] = backup.local_path
            _emit(website_id, "backup_created", f"Backup created: {backup.local_path}",
                  metadata={"backup_id": backup.id}, change_id=change_id)
        except Exception as e:
            error_detail = {
                "error_type": "backup_failed",
                "error_message": str(e),
                "stack_trace": traceback.format_exc(),
                "deployment_target": server_file,
                "source_file_path": getattr(backup, 'local_path', '') if 'backup' in dir() else "",
                "remote_file_path": server_file,
                "website_connection_type": website.connection_type,
                "optimization_run_id": "",
                **deployment_meta,
            }
            _emit(website_id, "backup_failed", f"Backup failed: {e}",
                  severity="error", metadata=error_detail, change_id=change_id)
            seo_change = SEOChange(
                website_id=website_id,
                change_id=change_id,
                page_url=page_url,
                server_file=server_file,
                change_type=changes[0]["type"] if changes else "multiple",
                before_value=before_html[:5000],
                after_value=new_html[:5000] if 'new_html' in dir() else before_html[:5000],
                reasoning="; ".join(c.get("reason", "") for c in changes) if changes else "",
                confidence=sum(c.get("confidence", 0.5) for c in changes) / max(1, len(changes)) if changes else 0.0,
                risk=changes[0].get("risk", "low") if changes else "low",
                status="failed",
                backup_id=getattr(backup, 'id', None),
                validation_result="",
                failure_details=error_detail,
            )
            sess.add(seo_change)
            sess.commit()
            return {"ok": False, "message": f"Backup failed: {e}",
                    "error_type": "backup_failed", "error_detail": error_detail}

        # 2. Apply modifications
        try:
            new_html, applied_log = apply_changes(before_html, changes)
            deployment_meta["applied_log"] = applied_log
            deployment_meta["changes_count"] = len(changes)
            _emit(website_id, "change_applied_locally", f"Applied {len(changes)} changes locally",
                  metadata={"applied_log": applied_log}, change_id=change_id)
        except Exception as e:
            error_detail = {
                "error_type": "apply_changes_failed",
                "error_message": str(e),
                "stack_trace": traceback.format_exc(),
                "deployment_target": server_file,
                "source_file_path": "",
                "remote_file_path": server_file,
                "website_connection_type": website.connection_type,
                "optimization_run_id": "",
                **deployment_meta,
            }
            _emit(website_id, "apply_changes_failed", f"Apply changes failed: {e}",
                  severity="error", metadata=error_detail, change_id=change_id)
            seo_change = SEOChange(
                website_id=website_id,
                change_id=change_id,
                page_url=page_url,
                server_file=server_file,
                change_type=changes[0]["type"] if changes else "multiple",
                before_value=before_html[:5000],
                after_value=before_html[:5000],
                reasoning="; ".join(c.get("reason", "") for c in changes) if changes else "",
                confidence=sum(c.get("confidence", 0.5) for c in changes) / max(1, len(changes)) if changes else 0.0,
                risk=changes[0].get("risk", "low") if changes else "low",
                status="failed",
                backup_id=backup.id if backup else None,
                validation_result="",
                failure_details=error_detail,
            )
            sess.add(seo_change)
            sess.commit()
            return {"ok": False, "message": f"Apply changes failed: {e}",
                    "error_type": "apply_changes_failed", "error_detail": error_detail}

        # 3. Validate
        try:
            validation = validate_change_payload(before_html, new_html, changes)
            deployment_meta["validation"] = validation
        except Exception as e:
            error_detail = {
                "error_type": "validation_exception",
                "error_message": str(e),
                "stack_trace": traceback.format_exc(),
                "deployment_target": server_file,
                "source_file_path": "",
                "remote_file_path": server_file,
                "website_connection_type": website.connection_type,
                "optimization_run_id": "",
                **deployment_meta,
            }
            _emit(website_id, "validation_exception", f"Validation exception: {e}",
                  severity="error", metadata=error_detail, change_id=change_id)
            seo_change = SEOChange(
                website_id=website_id,
                change_id=change_id,
                page_url=page_url,
                server_file=server_file,
                change_type=changes[0]["type"] if changes else "multiple",
                before_value=before_html[:5000],
                after_value=new_html[:5000],
                reasoning="; ".join(c.get("reason", "") for c in changes),
                confidence=sum(c.get("confidence", 0.5) for c in changes) / max(1, len(changes)),
                risk=changes[0].get("risk", "low") if changes else "low",
                status="failed",
                backup_id=backup.id if backup else None,
                validation_result="",
                failure_details=error_detail,
            )
            sess.add(seo_change)
            sess.commit()
            return {"ok": False, "message": f"Validation exception: {e}",
                    "error_type": "validation_exception", "error_detail": error_detail}

        if not validation["ok"]:
            error_detail = {
                "error_type": "validation_failed",
                "error_message": "Validation failed",
                "validation_checks": validation.get("checks", []),
                "deployment_target": server_file,
                "source_file_path": "",
                "remote_file_path": server_file,
                "website_connection_type": website.connection_type,
                "optimization_run_id": "",
                **deployment_meta,
            }
            seo_change = SEOChange(
                website_id=website_id,
                change_id=change_id,
                page_url=page_url,
                server_file=server_file,
                change_type=changes[0]["type"] if changes else "multiple",
                before_value=before_html[:5000],
                after_value=new_html[:5000],
                reasoning="; ".join(c.get("reason", "") for c in changes),
                confidence=sum(c.get("confidence", 0.5) for c in changes) / max(1, len(changes)),
                risk=changes[0].get("risk", "low") if changes else "low",
                status="failed",
                backup_id=backup.id,
                validation_result=json.dumps(validation),
                failure_details=error_detail,
            )
            sess.add(seo_change)
            sess.commit()
            _emit(website_id, "validation_failed", "Validation failed",
                  severity="error", metadata=error_detail, change_id=change_id)
            return {"ok": False, "message": "Validation failed", "validation": validation,
                    "change_id": change_id, "error_type": "validation_failed",
                    "error_detail": error_detail}

        # 4. Upload with preflight for FTP/SFTP
        remote_root = _safe_remote_root(website, conn)

        if can_modify_remotely(website):
            deploy_status = "deployed"
            _emit(website_id, "ftp_preflight_started", f"Starting FTP preflight for {server_file}",
                  metadata={"remote_root": remote_root, "server_file": server_file}, change_id=change_id)

            # Preflight
            preflight = _ftp_preflight(conn_obj, remote_root)
            if not preflight.get("ok"):
                error_detail = {
                    "error_type": "ftp_preflight_failed",
                    "error_message": "FTP preflight failed",
                    "preflight_steps": preflight.get("steps", []),
                    "deployment_target": server_file,
                    "source_file_path": backup.local_path if backup else "",
                    "remote_file_path": server_file,
                    "remote_root": remote_root,
                    "website_connection_type": website.connection_type,
                    "optimization_run_id": "",
                    **deployment_meta,
                }
                _emit(website_id, "ftp_preflight_failed", "FTP preflight failed",
                      severity="error", metadata=error_detail, change_id=change_id)
                seo_change = SEOChange(
                    website_id=website_id,
                    change_id=change_id,
                    page_url=page_url,
                    server_file=server_file,
                    change_type=changes[0]["type"] if changes else "multiple",
                    before_value=before_html[:5000],
                    after_value=new_html[:5000],
                    reasoning="; ".join(c.get("reason", "") for c in changes),
                    confidence=sum(c.get("confidence", 0.5) for c in changes) / max(1, len(changes)),
                    risk=changes[0].get("risk", "low") if changes else "low",
                    status="failed",
                    backup_id=backup.id if backup else None,
                    validation_result=json.dumps(validation),
                    failure_details=error_detail,
                )
                sess.add(seo_change)
                sess.commit()
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
                connection_host=conn.host if conn else "",
                connection_port=conn.port if conn else 21,
                connection_username=conn.username if conn else "",
                connection_password=conn.password_encrypted if conn else "",
                connection_private_key=conn.private_key_encrypted if conn else "",
            )
            connect_result2 = conn_obj2.connect()
            if not connect_result2.ok:
                error_detail = {
                    "error_type": "ftp_connection_failed",
                    "error_message": f"Connection failed: {connect_result2.message}",
                    "details": connect_result2.details,
                    "deployment_target": server_file,
                    "source_file_path": backup.local_path if backup else "",
                    "remote_file_path": server_file,
                    "remote_root": remote_root,
                    "website_connection_type": website.connection_type,
                    "optimization_run_id": "",
                    **deployment_meta,
                }
                _emit(website_id, "ftp_connection_failed", f"Connection failed: {connect_result2.message}",
                      severity="error", metadata=error_detail, change_id=change_id)
                seo_change = SEOChange(
                    website_id=website_id,
                    change_id=change_id,
                    page_url=page_url,
                    server_file=server_file,
                    change_type=changes[0]["type"] if changes else "multiple",
                    before_value=before_html[:5000],
                    after_value=new_html[:5000],
                    reasoning="; ".join(c.get("reason", "") for c in changes),
                    confidence=sum(c.get("confidence", 0.5) for c in changes) / max(1, len(changes)),
                    risk=changes[0].get("risk", "low") if changes else "low",
                    status="failed",
                    backup_id=backup.id if backup else None,
                    validation_result=json.dumps(validation),
                    failure_details=error_detail,
                )
                sess.add(seo_change)
                sess.commit()
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
                deploy_msg = upload_dict.get("error_message", "Upload failed")
                error_detail = {
                    "error_type": upload_dict.get("error_type", "upload_failed"),
                    "error_message": upload_dict.get("error_message", "Upload failed"),
                    "traceback": upload_dict.get("traceback", ""),
                    "ftp_command": upload_dict.get("ftp_command", ""),
                    "remote_directory": upload_dict.get("remote_directory", remote_root),
                    "deployment_target": server_file,
                    "source_file_path": backup.local_path if backup else "",
                    "remote_file_path": remote_path_used,
                    "remote_root": remote_root,
                    "website_connection_type": website.connection_type,
                    "optimization_run_id": "",
                    **deployment_meta,
                }
                _emit(website_id, "ftp_upload_failed", f"Upload failed: {deploy_msg}",
                      severity="error", metadata=error_detail, change_id=change_id)
                try:
                    conn_obj2.close()
                except Exception:
                    pass
                seo_change = SEOChange(
                    website_id=website_id,
                    change_id=change_id,
                    page_url=page_url,
                    server_file=server_file,
                    change_type=changes[0]["type"] if changes else "multiple",
                    before_value=before_html[:5000],
                    after_value=new_html[:5000],
                    reasoning="; ".join(c.get("reason", "") for c in changes),
                    confidence=sum(c.get("confidence", 0.5) for c in changes) / max(1, len(changes)),
                    risk=changes[0].get("risk", "low") if changes else "low",
                    status="failed",
                    backup_id=backup.id if backup else None,
                    validation_result=json.dumps(validation),
                    failure_details=error_detail,
                )
                sess.add(seo_change)
                sess.commit()
                return {"ok": False, "message": f"Upload failed: {deploy_msg}",
                        "change_id": change_id, "error_type": "upload_failed",
                        "error_detail": error_detail}

            deploy_msg = "Uploaded successfully"
            _emit(website_id, "ftp_upload_completed", f"Upload completed: {remote_path_used}",
                  metadata={"remote_path": remote_path_used, "size": len(new_html)}, change_id=change_id)

            # Post-upload verification: download and compare
            downloaded = conn_obj2.download(remote_path_used)
            if downloaded is None:
                deploy_status = "verification_failed"
                deploy_msg = "Upload succeeded but download verification failed"
                error_detail = {
                    "error_type": "ftp_verification_failed",
                    "error_message": "Cannot download uploaded file for verification",
                    "remote_file_path": remote_path_used,
                    "deployment_target": server_file,
                    "source_file_path": backup.local_path if backup else "",
                    "remote_root": remote_root,
                    "website_connection_type": website.connection_type,
                    "optimization_run_id": "",
                    **deployment_meta,
                }
                _emit(website_id, "ftp_verification_failed", deploy_msg,
                      severity="error", metadata=error_detail, change_id=change_id)
                try:
                    conn_obj2.close()
                except Exception:
                    pass
                seo_change = SEOChange(
                    website_id=website_id,
                    change_id=change_id,
                    page_url=page_url,
                    server_file=server_file,
                    change_type=changes[0]["type"] if changes else "multiple",
                    before_value=before_html[:5000],
                    after_value=new_html[:5000],
                    reasoning="; ".join(c.get("reason", "") for c in changes),
                    confidence=sum(c.get("confidence", 0.5) for c in changes) / max(1, len(changes)),
                    risk=changes[0].get("risk", "low") if changes else "low",
                    status="verification_failed",
                    backup_id=backup.id if backup else None,
                    validation_result=json.dumps(validation),
                    failure_details=error_detail,
                )
                sess.add(seo_change)
                sess.commit()
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
                    "remote_file_path": remote_path_used,
                    "deployment_target": server_file,
                    "source_file_path": backup.local_path if backup else "",
                    "remote_root": remote_root,
                    "website_connection_type": website.connection_type,
                    "optimization_run_id": "",
                    **deployment_meta,
                }
                _emit(website_id, "ftp_verification_failed", deploy_msg,
                      severity="error", metadata=error_detail, change_id=change_id)
                try:
                    conn_obj2.close()
                except Exception:
                    pass
                seo_change = SEOChange(
                    website_id=website_id,
                    change_id=change_id,
                    page_url=page_url,
                    server_file=server_file,
                    change_type=changes[0]["type"] if changes else "multiple",
                    before_value=before_html[:5000],
                    after_value=new_html[:5000],
                    reasoning="; ".join(c.get("reason", "") for c in changes),
                    confidence=sum(c.get("confidence", 0.5) for c in changes) / max(1, len(changes)),
                    risk=changes[0].get("risk", "low") if changes else "low",
                    status="verification_failed",
                    backup_id=backup.id if backup else None,
                    validation_result=json.dumps(validation),
                    failure_details=error_detail,
                )
                sess.add(seo_change)
                sess.commit()
                return {"ok": False, "message": deploy_msg,
                        "change_id": change_id, "error_type": "ftp_verification_failed",
                        "error_detail": error_detail}

            ftp_verified = True
            _emit(website_id, "remote_file_verified", "Remote file content verified",
                  metadata={"remote_path": remote_path_used}, change_id=change_id)

            try:
                conn_obj2.close()
            except Exception:
                pass
        else:
            deploy_status = "pending_manual"

        # 5. Verify public site
        verification = {"ok": True, "checks": []}
        browser_verification = {"ok": False, "reason": "not_attempted"}

        # 5a. FTP verification (already performed above)
        # 5b. Browser verification via Playwright
        try:
            verify_url = urljoin(website.root_url, page_url)
            browser_result = fetch_real_html(verify_url)
            if browser_result.get("ok") and browser_result.get("html"):
                browser_html = browser_result["html"]
                browser_verification = {
                    "ok": True,
                    "status_code": browser_result.get("status_code", 200),
                    "final_url": browser_result.get("final_url", verify_url),
                    "source": browser_result.get("source"),
                    "change_detected": _change_exists_in_html(changes, new_html, browser_html),
                    "title_match": _title_matches(new_html, browser_html),
                }
                verification["browser"] = browser_verification
                if browser_verification["change_detected"]:
                    _emit(website_id, "production_browser_verified",
                          f"Production browser verified: {verify_url}",
                          metadata={"final_url": browser_result.get("final_url"),
                                    "source": browser_result.get("source"),
                                    "change_detected": True},
                          change_id=change_id)
                else:
                    verification["ok"] = False
                    deploy_msg = (deploy_msg + "; " if deploy_msg else "") + "Browser verification: SEO change not found in production DOM"
                    _emit(website_id, "production_browser_verification_failed",
                          "SEO change not found in production browser DOM",
                          severity="warning", metadata={"final_url": browser_result.get("final_url")},
                          change_id=change_id)
            else:
                verification["ok"] = False
                browser_verification = {
                    "ok": False,
                    "reason": browser_result.get("error", "fetch_failed"),
                    "challenge": browser_result.get("challenge"),
                }
                verification["browser"] = browser_verification
                deploy_msg = (deploy_msg + "; " if deploy_msg else "") + f"Browser verification failed: {browser_result.get('error')}"
                _emit(website_id, "production_browser_verification_failed",
                      f"Browser verification failed: {browser_result.get('error')}",
                      severity="warning", metadata={"error": browser_result.get("error"),
                                                     "challenge": browser_result.get("challenge")},
                      change_id=change_id)
        except Exception as e:
            verification["ok"] = False
            browser_verification = {"ok": False, "reason": str(e)}
            verification["browser"] = browser_verification
            deploy_msg = (deploy_msg + "; " if deploy_msg else "") + f"Browser verification error: {e}"

        if not verification.get("ok", True) and deploy_status == "deployed":
            deploy_status = "verification_failed"

        # 6. Record deployment row
        deployment = Deployment(
            website_id=website_id,
            change_id=change_id,
            server_file=server_file,
            status=deploy_status,
            message=deploy_msg,
            verification_json=verification,
        )
        sess.add(deployment)
        sess.flush()

        # 7. Record SEOChange
        seo_change = SEOChange(
            website_id=website_id,
            change_id=change_id,
            page_url=page_url,
            server_file=server_file,
            change_type=changes[0]["type"] if changes else "multiple",
            before_value=before_html[:5000],
            after_value=new_html[:5000],
            reasoning="; ".join(c.get("reason", "") for c in changes),
            confidence=sum(c.get("confidence", 0.5) for c in changes) / max(1, len(changes)),
            risk=changes[0].get("risk", "low") if changes else "low",
            status=deploy_status,
            backup_id=backup.id if backup else None,
            deployment_id=deployment.id,
            validation_result=json.dumps(validation),
            failure_details=error_detail if deploy_status in ("failed", "verification_failed") else {
                "deployment_report": {
                    "source_mode": deployment_meta.get("source_mode"),
                    "ftp_remote_path": deployment_meta.get("ftp_remote_path"),
                    "ftp_file_size": deployment_meta.get("ftp_file_size"),
                    "ftp_sha256": deployment_meta.get("ftp_sha256"),
                    "modified_sha256": sha256_bytes(new_html.encode("utf-8")),
                    "browser_verification": browser_verification,
                    "change_detected_in_production": browser_verification.get("change_detected", False),
                }
            },
            deployed_at=deployed_at if deploy_status == "deployed" else None,
        )
        sess.add(seo_change)
        sess.commit()
        sess.refresh(seo_change)

        log_audit("system", "change_deployed", change_id,
                  {"website_id": website_id, "page_url": page_url,
                   "status": deploy_status, "change_type": changes[0]["type"] if changes else "multiple"})

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
                "source_mode": deployment_meta.get("source_mode"),
                "ftp_remote_path": deployment_meta.get("ftp_remote_path"),
                "ftp_file_size": deployment_meta.get("ftp_file_size"),
                "ftp_sha256": deployment_meta.get("ftp_sha256"),
                "modified_sha256": sha256_bytes(new_html.encode("utf-8")),
                "uploaded_size": len(new_html.encode("utf-8")),
                "ftp_verified": ftp_verified,
                "browser_verified": browser_verification.get("ok", False),
                "change_detected_in_production": browser_verification.get("change_detected", False),
                "final_status": deploy_status,
            },
        }
        return result
    finally:
        sess.close()


def _title_matches(after_html: str, response_text: str) -> bool:
    """Lightweight check that a new title appears in the live response."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(after_html or "", "html.parser")
    new_title = (soup.title.string or "").strip() if soup.title else ""
    if not new_title:
        return True
    return new_title in response_text


def _change_exists_in_html(changes: List[Dict], new_html: str, production_html: str) -> bool:
    """Verify that at least one deployed change is detectable in production HTML."""
    if not changes or not new_html or not production_html:
        return False
    production_lower = production_html.lower()
    for change in changes:
        value = change.get("value", "")
        if not value:
            continue
        change_type = change.get("type", "")
        if change_type == "meta_description":
            if value.lower() in production_lower:
                return True
        elif change_type == "title":
            if value.lower() in production_lower:
                return True
        elif change_type == "h1":
            if value.lower() in production_lower:
                return True
        elif change_type == "canonical":
            if value.lower() in production_lower:
                return True
        else:
            if value.lower() in production_lower:
                return True
    return False


def rollback_change(seo_change_id: int) -> Dict:
    sess = new_session()
    try:
        sc: SEOChange = sess.get(SEOChange, seo_change_id)
        if not sc or not sc.backup_id:
            return {"ok": False, "message": "No backup available"}
        website = sess.get(Website, sc.website_id)
        if not website:
            return {"ok": False, "message": "Website not found"}
        backup = sess.get(Backup, sc.backup_id)
        if not backup:
            return {"ok": False, "message": "Backup record missing"}
        conn = sess.query(Connection).filter_by(website_id=website.id).first()
        conn_obj = build_connection_from_ids(
            website_id=website.id,
            root_url=website.root_url,
            connection_type=website.connection_type,
            website_root_path=website.website_root_path,
            connection_host=conn.host if conn else "",
            connection_port=conn.port if conn else 21,
            connection_username=conn.username if conn else "",
            connection_password=conn.password_encrypted if conn else "",
            connection_private_key=conn.private_key_encrypted if conn else "",
        )

        original_bytes = __import__("pathlib").Path(backup.local_path).read_bytes()
        result = {"uploaded": False}

        if can_modify_remotely(website):
            try:
                connect_result = conn_obj.connect()
                if connect_result.ok:
                    remote_root = _safe_remote_root(website, conn)
                    remote_path = _resolve_remote_path(conn_obj, sc.server_file, remote_root)
                    upload_result = conn_obj.upload(remote_path, original_bytes)
                    if hasattr(upload_result, 'to_dict'):
                        result["uploaded"] = upload_result.ok
                        result["upload_detail"] = upload_result.to_dict()
                    else:
                        result["uploaded"] = bool(upload_result)
            except Exception as e:
                result["error"] = str(e)
                result["traceback"] = traceback.format_exc()
            finally:
                try:
                    conn_obj.close()
                except Exception:
                    pass

        sc.status = "rolled_back"
        sess.add(sc)
        sess.commit()
        log_audit("system", "change_rolled_back", sc.change_id,
                  {"website_id": website.id, "seo_change_id": sc.id,
                   "uploaded": result.get("uploaded")})
        return {"ok": True, "rolled_back": True, "uploaded": result.get("uploaded"),
                "message": "Rollback recorded" + (" and uploaded" if result.get("uploaded") else "")}
    finally:
        sess.close()
