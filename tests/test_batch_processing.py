import os
import io
import pytest
import numpy as np
from fastapi.testclient import TestClient
from api.index import app
from app.storage import FileRegistry

client = TestClient(app)

def create_dummy_wav(duration_s=0.01, fs=2000000.0, tone_hz=20000.0) -> bytes:
    """Generates a small valid complex baseband float32 I/Q byte buffer."""
    t = np.arange(int(fs * duration_s)) / fs
    sig = np.exp(1j * 2 * np.pi * tone_hz * t).astype(np.complex64)
    interleaved = np.empty(len(sig) * 2, dtype=np.float32)
    interleaved[0::2] = np.real(sig)
    interleaved[1::2] = np.imag(sig)
    return interleaved.tobytes()

@pytest.fixture(autouse=True)
def setup_teardown():
    FileRegistry.clear_all()
    yield
    FileRegistry.clear_all()

def test_batch_upload():
    raw1 = create_dummy_wav(0.005, tone_hz=10000.0)
    raw2 = create_dummy_wav(0.005, tone_hz=30000.0)
    
    files = [
        ("files", ("test_signal_1.iq", io.BytesIO(raw1), "application/octet-stream")),
        ("files", ("test_signal_2.iq", io.BytesIO(raw2), "application/octet-stream"))
    ]
    
    res = client.post("/api/v1/files/upload-batch", files=files, data={"sample_rate": "2000000", "center_freq": "434500000"})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["uploaded_count"] == 2
    assert len(data["files"]) == 2
    assert data["files"][0]["status"] == "QUEUED"
    assert data["files"][1]["status"] == "QUEUED"

def test_batch_pipeline_run():
    raw1 = create_dummy_wav(0.005, tone_hz=15000.0)
    raw2 = create_dummy_wav(0.005, tone_hz=25000.0)
    
    files = [
        ("files", ("burst_alpha.iq", io.BytesIO(raw1), "application/octet-stream")),
        ("files", ("burst_bravo.iq", io.BytesIO(raw2), "application/octet-stream"))
    ]
    
    res_upload = client.post("/api/v1/files/upload-batch", files=files)
    assert res_upload.status_code == 200
    upload_data = res_upload.json()
    fids = [f["file_id"] for f in upload_data["files"]]
    
    # Run batch pipeline
    res_batch = client.post("/api/v1/pipeline/run-batch", json={"file_ids": fids})
    assert res_batch.status_code == 200, res_batch.text
    batch_data = res_batch.json()
    assert batch_data["status"] == "SUCCESS"
    assert batch_data["processed_count"] == 2
    
    # Verify each file's status in registry is now ANALYZED
    for fid in fids:
        rec = FileRegistry.get_by_id(fid)
        assert rec is not None
        assert rec["status"] == "ANALYZED"
        assert rec["analysis_summary"] is not None
        assert "modulation" in rec["analysis_summary"]

def test_select_cached_analysis():
    raw = create_dummy_wav(0.005, tone_hz=15000.0)
    res_upload = client.post("/api/v1/files/upload-batch", files=[("files", ("cached_test.iq", io.BytesIO(raw), "application/octet-stream"))])
    fid = res_upload.json()["files"][0]["file_id"]
    
    # Run batch
    client.post("/api/v1/pipeline/run-batch", json={"file_ids": [fid]})
    
    # Selecting the file should return cached: True
    res_select = client.post("/api/v1/files/select", json={"file_id": fid})
    assert res_select.status_code == 200
    sel_data = res_select.json()
    assert sel_data["status"] == "SUCCESS"
    assert sel_data["cached"] is True
    assert sel_data["analysis"]["file_id"] == fid

def test_batch_report_export_csv_and_json():
    raw1 = create_dummy_wav(0.005, tone_hz=12000.0)
    raw2 = create_dummy_wav(0.005, tone_hz=24000.0)
    
    res_upload = client.post("/api/v1/files/upload-batch", files=[
        ("files", ("stream_1.iq", io.BytesIO(raw1), "application/octet-stream")),
        ("files", ("stream_2.iq", io.BytesIO(raw2), "application/octet-stream"))
    ])
    client.post("/api/v1/pipeline/run-batch", json={})
    
    # Export CSV
    res_csv = client.get("/api/v1/report/batch-export?format=csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["content-type"]
    assert "stream_1.iq" in res_csv.text
    assert "stream_2.iq" in res_csv.text
    assert "ELVYN Multi-Signal Intelligence Ledger" in res_csv.text
    
    # Export JSON
    res_json = client.get("/api/v1/report/batch-export?format=json")
    assert res_json.status_code == 200
    j_data = res_json.json()
    assert "total_records" in j_data
    assert j_data["total_records"] == 2
    assert j_data["analyzed_count"] == 2
    assert len(j_data["records"]) == 2

def test_pipeline_run_file_endpoint():
    raw = create_dummy_wav(0.005, tone_hz=22000.0)
    res_upload = client.post("/api/v1/files/upload-batch", files=[("files", ("single_run.iq", io.BytesIO(raw), "application/octet-stream"))])
    fid = res_upload.json()["files"][0]["file_id"]

    res_run = client.post(f"/api/v1/pipeline/run-file/{fid}")
    assert res_run.status_code == 200
    data = res_run.json()
    assert data["status"] == "SUCCESS"
    assert data["file_id"] == fid
    assert "analysis" in data
    assert data["analysis"]["file_id"] == fid

    # Check cached
    res_select = client.post("/api/v1/files/select", json={"file_id": fid})
    assert res_select.status_code == 200
    assert res_select.json()["cached"] is True

def test_single_file_upload_regression():
    raw = create_dummy_wav(0.005, tone_hz=18000.0)
    res = client.post(
        "/api/v1/files/upload",
        files={"file": ("single_reg.iq", io.BytesIO(raw), "application/octet-stream")},
        data={"sample_rate": "2000000", "center_freq": "434500000"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert "analysis" in data
    fid = data["analysis"]["file_id"]

    # Verify cached
    res_select = client.post("/api/v1/files/select", json={"file_id": fid})
    assert res_select.status_code == 200
    assert res_select.json()["cached"] is True

def test_signal_synthesis_and_caching():
    res = client.post("/api/v1/signals/synthesize", json={"profile": "Profile A"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert "analysis" in data
    fid = data["analysis"]["file_id"]

    # Re-select synthesized file immediately from cache
    res_select = client.post("/api/v1/files/select", json={"file_id": fid})
    assert res_select.status_code == 200
    assert res_select.json()["cached"] is True

