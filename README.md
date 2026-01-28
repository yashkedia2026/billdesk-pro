# BillDesk Pro — Bill Generator (CSV → PDF)

BillDesk Pro is a lightweight web app that takes two trade/brokerage-style CSV uploads (**Daywise** and **Netwise**) and generates a clean **PDF Bill Summary Report**. It also includes a **Debug** option that returns the parsed/processed data as JSON so you can verify inputs before generating the PDF. :contentReference[oaicite:0]{index=0}

**Live app:** https://billdesk-pro.onrender.com/ :contentReference[oaicite:1]{index=1}  
**Repo:** https://github.com/yashkedia2026/billdesk-pro :contentReference[oaicite:2]{index=2}

---

## What you can do

From the web UI you can: :contentReference[oaicite:3]{index=3}
- Enter basic metadata (e.g., **Account**, **Trade Date**)
- Upload:
  - **Daywise CSV**
  - **Netwise CSV**
- Click:
  - **Debug (return JSON)** — validate/inspect what the server understood
  - **Generate PDF** — create the final PDF Bill Summary Report

---

## Tech stack (high level)

- **Backend:** Python (web server + CSV parsing/validation)
- **PDF generation:** server-side PDF renderer
- **Deployment:** Render (see `render.yaml` in repo) :contentReference[oaicite:4]{index=4}

> Note: Exact library versions and service config live in this repository (and `requirements.txt` / `render.yaml`). :contentReference[oaicite:5]{index=5}

---

## How it works (workflow)

1. You provide **Account** and **Trade Date** in the UI. :contentReference[oaicite:6]{index=6}  
2. Upload the two CSVs (**Daywise** + **Netwise**). :contentReference[oaicite:7]{index=7}  
3. Use **Debug (return JSON)** to confirm:
   - headers were recognized
   - totals / groupings look correct
4. Click **Generate PDF** to download/preview the generated PDF.

---

## Running locally

> The project’s runnable entrypoint lives under the `backend/` directory. :contentReference[oaicite:8]{index=8}

### 1) Clone
```bash
git clone https://github.com/yashkedia2026/billdesk-pro.git
cd billdesk-pro
2) Create a virtual environment + install deps
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
3) Start the server
Because repo layouts can vary, here are the two most common patterns:

Option A

cd backend
python main.py
Option B

cd backend
flask --app main run
Then open: http://127.0.0.1:5000
