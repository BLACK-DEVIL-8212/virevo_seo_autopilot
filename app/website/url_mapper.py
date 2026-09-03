"""URL-to-server-file mapping engine.

Maps public URLs to potential server files based on common conventions.
Returns confidence levels so we never modify files we're unsure about.
"""
from __future__ import annotations
from urllib.parse import urlparse
from typing import Optional, Dict, List


INDEX_FILES = ["index.html", "index.htm", "default.html", "default.htm"]


def candidate_files_for_url(public_url: str, web_root: str = "") -> List[Dict]:
    """Return candidate server file paths for a given URL with confidence scores."""
    parsed = urlparse(public_url)
    path = parsed.path or "/"
    segments = [s for s in path.split("/") if s]
    candidates: List[Dict] = []

    base = (web_root or "").rstrip("/")

    # 1. direct HTML file
    if path.endswith(".html") or path.endswith(".htm"):
        rel = path.lstrip("/")
        candidates.append({"file": f"{base}/{rel}" if base else rel, "confidence": 0.95, "reason": "explicit .html"})
        return candidates

    # 2. directory + index.html
    if not segments:
        for idx in INDEX_FILES:
            candidates.append({"file": f"{base}/{idx}" if base else idx, "confidence": 0.85, "reason": f"root /{idx}"})
        return candidates

    # Build candidates like /about -> about.html, about/index.html
    rel_no_slash = "/".join(segments)
    candidates.append({"file": f"{base}/{rel_no_slash}.html" if base else f"{rel_no_slash}.html",
                       "confidence": 0.65, "reason": "named .html file"})
    for idx in INDEX_FILES[:1]:
        candidates.append({"file": f"{base}/{rel_no_slash}/{idx}" if base else f"{rel_no_slash}/{idx}",
                           "confidence": 0.55, "reason": f"directory with {idx}"})

    return candidates


def best_mapping(public_url: str, web_root: str = "",
                 available_files: Optional[List[str]] = None) -> Dict:
    candidates = candidate_files_for_url(public_url, web_root)
    if available_files:
        avail_norm = {f.replace("\\", "/") for f in available_files}
        for c in candidates:
            cf = c["file"].replace("\\", "/").lstrip("/")
            if cf in avail_norm or ("/" + cf) in avail_norm:
                c["confidence"] = min(0.99, c["confidence"] + 0.2)
                c["verified"] = True
        # sort by confidence desc
        candidates.sort(key=lambda x: x["confidence"], reverse=True)
    return {
        "url": public_url,
        "best": candidates[0] if candidates else None,
        "all_candidates": candidates,
    }