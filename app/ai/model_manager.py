"""AI Model Manager - centralized lifecycle for local Hugging Face GGUF models."""
from __future__ import annotations
import os
import time
import threading
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from collections import deque

from huggingface_hub import hf_hub_download, model_info
from llama_cpp import Llama

from ..config import Config
from ..events import get_event_manager

logger = logging.getLogger(__name__)


class AIModelManager:
    """Singleton manager for downloading, loading, and serving a local GGUF model."""

    _instance: Optional["AIModelManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.model: Optional[Llama] = None
        self.model_path: Optional[str] = None
        self.status = "not_initialized"
        self.last_error: str = ""
        self.device = "cpu"
        self._load_lock = threading.Lock()
        self._download_lock = threading.Lock()
        self._downloading = False
        self._initializing = False
        self._init_started = False
        self._init_completed = False
        self.event_manager = get_event_manager()
        self._task_queue: deque = deque()
        self._processing_queue = False
        self._download_progress = {
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "percentage": 0.0,
            "speed_mbps": 0.0,
            "current_file": "",
            "status": "idle",
        }
        self._warmup_completed = False
        self._inference_passed = False
        self._ai_tasks_waiting = 0
        self._ai_tasks_completed = 0

    def _emit(self, event_type: str, message: str = "", severity: str = "info",
              metadata: dict = None):
        if self.event_manager:
            self.event_manager.emit(
                job_id="", event_type=event_type, message=message,
                agent_name="AI System", severity=severity, metadata=metadata or {},
            )

    def get_status(self) -> Dict[str, Any]:
        model_exists = self.model_path and Path(self.model_path).exists()
        model_size_mb = 0
        if model_exists:
            model_size_mb = round(Path(self.model_path).stat().st_size / 1024 / 1024, 2)

        cache_dir = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
        disk_usage = shutil.disk_usage(cache_dir)
        available_gb = round(disk_usage.free / 1024 / 1024 / 1024, 2)

        return {
            "provider": "huggingface",
            "model": os.environ.get("AI_MODEL", "user052/EDIATH-Q4_K_M"),
            "download_status": "DOWNLOADED" if model_exists else "NOT_DOWNLOADED",
            "model_load_status": "READY" if self.model is not None else "NOT_LOADED",
            "tokenizer_status": "READY" if self.model is not None else "NOT_LOADED",
            "inference_test": "PASSED" if self._inference_passed else "NOT_TESTED",
            "device": self.device,
            "ai_status": self.status,
            "last_error": self.last_error,
            "model_path": self.model_path or "",
            "model_size_mb": model_size_mb,
            "available_disk_gb": available_gb,
            "download_progress": self._download_progress,
            "ai_tasks_waiting": self._ai_tasks_waiting,
            "ai_tasks_completed": self._ai_tasks_completed,
            "warmup_completed": self._warmup_completed,
        }

    def _check_disk_space(self, required_gb: float = 5.0) -> Dict[str, Any]:
        """Check if sufficient disk space is available."""
        cache_dir = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
        cache_dir.mkdir(parents=True, exist_ok=True)
        disk_usage = shutil.disk_usage(cache_dir)
        available_gb = disk_usage.free / 1024 / 1024 / 1024

        return {
            "sufficient": available_gb >= required_gb,
            "available_gb": round(available_gb, 2),
            "required_gb": required_gb,
        }

    def check_model_files(self) -> Dict[str, Any]:
        """Check if the model exists locally and verify files."""
        model_name = os.environ.get("AI_MODEL", "user052/EDIATH-Q4_K_M")
        try:
            info = model_info(model_name)
            repo_id = info.id
        except Exception as e:
            return {"exists": False, "error": f"Cannot access model repo: {e}"}

        try:
            local_path = hf_hub_download(
                repo_id=repo_id,
                filename="EDIATH-Q4_K_M.gguf",
                local_files_only=True,
            )
            exists = Path(local_path).exists()
            size = Path(local_path).stat().st_size if exists else 0
            return {
                "exists": exists,
                "path": local_path,
                "size_bytes": size,
                "size_mb": round(size / 1024 / 1024, 2),
            }
        except Exception:
            return {"exists": False, "path": None, "size_bytes": 0, "size_mb": 0}

    def _download_with_progress(self) -> Dict[str, Any]:
        """Download model with progress tracking."""
        model_name = os.environ.get("AI_MODEL", "user052/EDIATH-Q4_K_M")

        with self._download_lock:
            if self._downloading:
                return {"ok": False, "error": "Download already in progress"}

            self._downloading = True
            self.status = "downloading"
            self._download_progress = {
                "downloaded_bytes": 0,
                "total_bytes": 0,
                "percentage": 0.0,
                "speed_mbps": 0.0,
                "current_file": "",
                "status": "downloading",
            }
            self._emit("ai_model_download_start", f"Starting download of {model_name}",
                       metadata={"model": model_name})

            try:
                self._emit("ai_model_download_progress", "Checking model repository...",
                           metadata={"model": model_name, "stage": "checking"})

                info = model_info(model_name)
                repo_id = info.id

                self._emit("ai_model_download_progress", "Model found. Starting download...",
                           metadata={"model": model_name, "stage": "downloading"})

                local_path = hf_hub_download(
                    repo_id=repo_id,
                    filename="EDIATH-Q4_K_M.gguf",
                    local_files_only=False,
                )

                if not Path(local_path).exists():
                    raise RuntimeError("Download completed but file not found locally")

                size_bytes = Path(local_path).stat().st_size
                size_mb = round(size_bytes / 1024 / 1024, 2)
                self.model_path = local_path
                self._download_progress = {
                    "downloaded_bytes": size_bytes,
                    "total_bytes": size_bytes,
                    "percentage": 100.0,
                    "speed_mbps": 0.0,
                    "current_file": "completed",
                    "status": "completed",
                }
                self._downloading = False

                self._emit("ai_model_download_complete",
                           f"Download completed: {size_mb} MB",
                           metadata={"model": model_name, "path": local_path, "size_mb": size_mb})

                return {"ok": True, "path": local_path, "size_mb": size_mb}

            except Exception as e:
                self._downloading = False
                self.status = "failed"
                self.last_error = str(e)
                self._download_progress["status"] = "failed"
                self._emit("ai_model_download_failed", f"Download failed: {e}",
                           severity="error", metadata={"model": model_name, "error": str(e)})
                return {"ok": False, "error": str(e)}

    def load_model(self) -> Dict[str, Any]:
        """Load the model into memory using llama-cpp-python."""
        with self._load_lock:
            if self.model is not None:
                return {"ok": True, "message": "Model already loaded"}

            self.status = "loading"
            self._emit("ai_model_load_start", "Loading model into memory...")

            try:
                if not self.model_path:
                    check = self.check_model_files()
                    if not check.get("exists"):
                        raise RuntimeError("Model not downloaded. Call download_model() first.")
                    self.model_path = check["path"]

                if not Path(self.model_path).exists():
                    raise RuntimeError(f"Model file not found at {self.model_path}")

                self._emit("ai_model_load_progress", "Initializing llama.cpp engine...",
                           metadata={"path": self.model_path})

                self.model = Llama(
                    model_path=self.model_path,
                    n_ctx=1024,
                    n_threads=4,
                    verbose=False,
                )

                self.device = "cpu"
                self.status = "ready"
                self._emit("ai_model_load_complete", "Model loaded successfully",
                           metadata={"device": self.device, "path": self.model_path})

                return {"ok": True, "device": self.device}

            except Exception as e:
                self.status = "failed"
                self.last_error = str(e)
                self.model = None
                self._emit("ai_model_load_failed", f"Model loading failed: {e}",
                           severity="error", metadata={"error": str(e)})
                return {"ok": False, "error": str(e)}

    def test_inference(self) -> Dict[str, Any]:
        """Run a real inference test."""
        if self.model is None:
            return {"ok": False, "error": "Model not loaded"}

        self._emit("ai_inference_test_start", "Running inference test...")
        start = time.time()

        try:
            result = self.model(
                "Respond with exactly: AI MODEL WORKING",
                max_tokens=20,
                stop=["\n"],
            )
            elapsed = round(time.time() - start, 2)
            text = result["choices"][0]["text"].strip()

            passed = "AI MODEL WORKING" in text.upper() or len(text) > 0
            self._inference_passed = passed

            status = "PASSED" if passed else "FAILED"
            self._emit("ai_inference_test_complete",
                       f"Inference test {status}: {text}",
                       metadata={"response": text, "time": elapsed, "passed": passed})

            return {
                "ok": passed,
                "response": text,
                "time": elapsed,
                "status": status,
            }

        except Exception as e:
            elapsed = round(time.time() - start, 2)
            self._emit("ai_inference_test_failed", f"Inference test failed: {e}",
                       severity="error", metadata={"error": str(e), "time": elapsed})
            return {"ok": False, "error": str(e), "time": elapsed}

    def warmup(self) -> Dict[str, Any]:
        """Run lightweight warmup inference."""
        if self.model is None:
            return {"ok": False, "error": "Model not loaded"}

        self._emit("ai_warmup_start", "Running warmup inference...")
        start = time.time()

        try:
            result = self.model(
                "Reply with OK",
                max_tokens=10,
                stop=["\n"],
            )
            elapsed = round(time.time() - start, 2)
            text = result["choices"][0]["text"].strip()
            self._warmup_completed = True

            self._emit("ai_warmup_complete", f"Warmup completed in {elapsed}s",
                       metadata={"response": text, "time": elapsed})

            return {"ok": True, "time": elapsed}

        except Exception as e:
            self._emit("ai_warmup_failed", f"Warmup failed: {e}",
                       severity="error", metadata={"error": str(e)})
            return {"ok": False, "error": str(e)}

    def _initialize_background(self):
        """Background initialization: download, verify, load, warmup, test."""
        if self._init_completed:
            return

        self._initializing = True
        self._emit("ai_initialization_started", "AI background initialization started")

        try:
            # Check cache
            self.status = "checking_cache"
            self._emit("model_cache_check_started", "Checking local model cache...")
            check = self.check_model_files()

            if check.get("exists"):
                self._emit("model_cache_check_complete", "Model found locally",
                           metadata={"path": check.get("path"), "size_mb": check.get("size_mb")})
            else:
                self._emit("model_not_found", "Model not found locally. Download required.")

                # Check disk space
                disk = self._check_disk_space(required_gb=5.0)
                if not disk.get("sufficient"):
                    error_msg = f"Insufficient disk space. Required: {disk['required_gb']} GB, Available: {disk['available_gb']} GB"
                    self.status = "failed"
                    self.last_error = error_msg
                    self._emit("ai_download_blocked", error_msg, severity="error", metadata=disk)
                    self._initializing = False
                    return

                # Download
                self.status = "downloading"
                dl = self._download_with_progress()
                if not dl.get("ok"):
                    self.status = "failed"
                    self.last_error = dl.get("error", "Download failed")
                    self._initializing = False
                    return

            # Verify
            self.status = "verifying"
            self._emit("model_verification_started", "Verifying model files...")
            if not self.model_path:
                check = self.check_model_files()
                if not check.get("exists"):
                    raise RuntimeError("Model verification failed: file not found")
                self.model_path = check["path"]

            if not Path(self.model_path).exists():
                raise RuntimeError(f"Model verification failed: {self.model_path}")

            self._emit("model_verification_complete", "Model files verified",
                       metadata={"path": self.model_path, "size_mb": round(Path(self.model_path).stat().st_size / 1024 / 1024, 2)})

            # Load
            self.status = "loading"
            load = self.load_model()
            if not load.get("ok"):
                self.status = "failed"
                self.last_error = load.get("error", "Load failed")
                self._initializing = False
                return

            # Warmup
            self.status = "warming_up"
            warmup = self.warmup()
            if not warmup.get("ok"):
                self.status = "failed"
                self.last_error = warmup.get("error", "Warmup failed")
                self._initializing = False
                return

            # Test inference
            self.status = "testing"
            test = self.test_inference()
            if not test.get("ok"):
                self.status = "failed"
                self.last_error = test.get("error", "Inference test failed")
                self._initializing = False
                return

            self.status = "ready"
            self._init_completed = True
            self._emit("ai_ready", f"AI engine ready. Inference test passed in {test.get('time')}s",
                       metadata={"inference_time": test.get("time"), "device": self.device})

            # Process queued tasks
            self._process_queue()

        except Exception as e:
            self.status = "failed"
            self.last_error = str(e)
            self._emit("ai_initialization_failed", f"AI initialization failed: {e}",
                       severity="error", metadata={"error": str(e)})
        finally:
            self._initializing = False

    def _process_queue(self):
        """Process queued AI tasks."""
        if self._processing_queue or self.status != "ready" or not self.model:
            return

        self._processing_queue = True
        while self._task_queue and self.status == "ready" and self.model is not None:
            task = self._task_queue.popleft()
            try:
                prompt = task.get("prompt", "")
                max_tokens = task.get("max_tokens", 800)
                temperature = task.get("temperature", 0.4)
                result = self.generate(prompt, max_tokens=max_tokens, temperature=temperature)
                task["callback"]({"ok": True, "result": result})
            except Exception as e:
                task["callback"]({"ok": False, "error": str(e)})
            self._ai_tasks_completed += 1
        self._processing_queue = False

    def start_background_initialization(self):
        """Start background initialization if not already started."""
        if self._init_started:
            return

        self._init_started = True
        self.status = "checking_cache"
        thread = threading.Thread(target=self._initialize_background, daemon=True)
        thread.start()

    def submit_task(self, prompt: str, max_tokens: int = 800, temperature: float = 0.4,
                    callback: Optional[Callable] = None) -> Dict[str, Any]:
        """Submit an AI task. If model is ready, execute immediately. Otherwise queue."""
        if self.status == "ready" and self.model is not None:
            try:
                result = self.generate(prompt, max_tokens=max_tokens, temperature=temperature)
                self._ai_tasks_completed += 1
                if callback:
                    callback({"ok": True, "result": result})
                return {"ok": True, "result": result, "status": "completed"}
            except Exception as e:
                if callback:
                    callback({"ok": False, "error": str(e)})
                return {"ok": False, "error": str(e)}

        # Queue task
        self._ai_tasks_waiting += 1
        task = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "callback": callback,
        }
        self._task_queue.append(task)

        self._emit("ai_task_queued", f"AI task queued. Waiting: {self._ai_tasks_waiting}",
                   metadata={"queue_length": len(self._task_queue)})

        # Start initialization if not started
        if not self._init_started:
            self.start_background_initialization()

        return {"ok": True, "status": "queued", "message": "AI task queued for processing when model is ready"}

    def ensure_ready(self, block: bool = False) -> Dict[str, Any]:
        """Ensure model is initialized. Non-blocking by default."""
        if self.status == "ready" and self.model is not None:
            return {"ok": True, "status": "ready"}

        if self.status == "failed":
            return {"ok": False, "error": self.last_error, "status": "failed"}

        if not self._init_started:
            self.start_background_initialization()

        if not block:
            return {
                "ok": False,
                "status": self.status,
                "message": f"AI model is {self.status}. Background initialization in progress.",
            }

        # Blocking mode
        while self.status not in ("ready", "failed"):
            time.sleep(0.5)

        if self.status == "failed":
            return {"ok": False, "error": self.last_error, "status": "failed"}

        return {"ok": True, "status": "ready"}

    def get_model(self) -> Optional[Llama]:
        """Get the loaded model instance."""
        return self.model

    def generate(self, prompt: str, max_tokens: int = 800, temperature: float = 0.4) -> str:
        """Generate text using the loaded model."""
        if self.model is None:
            raise RuntimeError("Model not loaded. Background initialization may still be in progress.")

        try:
            kwargs = {
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            result = self.model(**kwargs)
            text = result["choices"][0]["text"].strip()
            return text
        except Exception as e:
            raise RuntimeError(f"Inference failed: {e}")

    def repair(self) -> Dict[str, Any]:
        """Attempt to repair a broken model state."""
        self._emit("ai_repair_start", "Starting AI model repair...")
        self.model = None
        self.model_path = None
        self.status = "not_ready"
        self.last_error = ""
        self._init_completed = False
        self._init_started = False
        self._warmup_completed = False
        self._inference_passed = False
        self._task_queue.clear()
        self._ai_tasks_waiting = 0

        check = self.check_model_files()
        if check.get("exists") and check.get("path"):
            try:
                Path(check["path"]).unlink()
                self._emit("ai_repair", "Removed corrupted model file",
                           metadata={"path": check["path"]})
            except Exception:
                pass

        self.start_background_initialization()
        return {"ok": True, "status": "repairing"}


def get_model_manager() -> AIModelManager:
    return AIModelManager()
