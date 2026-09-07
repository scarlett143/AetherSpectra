import os
import io
import time
import json
import uuid
import numpy as np
from fastapi import FastAPI, UploadFile, File, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.storage import FileRegistry, init_storage
from app.report_generator import ReportGenerator
from app.dsp.signal_loader import SignalLoader
from app.dsp.synthetic_signals import SyntheticSignalGenerator
from app.dsp.filtering import SignalFilter
from app.dsp.fft_stage import FFTAnalyzer
from app.dsp.frequency_estimator import FrequencyEstimator
from app.dsp.synchronization import CarrierAndTimingSync
from app.dsp.amc_classifier import AMCClassifier
from app.dsp.noise_estimator import NoiseEstimator
from app.dsp.symbol_demodulator import SymbolDemodulator
from app.dsp.signal_classifier import SignalClassifier

def to_serializable(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.floating, np.float32, np.float64)):
        return float(obj)
    elif isinstance(obj, (np.integer, np.int32, np.int64, np.uint8)):
        return int(obj)
    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    elif isinstance(obj, (np.complex64, np.complex128, complex)):
        return {"real": float(obj.real), "imag": float(obj.imag)}
    elif isinstance(obj, dict):
        return {k: to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [to_serializable(i) for i in obj]
    elif isinstance(obj, bytes):
        return list(obj)
    return obj

app = FastAPI(title="AetherSpectra Signal Intelligence Platform", version="3.0")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(BASE_DIR, "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Initialize storage directories on boot
init_storage()

# Dynamic Active Session State (Starts Completely Fresh)
ACTIVE_SESSION = {
    "file_id": None,
    "filename": None,
    "stored_path": None,
    "raw_iq": None,
    "sample_rate": 2.0e6,
    "center_freq": 434.5e6,
    "format_desc": None,
    "pipeline_results": None,
    "status": "IDLE"
}

def execute_pipeline_on_iq(raw_iq: np.ndarray, fs: float, fc: float, filename: str, file_id: str | None = None) -> dict:
    """Executes the exact 8-stage DSP radio signal processing and intelligence pipeline in order:
    1. Filtering
    2. FFT
    3. Frequency Estimation
    4. Synchronization
    5. Modulation Detection
    6. Noise Estimation
    7. Demodulation
    8. Signal Classification
    """
    start_time = time.time()
    
    # 1. Filtering (Butterworth Bandpass/Lowpass, DC offset removal, Gram-Schmidt IQ balance, RMS normalization)
    t0 = time.time()
    filtered_iq, filter_stats = SignalFilter.apply_filter(raw_iq, fs)
    lat_filtering = round((time.time() - t0) * 1000, 2)

    # 2. FFT (Fast Fourier Transform, Peak detection, Welch PSD, STFT Spectrogram, Spectral Flatness)
    t0 = time.time()
    fft_stats = FFTAnalyzer.process_fft(filtered_iq, fs)
    lat_fft = round((time.time() - t0) * 1000, 2)

    # 3. Frequency estimation (Coarse/Fine carrier frequency, CFO, 99% OBW, -3dB Bandwidth, Baud/Symbol Rate)
    t0 = time.time()
    freq_stats = FrequencyEstimator.estimate(filtered_iq, fs, fc)
    lat_freq_est = round((time.time() - t0) * 1000, 2)

    # 4. Synchronization (Gardner symbol timing sync, Costas carrier recovery loop, EVM RMS & dB, Eye diagram)
    t0 = time.time()
    sps_val = max(2, int(round(freq_stats.get("samples_per_symbol", 8.0))))
    sync_res = CarrierAndTimingSync.sync_signal(filtered_iq, "QPSK", sps_val)
    lat_sync = round((time.time() - t0) * 1000, 2)

    # 5. Modulation detection (Higher-order cumulants C20/C40/C42, Kurtosis, AMC Probabilities & Classification)
    t0 = time.time()
    amc_res = AMCClassifier.classify(filtered_iq, 15.0)
    if amc_res["identified_modulation"] != "QPSK":
        sync_res = CarrierAndTimingSync.sync_signal(filtered_iq, amc_res["identified_modulation"], sps_val)
    lat_mod_det = round((time.time() - t0) * 1000, 2)

    # 6. Noise estimation (M2M4 moment SNR, Split-Symbol Moment Estimator SSME, Noise floor N0, Noise variance)
    t0 = time.time()
    noise_stats = NoiseEstimator.estimate_noise(filtered_iq, fs, sync_res.get("evm_db"))
    lat_noise_est = round((time.time() - t0) * 1000, 2)

    # 7. Demodulation (Gray constellation demapping to bits, soft LLRs, decision regions)
    t0 = time.time()
    demod_res = SymbolDemodulator.demodulate(filtered_iq[::sps_val], amc_res["identified_modulation"])
    raw_bits = sync_res.get("raw_sliced_bits") or demod_res["bits"]
    soft_llrs = sync_res.get("soft_llrs") or demod_res["soft_llrs"]
    lat_demod = round((time.time() - t0) * 1000, 2)

    # 8. Signal classification (Standard / Emitter classification, Frame sync, Descramble, CRC, Telemetry extraction)
    t0 = time.time()
    class_res = SignalClassifier.classify_and_extract(raw_bits, soft_llrs, amc_res["identified_modulation"], filename)
    lat_sig_class = round((time.time() - t0) * 1000, 2)

    total_latency = round((time.time() - start_time) * 1000, 2)

    # Time-series Waveform samples for charting
    wf_samples = min(len(filtered_iq), 600)
    wf_i = np.real(filtered_iq[:wf_samples]).tolist()
    wf_q = np.imag(filtered_iq[:wf_samples]).tolist()
    wf_t = (np.arange(wf_samples) / fs * 1000.0).tolist()

    result = {
        "file_id": file_id,
        "filename": filename,
        "total_latency_ms": total_latency,
        "sample_count": len(raw_iq),
        "latencies": {
            "filtering": lat_filtering,
            "fft": lat_fft,
            "frequency_estimation": lat_freq_est,
            "synchronization": lat_sync,
            "modulation_detection": lat_mod_det,
            "noise_estimation": lat_noise_est,
            "demodulation": lat_demod,
            "signal_classification": lat_sig_class
        },
        "waveform": {"time_ms": wf_t, "i": wf_i, "q": wf_q},
        "psd": fft_stats["psd"],
        "spectrogram": fft_stats["spectrogram"],
        "fft_features": {
            "fft_points": fft_stats["fft_points"],
            "peak_frequency_hz": fft_stats["peak_frequency_hz"],
            "peak_power_db": fft_stats["peak_power_db"],
            "spectral_flatness": fft_stats["spectral_flatness"],
            "dynamic_range_db": fft_stats["dynamic_range_db"]
        },
        "filtering_stats": filter_stats,
        "parameters": {
            "carrier_freq_hz": freq_stats["carrier_freq_hz"],
            "carrier_offset_hz": freq_stats["carrier_offset_hz"],
            "cfo_residual_hz": freq_stats["cfo_residual_hz"],
            "occupied_bandwidth_99_hz": freq_stats["occupied_bandwidth_99_hz"],
            "bandwidth_3db_hz": freq_stats["bandwidth_3db_hz"],
            "symbol_rate_baud": freq_stats["symbol_rate_baud"],
            "samples_per_symbol": freq_stats["samples_per_symbol"],
            "snr_db": noise_stats["snr_db"]
        },
        "frequency_estimation": freq_stats,
        "amc": amc_res,
        "noise_estimation": noise_stats,
        "preprocessing_stats": {
            "snr_m2m4_db": noise_stats["snr_m2m4_db"],
            "dc_offset_i": filter_stats["dc_offset_i"],
            "dc_offset_q": filter_stats["dc_offset_q"],
            "iq_phase_imbalance_rad": filter_stats["iq_phase_imbalance_rad"],
            "rms_level": filter_stats["rms_level"]
        },
        "synchronization": {
            "constellation_i": sync_res["constellation_i"],
            "constellation_q": sync_res["constellation_q"],
            "evm_rms_pct": sync_res["evm_rms_pct"],
            "evm_db": sync_res["evm_db"],
            "carrier_lock_status": sync_res["carrier_lock_status"],
            "eye_traces": sync_res["eye_traces"]
        },
        "demodulation": {
            "bit_count": demod_res["bit_count"],
            "symbol_count": demod_res["symbol_count"],
            "bits_per_symbol": demod_res["bits_per_symbol"]
        },
        "symbols_to_bits": {
            "bit_count": demod_res["bit_count"],
            "symbol_count": demod_res["symbol_count"],
            "bits_per_symbol": demod_res["bits_per_symbol"]
        },
        "signal_classification": {
            "classified_standard": class_res["classified_standard"],
            "emitter_category": class_res["emitter_category"],
            "classification_confidence_pct": class_res["classification_confidence_pct"],
            "threat_level": class_res["threat_level"]
        },
        "deinterleaver": class_res["deinterleaver"],
        "fec": class_res["fec"],
        "framing": class_res["framing"],
        "descrambler": class_res["descrambler"],
        "crc": class_res["crc"],
        "telemetry": class_res["telemetry"]
    }

    # Update summary in registry if file_id exists
    if file_id:
        summary = {
            "modulation": amc_res["identified_modulation"],
            "confidence": round(amc_res["confidence"] * 100, 1),
            "snr_db": round(noise_stats["snr_db"], 1),
            "carrier_offset_khz": round(freq_stats["carrier_offset_hz"] / 1e3, 2),
            "bandwidth_khz": round(freq_stats["occupied_bandwidth_99_hz"] / 1e3, 2),
            "carrier_lock": sync_res["carrier_lock_status"],
            "classified_standard": class_res["classified_standard"],
            "decoded_telemetry": class_res["telemetry"]["decoded_text"]
        }
        FileRegistry.update_analysis(file_id, summary)

    ACTIVE_SESSION["pipeline_results"] = result
    ACTIVE_SESSION["status"] = "ANALYSIS_COMPLETE"
    return to_serializable(result)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/v1/files")
async def list_files():
    """Returns the persistent audit log of all uploaded files."""
    records = FileRegistry.list_all()
    return {"files": records, "count": len(records), "active_file_id": ACTIVE_SESSION["file_id"]}

@app.post("/api/v1/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    sample_rate: float = Form(2.0e6),
    center_freq: float = Form(434.5e6)
):
    """Saves uploaded file to disk, records in audit log, and runs full analysis."""
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        return JSONResponse({"status": "ERROR", "message": "Uploaded file is empty"}, status_code=400)

    # 1. Save file to disk and record in audit registry
    record = FileRegistry.save_and_log_upload(
        filename=file.filename,
        file_bytes=file_bytes,
        sample_rate=sample_rate,
        center_freq=center_freq
    )

    # 2. Parse and stream signal from memory or stored disk file
    iq, fs_detected, fmt_desc = SignalLoader.load_from_bytes(file_bytes, filename=record["filename"], default_fs=sample_rate)

    # 3. Update session
    ACTIVE_SESSION["file_id"] = record["file_id"]
    ACTIVE_SESSION["filename"] = record["filename"]
    ACTIVE_SESSION["stored_path"] = record["stored_path"]
    ACTIVE_SESSION["raw_iq"] = iq
    ACTIVE_SESSION["sample_rate"] = fs_detected
    ACTIVE_SESSION["center_freq"] = center_freq
    ACTIVE_SESSION["format_desc"] = fmt_desc
    ACTIVE_SESSION["status"] = "ANALYZED"

    # 4. Execute pipeline
    analysis = execute_pipeline_on_iq(iq, fs_detected, center_freq, record["filename"], record["file_id"])
    ACTIVE_SESSION["pipeline_results"] = analysis

    return {
        "status": "SUCCESS",
        "file_record": record,
        "analysis": analysis
    }

@app.post("/api/v1/files/select")
async def select_file(payload: dict):
    """Activates an existing file from the audit log and runs analysis."""
    file_id = payload.get("file_id")
    record = FileRegistry.get_by_id(file_id)
    if not record:
        return JSONResponse({"status": "ERROR", "message": "File not found"}, status_code=404)

    file_bytes = FileRegistry.get_file_bytes(file_id)
    if file_bytes is not None:
        iq, fs_detected, fmt_desc = SignalLoader.load_from_bytes(file_bytes, filename=record["filename"], default_fs=record["sample_rate"])
    else:
        iq, fs_detected, fmt_desc = SignalLoader.load_from_disk(record["stored_path"], default_fs=record["sample_rate"])
    
    ACTIVE_SESSION["file_id"] = record["file_id"]
    ACTIVE_SESSION["filename"] = record["filename"]
    ACTIVE_SESSION["stored_path"] = record["stored_path"]
    ACTIVE_SESSION["raw_iq"] = iq
    ACTIVE_SESSION["sample_rate"] = fs_detected
    ACTIVE_SESSION["center_freq"] = record["center_freq"]
    ACTIVE_SESSION["format_desc"] = fmt_desc
    ACTIVE_SESSION["status"] = "ANALYZED"

    analysis = execute_pipeline_on_iq(iq, fs_detected, record["center_freq"], record["filename"], record["file_id"])
    ACTIVE_SESSION["pipeline_results"] = analysis

    return {
        "status": "SUCCESS",
        "file_record": record,
        "analysis": analysis
    }

@app.delete("/api/v1/files/{file_id}")
async def delete_file(file_id: str):
    """Deletes a file from disk and audit registry."""
    success = FileRegistry.delete_by_id(file_id)
    if ACTIVE_SESSION["file_id"] == file_id:
        ACTIVE_SESSION["file_id"] = None
        ACTIVE_SESSION["filename"] = None
        ACTIVE_SESSION["raw_iq"] = None
        ACTIVE_SESSION["pipeline_results"] = None
        ACTIVE_SESSION["status"] = "IDLE"
    return {"status": "SUCCESS" if success else "NOT_FOUND"}

@app.post("/api/v1/files/clear")
async def clear_all_files():
    """Wipes all uploaded files and audit logs to start completely fresh."""
    FileRegistry.clear_all_data()
    ACTIVE_SESSION["file_id"] = None
    ACTIVE_SESSION["filename"] = None
    ACTIVE_SESSION["raw_iq"] = None
    ACTIVE_SESSION["pipeline_results"] = None
    ACTIVE_SESSION["status"] = "IDLE"
    return {"status": "SUCCESS", "message": "All uploaded files and logs cleared"}

@app.post("/api/v1/signals/synthesize")
async def synthesize_new_signal(payload: dict):
    """Optional utility: Synthesizes a new signal, writes it to disk, and logs it in the registry."""
    p_name = payload.get("profile", "Profile A")
    sig = SyntheticSignalGenerator.generate_profile(p_name)
    
    # Save synthetic signal as raw float32 IQ file on disk
    iq = sig["raw_iq"]
    interleaved_f32 = np.empty(len(iq) * 2, dtype=np.float32)
    interleaved_f32[0::2] = np.real(iq)
    interleaved_f32[1::2] = np.imag(iq)
    file_bytes = interleaved_f32.tobytes()

    filename = f"synthetic_{p_name.lower().replace(' ', '_')}.iq"
    record = FileRegistry.save_and_log_upload(
        filename=filename,
        file_bytes=file_bytes,
        sample_rate=sig["sample_rate"],
        center_freq=sig["config"]["center_freq"]
    )

    ACTIVE_SESSION["file_id"] = record["file_id"]
    ACTIVE_SESSION["filename"] = record["filename"]
    ACTIVE_SESSION["stored_path"] = record["stored_path"]
    ACTIVE_SESSION["raw_iq"] = iq
    ACTIVE_SESSION["sample_rate"] = sig["sample_rate"]
    ACTIVE_SESSION["center_freq"] = sig["config"]["center_freq"]
    ACTIVE_SESSION["format_desc"] = "Synthesized Complex Float32 I/Q"
    ACTIVE_SESSION["status"] = "ANALYZED"

    analysis = execute_pipeline_on_iq(iq, sig["sample_rate"], sig["config"]["center_freq"], record["filename"], record["file_id"])
    ACTIVE_SESSION["pipeline_results"] = analysis

    return {
        "status": "SUCCESS",
        "file_record": record,
        "analysis": analysis
    }

@app.post("/api/v1/pipeline/run")
async def run_pipeline():
    """Re-runs the pipeline on currently active signal."""
    if ACTIVE_SESSION["raw_iq"] is None:
        return JSONResponse({"status": "ERROR", "message": "No active signal loaded. Please upload a file."}, status_code=400)

    analysis = execute_pipeline_on_iq(
        ACTIVE_SESSION["raw_iq"],
        ACTIVE_SESSION["sample_rate"],
        ACTIVE_SESSION["center_freq"],
        ACTIVE_SESSION["filename"] or "active_signal.iq",
        ACTIVE_SESSION["file_id"]
    )
    ACTIVE_SESSION["pipeline_results"] = analysis
    return analysis

@app.get("/api/v1/report/export")
async def export_report(format: str = Query("pdf")):
    """Unified endpoint to export reports in PDF, JSON, MD, DOCX, CSV, or HTML format."""
    res = ACTIVE_SESSION.get("pipeline_results")
    if not res:
        return JSONResponse({"status": "EMPTY", "message": "No active signal analysis results available. Upload/select a signal first."}, status_code=400)
    
    fmt = format.lower().strip()
    clean_name = os.path.splitext(res.get("filename", "signal"))[0]
    
    if fmt == "pdf":
        pdf_bytes = ReportGenerator.generate_pdf(res)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="NTRO_Report_{clean_name}.pdf"'}
        )
    elif fmt == "docx":
        docx_bytes = ReportGenerator.generate_docx(res)
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="NTRO_Report_{clean_name}.docx"'}
        )
    elif fmt == "csv":
        csv_str = ReportGenerator.generate_csv(res)
        return Response(
            content=csv_str,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="NTRO_Report_{clean_name}.csv"'}
        )
    elif fmt in ["md", "markdown"]:
        md_str = ReportGenerator.generate_markdown(res)
        return Response(
            content=md_str,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="NTRO_Report_{clean_name}.md"'}
        )
    elif fmt == "json":
        json_str = ReportGenerator.generate_json(res)
        return Response(
            content=json_str,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="NTRO_Report_{clean_name}.json"'}
        )
    elif fmt == "html":
        return await get_html_report()
    else:
        return JSONResponse({"status": "ERROR", "message": f"Unsupported export format '{format}'. Supported formats: pdf, json, md, docx, csv, html."}, status_code=400)

