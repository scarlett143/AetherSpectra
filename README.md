# ELVYN // Autonomous Signal Intelligence & Telemetry Platform

[![Vercel Deployment](https://img.shields.io/badge/Vercel-Deployed-000000.svg?logo=vercel&logoColor=white)](https://aether-spectra.vercel.app/)
[![FastAPI](https://img.shields.io/badge/FastAPI-3.0-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![DSP Pipeline](https://img.shields.io/badge/DSP-8--Stage_Core-0284C7.svg)](app/dsp/)
[![Latency](https://img.shields.io/badge/DSP_Latency-110ms-emerald.svg)](app/dsp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**ELVYN** is an autonomous 8-stage Signal Intelligence (SIGINT), blind demodulation, Automatic Modulation Classification (AMC), and telemetry extraction platform configured for local execution and serverless cloud deployment.

---

## ⚡ Key Highlights & Impact Numbers

- **96.7% Payload Compression**: Downsampled STFT waterfall spectrograms and Welch PSD from **7.41 MB to 246 KB** per query, enabling fluid real-time web rendering with zero lag.
- **Sub-120ms DSP Latency**: Total pipeline execution time reduced from ~600ms to **110ms** across all 8 processing stages.
- **Resilient 3-Tier Fallback**: Guaranteed zero-downtime serverless operation via static assets, disk templates, and self-contained Base64 in-memory HTML fallbacks.
- **Multi-Format Intelligence Dossier Export**: Generate executive and forensic reports in **PDF, DOCX, CSV, Markdown, JSON, and interactive HTML**.
- **Tactical Dark/Light Interface**: Full-featured web workbench with live carrier lock indicators, EVM/SNR badges, interactive Plotly waterfall spectrograms, and an audit log of captured RF bursts.

---

## 📡 8-Stage DSP Execution Pipeline

ELVYN executes an ordered, high-performance digital signal processing chain on incoming complex baseband I/Q recordings:

```text
[ Raw RF I/Q Stream (.wav / .iq / .raw / .bin / .sigmf) ]
                           │
                           ▼
  1. Filtering (Butterworth Bandpass, DC Offset Removal, AGC)
                           │
                           ▼
  2. FFT Analysis (Windowed Power Spectral Density, Spectral Flatness)
                           │
                           ▼
  3. Frequency Estimation (Carrier Center Frequency fc, 99% OBW, Residual CFO)
                           │
                           ▼
  4. Synchronization (Costas Loop Carrier Recovery, Gardner Timing Error Detector)
                           │
                           ▼
  5. Modulation Detection (High-Order Cumulants C20/C40/C42, Decision Tree AMC)
                           │
                           ▼
  6. Noise Estimation (M2M4 Signal-to-Noise Ratio Consensus, N0 Noise Floor)
                           │
                           ▼
  7. Demodulation (Soft Symbol Slicing, Gray Decoding, Bitstream Recovery)
                           │
                           ▼
  8. Signal Classification & Intelligence (Standard Recognition, Shannon Entropy, CRC & FEC)
```

---

## 🚀 Quickstart & Local Execution

### Prerequisites
- Python 3.11+ (Python 3.12 / 3.13 supported)
- Node.js 18+ (optional, for npm convenience scripts)

```bash
# Clone and enter directory
cd /Users/rithuliniyan/ELVYN

# Install Python dependencies
pip install -r requirements.txt

# Run development server
npm run dev
# Alternatively:
python3 -m uvicorn api.index:app --host 127.0.0.1 --port 8000 --reload

# Open platform in browser
open http://localhost:8000
```

---

## 🌐 Cloud Deployment (Vercel Serverless)

The platform is pre-configured with `vercel.json` and `@vercel/python` runtime wrappers:

```bash
# Deploy to Vercel production
vercel --prod
```

Or connect the GitHub repository directly to Vercel. For comprehensive instructions, see [`VERCEL_DEPLOYMENT.md`](file:///Users/rithuliniyan/ELVYN/VERCEL_DEPLOYMENT.md).

---

*Engineered by Team ELVYN · Autonomous RF Defense & Telemetry Systems*
