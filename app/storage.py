import os
import json
import uuid
import datetime
import shutil

# In serverless environments (like Vercel), only /tmp is writable
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    DATA_DIR = "/tmp/sih26147_data"
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
REGISTRY_PATH = os.path.join(DATA_DIR, "registry.json")

# In-memory registry fallback for resilient serverless operation
_IN_MEMORY_REGISTRY = []
_IN_MEMORY_FILES = {}

def init_storage():
    try:
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        if not os.path.exists(REGISTRY_PATH):
            with open(REGISTRY_PATH, "w") as f:
                json.dump([], f, indent=2)
    except Exception:
        pass

def load_registry() -> list:
    init_storage()
    try:
        if os.path.exists(REGISTRY_PATH):
            with open(REGISTRY_PATH, "r") as f:
                records = json.load(f)
                return records
    except Exception:
        pass
    return _IN_MEMORY_REGISTRY

def save_registry(records: list):
    global _IN_MEMORY_REGISTRY
    _IN_MEMORY_REGISTRY = records
    try:
        init_storage()
        with open(REGISTRY_PATH, "w") as f:
            json.dump(records, f, indent=2)
    except Exception:
        pass

class FileRegistry:
    @staticmethod
    def save_and_log_upload(filename: str, file_bytes: bytes, sample_rate: float = 2.0e6, center_freq: float = 434.5e6, format_hint: str = "auto") -> dict:
        init_storage()
        file_id = str(uuid.uuid4())
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")
        stored_filename = f"{file_id[:8]}_{safe_name}"
        stored_path = os.path.join(UPLOADS_DIR, stored_filename)

        # Store in memory for instant serverless recall
        _IN_MEMORY_FILES[file_id] = file_bytes

        # Attempt writing to disk / /tmp
        try:
            with open(stored_path, "wb") as f:
                f.write(file_bytes)
        except Exception:
            stored_path = f"memory://{stored_filename}"

        file_size = len(file_bytes)
        size_str = f"{file_size / 1024:.1f} KB" if file_size < 1024*1024 else f"{file_size / (1024*1024):.2f} MB"
        
        now = datetime.datetime.now()
        timestamp_iso = now.isoformat()
        timestamp_formatted = now.strftime("%Y-%m-%d %H:%M:%S")

        # Auto-detect format label
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".wav":
            fmt_label = "Complex WAV (RIFF/PCM)"
        elif ext in [".iq", ".raw", ".bin"]:
            fmt_label = "Raw I/Q Baseband"
        elif ext == ".dat":
            fmt_label = "GNU Radio Binary Stream"
        elif ext in [".sigmf", ".sigmf-data"]:
            fmt_label = "SigMF Standard Data"
        else:
            fmt_label = f"Binary Stream ({ext})"

        record = {
            "file_id": file_id,
            "filename": filename,
            "stored_filename": stored_filename,
            "stored_path": stored_path,
            "size_bytes": file_size,
            "size_formatted": size_str,
            "upload_timestamp": timestamp_iso,
            "upload_time_formatted": timestamp_formatted,
            "sample_rate": float(sample_rate),
            "center_freq": float(center_freq),
            "format_detected": fmt_label,
            "status": "UPLOADED",
            "analysis_summary": None
        }

        records = load_registry()
        records.insert(0, record)
        save_registry(records)
        return record

    @staticmethod
    def get_file_bytes(file_id: str) -> bytes | None:
        if file_id in _IN_MEMORY_FILES:
            return _IN_MEMORY_FILES[file_id]
        record = FileRegistry.get_by_id(file_id)
        if record and record.get("stored_path") and os.path.exists(record["stored_path"]):
            with open(record["stored_path"], "rb") as f:
                return f.read()
        return None

    @staticmethod
    def list_all() -> list:
        return load_registry()

    @staticmethod
    def get_by_id(file_id: str) -> dict | None:
        records = load_registry()
        for r in records:
            if r["file_id"] == file_id:
                return r
        return None

    @staticmethod
    def update_analysis(file_id: str, summary: dict):
        records = load_registry()
        for r in records:
            if r["file_id"] == file_id:
                r["analysis_summary"] = summary
                r["status"] = "ANALYZED"
                break
        save_registry(records)

    @staticmethod
    def delete(file_id: str) -> bool:
        global _IN_MEMORY_FILES
        _IN_MEMORY_FILES.pop(file_id, None)
        records = load_registry()
        record_to_del = None
        new_records = []
        for r in records:
            if r["file_id"] == file_id:
                record_to_del = r
            else:
                new_records.append(r)
        
        if record_to_del:
            save_registry(new_records)
            stored_path = record_to_del.get("stored_path")
            if stored_path and not stored_path.startswith("memory://") and os.path.exists(stored_path):
                try:
                    os.remove(stored_path)
                except Exception:
                    pass
            return True
        return False

    @staticmethod
    def delete_by_id(file_id: str) -> bool:
        return FileRegistry.delete(file_id)

    @staticmethod
    def clear_all():
        global _IN_MEMORY_FILES
        _IN_MEMORY_FILES.clear()
        save_registry([])
        try:
            if os.path.exists(UPLOADS_DIR):
                shutil.rmtree(UPLOADS_DIR, ignore_errors=True)
                os.makedirs(UPLOADS_DIR, exist_ok=True)
        except Exception:
            pass