@app.get("/api/v1/report/pdf")
async def get_pdf_report():
    return await export_report(format="pdf")

@app.get("/api/v1/report/docx")
async def get_docx_report():
    return await export_report(format="docx")

@app.get("/api/v1/report/md")
async def get_md_report():
    return await export_report(format="md")

@app.get("/api/v1/report/csv")
async def get_csv_report():
    return await export_report(format="csv")

@app.get("/api/v1/report/json")
async def get_json_report(download: bool = Query(False)):
    res = ACTIVE_SESSION.get("pipeline_results")
    if not res:
        return JSONResponse({"status": "EMPTY", "message": "No analysis results available. Upload and analyze a file first."})
    if download:
        clean_name = os.path.splitext(res.get("filename", "signal"))[0]
        json_str = ReportGenerator.generate_json(res)
        return Response(
            content=json_str,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="NTRO_Report_{clean_name}.json"'}
        )
    return res

@app.get("/api/v1/report/html", response_class=HTMLResponse)
async def get_html_report():
    res = ACTIVE_SESSION.get("pipeline_results")
    if not res:
        return """
        <!DOCTYPE html>
        <html>
        <head><style>body { font-family: sans-serif; background: #090D16; color: #94A3B8; text-align: center; padding: 50px; }</style></head>
        <body>
            <h2>No Signal Analyzed Yet</h2>
            <p>Please upload a .IQ or .WAV file in the SIGINT workbench first.</p>
        </body>
        </html>
        """
    
    # Serialize data for client-side Plotly rendering in the report
    res_json_str = json.dumps(res)
    filename = res.get("filename", "Unknown")
    total_latency = res.get("total_latency_ms", 0)
    amc = res.get("amc", {})
    params = res.get("parameters", {})
    prep = res.get("preprocessing_stats", {})
    sync = res.get("synchronization", {})
    fec = res.get("fec", {})
    framing = res.get("framing", {})
    descramble = res.get("descrambler", {})
    crc = res.get("crc", {})
    telem = res.get("telemetry", {})
    latencies = res.get("latencies", {})
        
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AetherSpectra // Autonomous SIGINT & Telemetry Recovery Dossier - {filename}</title>
        <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
        <!-- Plotly CDN for big panel charts -->
        <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
        <!-- Tailwind CSS CDN -->
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            body {{ background-color: #090D16; color: #E2E8F0; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
            .card {{ background-color: #131C2E; border: 1px solid #1E293B; border-radius: 12px; padding: 20px; }}
            .glow-cyan {{ text-shadow: 0 0 10px rgba(56, 189, 248, 0.6); }}
            ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
            ::-webkit-scrollbar-track {{ background: #090D16; }}
            ::-webkit-scrollbar-thumb {{ background: #1E293B; border-radius: 3px; }}
        </style>
    </head>
    <body class="p-4 sm:p-8 max-w-7xl mx-auto space-y-6">

        <!-- Report Header -->
        <div class="card border-sky-500/30 flex flex-wrap items-center justify-between gap-4">
            <div class="flex items-center space-x-4">
                <img src="/static/logo.svg" alt="AetherSpectra Logo" class="w-12 h-12">
                <div>
                    <div class="flex items-center space-x-3">
                        <span class="text-xs bg-sky-950 border border-sky-500/40 text-sky-300 font-bold px-2.5 py-1 rounded tracking-wider">AETHERSPECTRA DEFENSE & RF LABS</span>
                        <span class="text-xs bg-emerald-950 border border-emerald-500/40 text-emerald-300 font-bold px-2.5 py-1 rounded">TACTICAL // 8-STAGE DSP</span>
                    </div>
                    <h1 class="text-xl sm:text-2xl font-black text-white mt-1.5 flex items-center gap-2">
                        <span>AETHER</span><span class="text-sky-400 glow-cyan">SPECTRA</span>
                        <span class="text-sm font-normal text-slate-400">| Signal Intelligence Dossier</span>
                    </h1>
                    <p class="text-xs text-slate-400 mt-0.5">Automated 8-Stage Filtering, FFT, Carrier/Timing Sync, Modulation Classification & Telemetry Recovery</p>
                </div>
            </div>
            <div class="text-right">
                <div class="text-xs text-slate-400">Target Signal File</div>
                <div class="text-base font-bold text-sky-400">{filename}</div>
                <div class="text-xs text-emerald-400 font-bold">Analysis Latency: {total_latency} ms</div>
            </div>
        </div>

        <!-- 12-Stage Executive Pipeline Status Grid -->
        <div class="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
            <div class="card p-3">
                <div class="text-[10px] text-slate-400 uppercase font-bold">1. Signal Ingest</div>
                <div class="text-xs font-bold text-white mt-1">{res.get('sample_count', 0):,} samples</div>
                <div class="text-[10px] text-emerald-400 mt-0.5">{latencies.get('read_iq', 0)} ms</div>
            </div>
            <div class="card p-3">
                <div class="text-[10px] text-slate-400 uppercase font-bold">2. Cleaning / SNR</div>
                <div class="text-xs font-bold text-white mt-1">{prep.get('snr_m2m4_db', 0):.1f} dB SNR</div>
                <div class="text-[10px] text-emerald-400 mt-0.5">{latencies.get('clean_signal', 0)} ms</div>
            </div>
            <div class="card p-3">
                <div class="text-[10px] text-slate-400 uppercase font-bold">3. Modulation AMC</div>
                <div class="text-xs font-bold text-sky-400 mt-1">{amc.get('identified_modulation', 'N/A')}</div>
                <div class="text-[10px] text-slate-400 mt-0.5">{round(amc.get('confidence', 0)*100, 1)}% Conf</div>
            </div>
            <div class="card p-3">
                <div class="text-[10px] text-slate-400 uppercase font-bold">4. Carrier Lock</div>
                <div class="text-xs font-bold text-emerald-400 mt-1">{sync.get('carrier_lock_status', 'N/A')}</div>
                <div class="text-[10px] text-slate-400 mt-0.5">{sync.get('evm_db', 'N/A')} dB EVM</div>
            </div>
            <div class="card p-3">
                <div class="text-[10px] text-slate-400 uppercase font-bold">5. FEC / Deinter</div>
                <div class="text-xs font-bold text-white mt-1">{fec.get('scheme', 'N/A')}</div>
                <div class="text-[10px] text-emerald-400 mt-0.5">{fec.get('corrected_errors', 0)} errs fixed</div>
            </div>
            <div class="card p-3">
                <div class="text-[10px] text-slate-400 uppercase font-bold">6. CRC Checksum</div>
                <div class="text-xs font-bold text-emerald-400 mt-1">{crc.get('status', 'VALID')}</div>
                <div class="text-[10px] text-slate-400 mt-0.5">{crc.get('computed_crc', '0x0000')}</div>
            </div>
        </div>

        <!-- BIG PANEL: Time-Frequency Waves & Spectral Visualizations -->
        <div class="space-y-6">
            
            <!-- 1. Raw Waveform (I/Q) -->
            <div class="card">
                <div class="flex items-center justify-between mb-3 border-b border-slate-800 pb-2">
                    <h3 class="font-bold text-sm text-sky-400 uppercase tracking-wider">1. In-Phase & Quadrature (I/Q) Baseband Waveform</h3>
                    <span class="text-xs text-slate-400">High-Resolution Time Series (ms)</span>
                </div>
                <div id="reportWaveformPlot" class="w-full h-72"></div>
            </div>

            <!-- 2. Power Spectral Density & Waterfall Spectrogram (2 Columns) -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <!-- Power Spectral Density -->
                <div class="card">
                    <div class="flex items-center justify-between mb-3 border-b border-slate-800 pb-2">
                        <h3 class="font-bold text-sm text-sky-400 uppercase tracking-wider">2. Power Spectral Density (PSD)</h3>
                        <span class="text-xs text-slate-400">Welch Periodogram</span>
                    </div>
                    <div id="reportPsdPlot" class="w-full h-72"></div>
                </div>

                <!-- 2D Waterfall Spectrogram -->
                <div class="card">
                    <div class="flex items-center justify-between mb-3 border-b border-slate-800 pb-2">
                        <h3 class="font-bold text-sm text-sky-400 uppercase tracking-wider">3. 2D Waterfall Spectrogram</h3>
                        <span class="text-xs text-slate-400">Time-Frequency Density</span>
                    </div>
                    <div id="reportSpecPlot" class="w-full h-72"></div>
                </div>
            </div>

            <!-- 3. Constellation & RF Parameters Grid -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <!-- Synchronized Constellation -->
                <div class="card">
                    <div class="flex items-center justify-between mb-3 border-b border-slate-800 pb-2">
                        <h3 class="font-bold text-sm text-emerald-400 uppercase tracking-wider">4. Synchronized I/Q Constellation Diagram</h3>
                        <span class="text-xs text-emerald-400 font-bold">{sync.get('carrier_lock_status', 'LOCKED')}</span>
                    </div>
                    <div id="reportConstellationPlot" class="w-full h-72"></div>
                </div>

                <!-- Physical Parameters & Higher-Order Cumulants Table -->
                <div class="card space-y-4">
                    <div class="border-b border-slate-800 pb-2">
                        <h3 class="font-bold text-sm text-sky-400 uppercase tracking-wider">5. Extracted Physical RF Parameters</h3>
                    </div>
                    <table class="w-full text-xs text-left border-collapse">
                        <thead>
                            <tr class="border-b border-slate-800 text-slate-400">
                                <th class="py-2">RF / Baseband Metric</th>
                                <th class="py-2">Value</th>
                                <th class="py-2">Unit</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-800 text-slate-300">
                            <tr><td class="py-1.5 font-bold">Center Frequency (fc)</td><td class="text-sky-400">{params.get('center_freq_hz', 0)/1e6:.4f}</td><td>MHz</td></tr>
                            <tr><td class="py-1.5 font-bold">Occupied 99% Bandwidth</td><td class="text-sky-400">{params.get('occupied_bw_99_hz', 0)/1e3:.2f}</td><td>kHz</td></tr>
                            <tr><td class="py-1.5 font-bold">Estimated Baud Rate (Rs)</td><td class="text-sky-400">{params.get('baud_rate_hz', 0)/1e3:.2f}</td><td>kBaud</td></tr>
                            <tr><td class="py-1.5 font-bold">Carrier Frequency Offset (CFO)</td><td class="text-sky-400">{params.get('cfo_estimated_hz', 0):.2f}</td><td>Hz</td></tr>
                            <tr><td class="py-1.5 font-bold">Estimated SNR (M2M4)</td><td class="text-sky-400">{prep.get('snr_m2m4_db', 0):.2f}</td><td>dB</td></tr>
                            <tr><td class="py-1.5 font-bold">Error Vector Magnitude (EVM)</td><td class="text-sky-400">{sync.get('evm_db', 0):.2f}</td><td>dB</td></tr>
                        </tbody>
                    </table>

                    <div class="pt-2 border-t border-slate-800">
                        <div class="text-[10px] text-slate-400 uppercase font-bold mb-1.5">Higher-Order Cumulants Features</div>
                        <div class="grid grid-cols-3 gap-2 text-xs bg-slate-900/80 p-2 rounded-lg border border-slate-800">
                            <div>C20: <span class="text-sky-400 font-bold">{amc.get('cumulants', {}).get('C20', 0):.2f}</span></div>
                            <div>C40: <span class="text-sky-400 font-bold">{amc.get('cumulants', {}).get('C40', 0):.2f}</span></div>
                            <div>C42: <span class="text-sky-400 font-bold">{amc.get('cumulants', {}).get('C42', 0):.2f}</span></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 4. Decoded Telemetry & Intelligence Stream -->
            <div class="card space-y-3">
                <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                    <h3 class="font-bold text-sm text-sky-400 uppercase tracking-wider">6. Recovered Plaintext Telemetry & Protocol Framing</h3>
                    <div class="space-x-2 text-xs">
                        <span class="bg-sky-950 border border-sky-500/40 text-sky-300 px-2 py-0.5 rounded">Frame: {framing.get('sync_marker', 'CCSDS ASM')}</span>
                        <span class="bg-emerald-950 border border-emerald-500/40 text-emerald-300 px-2 py-0.5 rounded">CRC: {crc.get('status', 'VALID')}</span>
                    </div>
                </div>

                <div class="bg-slate-900 border border-sky-500/30 rounded-xl p-4">
                    <div class="text-[10px] text-sky-400 uppercase font-bold tracking-wider mb-1">Decoded Intelligence Stream (ASCII)</div>
                    <div class="text-base font-bold text-cyan-300 glow-cyan break-all select-all">
                        {telem.get('decoded_text', 'NO_PAYLOAD_RECOVERED')}
                    </div>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                    <div class="bg-slate-900/80 p-3 rounded-lg border border-slate-800">
                        <div class="text-[10px] text-slate-400 uppercase font-bold mb-1">Raw Hex Byte Stream</div>
                        <div class="text-slate-300 break-all text-[11px] max-h-24 overflow-y-auto">
                            {telem.get('hex_dump', 'N/A')}
                        </div>
                    </div>
                    <div class="bg-slate-900/80 p-3 rounded-lg border border-slate-800">
                        <div class="text-[10px] text-slate-400 uppercase font-bold mb-1">De-Interleaver & Descrambler State</div>
                        <div class="text-slate-300 text-[11px] space-y-1">
                            <div>De-Interleaver: <span class="text-sky-400 font-bold">{res.get('deinterleaver', {}).get('selected', 'N/A')}</span></div>
                            <div>Descrambler: <span class="text-sky-400 font-bold">{descramble.get('scheme_applied', 'N/A')}</span></div>
                            <div>Corrected FEC Errors: <span class="text-emerald-400 font-bold">{fec.get('corrected_errors', 0)}</span> symbols</div>
                        </div>
                    </div>
                </div>
            </div>

        </div>

        <script>
            const data = {res_json_str};

            // 1. Raw Waveform Plot
            const traceI = {{
                x: data.waveform.time_ms,
                y: data.waveform.i,
                mode: 'lines',
                name: 'In-Phase (I)',
                line: {{ color: '#0284C7', width: 1.5 }}
            }};
            const traceQ = {{
                x: data.waveform.time_ms,
                y: data.waveform.q,
                mode: 'lines',
                name: 'Quadrature (Q)',
                line: {{ color: '#38BDF8', width: 1.5 }}
            }};
            Plotly.newPlot('reportWaveformPlot', [traceI, traceQ], {{
                margin: {{ t: 15, r: 15, b: 35, l: 45 }},
                paper_bgcolor: 'transparent',
                plot_bgcolor: '#090D16',
                xaxis: {{ title: 'Time (ms)', color: '#94A3B8', gridcolor: '#1E293B' }},
                yaxis: {{ title: 'Amplitude', color: '#94A3B8', gridcolor: '#1E293B' }},
                legend: {{ font: {{ color: '#94A3B8' }} }}
            }}, {{ responsive: true, displayModeBar: false }});

            // 2. PSD Plot
            const tracePsd = {{
                x: data.psd.freqs.map(f => f / 1e3),
                y: data.psd.psd_db,
                mode: 'lines',
                line: {{ color: '#38BDF8', width: 1.5 }}
            }};
            Plotly.newPlot('reportPsdPlot', [tracePsd], {{
                margin: {{ t: 15, r: 15, b: 35, l: 45 }},
                paper_bgcolor: 'transparent',
                plot_bgcolor: '#090D16',
                xaxis: {{ title: 'Frequency Offset (kHz)', color: '#94A3B8', gridcolor: '#1E293B' }},
                yaxis: {{ title: 'Power (dB/Hz)', color: '#94A3B8', gridcolor: '#1E293B' }}
            }}, {{ responsive: true, displayModeBar: false }});

            // 3. Spectrogram Plot
            const specSdrColormap = [
                [0.0, '#010214'],
                [0.15, '#0d1f69'],
                [0.35, '#0066ff'],
                [0.55, '#00ffd5'],
                [0.70, '#ffee00'],
                [0.85, '#ff4400'],
                [0.95, '#ff0055'],
                [1.0, '#ffffff']
            ];
            const isAud = Math.max(...data.spectrogram.freq_bins) <= 10000;
            const fDisp = isAud ? data.spectrogram.freq_bins : data.spectrogram.freq_bins.map(f => f / 1e3);
            const fLbl = isAud ? 'Frequency (Hz)' : 'Frequency (kHz)';
            const zTrans = data.spectrogram.time_bins.map((_, colIdx) => data.spectrogram.freq_bins.map((_, rowIdx) => data.spectrogram.spectrogram_db[rowIdx][colIdx]));

            const traceSpec = {{
                z: zTrans,
                x: fDisp,
                y: data.spectrogram.time_bins,
                type: 'heatmap',
                colorscale: specSdrColormap,
                zmin: data.spectrogram.vmin,
                zmax: data.spectrogram.vmax
            }};
            Plotly.newPlot('reportSpecPlot', [traceSpec], {{
                margin: {{ t: 15, r: 15, b: 35, l: 45 }},
                paper_bgcolor: 'transparent',
                plot_bgcolor: '#090D16',
                xaxis: {{ title: fLbl, color: '#94A3B8', gridcolor: '#1E293B' }},
                yaxis: {{ title: 'Time (s) [Waterfall Flow]', autorange: 'reversed', color: '#94A3B8', gridcolor: '#1E293B' }}
            }}, {{ responsive: true, displayModeBar: false }});

            // 4. Constellation Diagram
            const traceConst = {{
                x: data.synchronization.constellation_i,
                y: data.synchronization.constellation_q,
                mode: 'markers',
                type: 'scatter',
                marker: {{ color: '#10B981', size: 4, opacity: 0.8 }}
            }};
            Plotly.newPlot('reportConstellationPlot', [traceConst], {{
                margin: {{ t: 15, r: 15, b: 35, l: 35 }},
                paper_bgcolor: 'transparent',
                plot_bgcolor: '#090D16',
                xaxis: {{ range: [-2.2, 2.2], color: '#94A3B8', gridcolor: '#1E293B', zerolinecolor: '#334155' }},
                yaxis: {{ range: [-2.2, 2.2], color: '#94A3B8', gridcolor: '#1E293B', zerolinecolor: '#334155' }}
            }}, {{ responsive: true, displayModeBar: false }});
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
