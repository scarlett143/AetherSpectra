# AetherSpectra // Autonomous SIGINT & Telemetry Platform - Vercel Deployment Guide

**AetherSpectra** is an autonomous 8-stage Signal Intelligence (SIGINT), blind demodulation, Automatic Modulation Classification (AMC), and telemetry extraction platform configured for seamless deployment on **Vercel Serverless**.

---

## 📁 Key Vercel Configuration Files

1. **`vercel.json`**: Configures the Python runtime `@vercel/python`, builds `api/index.py`, sets max serverless timeout (60s), and routes all incoming requests.
2. **`api/index.py`**: Serverless ASGI entry point exposing the FastAPI application (`app`).
3. **`app/static/`**:
   - `logo.svg`: High-resolution tactical vector SVG logo with frequency spectrum waves and radar core.
   - `favicon.svg`: Browser tab icon.
4. **`requirements.txt`**: Standard dependencies automatically installed by Vercel on build:
   - `fastapi`, `uvicorn`, `numpy`, `scipy`, `reportlab`, `python-docx`, `jinja2`, `python-multipart`, `requests`.
5. **`.vercelignore`**: Excludes temporary files, local caches, and test artifacts from the deployment bundle.
6. **Resilient Serverless Storage (`app/storage.py`)**: Automatically routes writes to `/tmp` in serverless environments, with in-memory caching to prevent read-only filesystem errors.

---

## 🚀 How to Deploy to Vercel

### Option 1: Deploy via Vercel CLI (Recommended)

1. **Install Vercel CLI** (if not already installed):
   ```bash
   npm i -g vercel
   ```

2. **Login to Vercel**:
   ```bash
   vercel login
   ```

3. **Deploy from project directory**:
   ```bash
   cd /Users/rithuliniyan/sih26147_workbench
   vercel
   ```
   * Follow the interactive prompts (Accept defaults for Framework preset: `Other`).
   * When asked to deploy to production:
     ```bash
     vercel --prod
     ```

---

### Option 2: Deploy via GitHub Integration

1. Push this repository to GitHub:
   ```bash
   git init
   git add .
   git commit -m "feat: AetherSpectra v3.0 Vercel deployable platform"
   git branch -M main
   git remote add origin https://github.com/<YOUR_USERNAME>/aetherspectra.git
   git push -u origin main
   ```

2. Go to **[vercel.com/new](https://vercel.com/new)**.
3. Import your GitHub repository.
4. Keep the default settings (**Root Directory**: `./`, **Framework Preset**: `Other`).
5. Click **Deploy**.

---

## 🧪 Local Verification

You can test the exact Vercel entrypoint locally using:
```bash
python3 -m uvicorn api.index:app --host 127.0.0.1 --port 8000 --reload
```
And visit **[http://localhost:8000](http://localhost:8000)**.
