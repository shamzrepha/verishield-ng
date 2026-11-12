# VeriShield NG — Unified AI Defense for `#AI4Elections` (2026–2027)

> **Event:** `#AI4Elections` Hackathon (Rise Networks × INEC × Meta, Google, Microsoft; supported by MacArthur Foundation & Luminate)  
> **Phase 1 Application Deadline:** **Thursday, Nov 12, 2026 at 11:59 PM WAT** (`https://ai4elections.risenetworks.org`)  
> **Grand Finale & Showcase:** **December 16, 2026** (Lagos) — working functional prototype required  
> **Election Context:** Nigeria General Elections — Jan 16, 2027 (Presidential/NASS) & Feb 6, 2027 (Governorship/State)

---

## 1. The Core Idea (Idea 1 + Idea 2 Unified Cleanly)

Instead of gluing two random apps together, **VeriShield NG** solves both sides of Nigeria's 2026–2027 synthetic election threat using **one shared Synthetic-Media & Tamper Forensics Core**:

1. **Module A — Citizen & Blind-Accessible Shield ("Blackout Shield")**
   - **Problem:** Eve-of-poll "blackout window" disinformation spreads via **WhatsApp voice notes (AI voice clones)** and **forged "INEC Press Release" flyers** in Pidgin, Igbo, Yoruba, and Hausa claiming polls are postponed or relocated. Existing text fact-checkers (*Run-Am*, *Dubawa* text workflows) miss voice notes and image screenshots, and blind/low-vision or non-English voters are hit hardest.
   - **What it does:** Users forward a voice note or flyer/screenshot (web app or bot). The engine runs acoustic spoofing detection (audio) or pixel/OCR tamper checks + official INEC notice retrieval (images), and replies with a **20-second spoken verdict in Igbo, Pidgin, Yoruba, Hausa, or English** plus screen-reader text.

2. **Module B — Intake & Registry Guard ("RegiGuard" using the SAME Image Forensics Core)**
   - **Problem:** Ahead of 2027, INEC's preliminary voters' register flagged anomalous records where rogue registration insiders injected **AI-generated faces** and suspicious entries.
   - **What it does:** Runs the **exact same Visual Forensics Core** on registration/observer image uploads (100% synthetic demo dataset—zero real PII!) to flag **AI-generated portraits**, **photo-of-a-phone-screen spoofs**, and **insider upload-burst anomalies** (e.g., 300 entries in 10 minutes at 2 AM) into a **Supervisor Review Queue** for human sign-off.

### Why They Share One Real Codebase
- **Shared Visual Forensics Core:**
  - Applied to a *forwarded flyer/notice* → detects Photoshop/text-splice scars + runs OCR against public INEC notices.
  - Applied to a *registration/intake portrait* → detects GAN/diffusion AI faces + screen-recapture moiré/glare + EXIF/timestamp tampering.
- **Shared Responsible-AI Contract:**
  - **4 calibrated outputs** (never "100% fake", never auto-deletes a citizen, never declares election results):
    1. `Official Match / No Manipulation Indicators Found`
    2. `Synthetic or Tamper Indicators Detected`
    3. `Contradicts Verified INEC Public Notice`
    4. `Inconclusive (e.g., Heavy WhatsApp Compression) — Verify via Official INEC Channels`

---

## 2. Official `#AI4Elections` Rubric Alignment

| Judging Criterion | Weight | How VeriShield NG Scores High |
| :--- | :---: | :--- |
| **Technical Functionality & Innovation** | **25%** | Acoustic anti-spoofing + ELA/AI-face visual forensics + metadata burst anomaly detection (not a plain LLM wrapper). |
| **Electoral Relevance & Practical Usefulness** | **20%** | Targets INEC's exact 2026–2027 warnings: blackout-window audio/flyer deepfakes and synthetic voter-register faces. |
| **Cybersecurity, Privacy & Responsible AI** | **20%** | Zero real PII (synthetic registration testbench), calibrated "Inconclusive" thresholds under WhatsApp compression, human-in-the-loop audit logs. |
| **Inclusion & Accessibility** | **15%** | Blind-accessible screen-reader UI + spoken voice verdicts in Igbo, Pidgin, Yoruba, Hausa, and English. |
| **Scalability & Feasibility** | **15%** | Single shared forensics backend, lightweight APIs/Azure-deployable, low-bandwidth audio replies. |
| **Demonstration & Documentation** | **5%** | Clean two-tab live demo + measured evaluation benchmark on WhatsApp-compressed synthetic audio & face/flyer datasets. |

**Prize Targets:** ₦10M pool — **₦4M** (1st), **₦2.5M** (2nd), **₦1.5M** (3rd) + **₦500k Special Awards** (*Responsible AI & Safety*, *Cybersecurity & Resilience*, *Electoral & Civic Inclusion*, *Research & Policy Innovation*).

---

## 3. Hard Red Lines (Do NOT Violate)

- **Zero real sensitive PII:** Build and test Module B exclusively on **synthetic/public datasets**.
- **Never present AI output as official election results:** Do not build public EC8A result tabulation or declare winners.
- **Strictly nonpartisan:** Neutral verification and civic education only.
- **Calibrated uncertainty:** Always explain limitations (especially WhatsApp `.ogg`/`.opus` re-encoding losses) and route to official INEC channels.

---

## 4. Recommended 5-Week Build Scope (Nov 12 → Dec 16)

Keep build effort **~75% Module A + Shared Forensics Core, ~25% Module B Dashboard** so it stays rock-solid alongside UGREEN/DSN:
1. **Week 1 (Nov 12–18):** Submit Phase 1 form by **Nov 12, 11:59 PM WAT**; lock stack (FastAPI + lightweight React/Next.js accessible UI); assemble synthetic benchmark datasets (WhatsApp-compressed Nigerian-accent audio clones + doctored sample INEC flyers + synthetic registration batch with injected AI faces/bursts).
2. **Week 2 (Nov 19–25):** Build Shared Visual Forensics Core (ELA + AI-face/spoof scorer + OCR) + Public INEC Notice Retriever.
3. **Week 3 (Nov 26–Dec 2):** Build Acoustic Deepfake Scorer + WhatsApp compression robustness tests + Multilingual Voice Reply (Igbo, Pidgin, English + Yoruba/Hausa).
4. **Week 4 (Dec 3–9):** Build Module B Supervisor Audit Queue (burst/GPS anomaly detection + explainable flags) + accessibility/screen-reader polish.
5. **Week 5 (Dec 10–15):** Benchmark precision/recall metrics, harden security/rate-limits, rehearse 3-minute live stage demo for **Dec 16** Lagos finale.

---

## 5. Scaffolded Workspace & Quickstart

- **Phase 1 Application Copy:** [`PHASE1_APPLICATION.md`](PHASE1_APPLICATION.md) (mapped 1:1 to all 5 steps of `https://ai4elections.risenetworks.org/application`).
- **Shared Forensics Core (`backend/app/forensics/`):** Unified visual forensics (`visual.py` — blockwise ELA, 2D-FFT screen moiré/glare, synthetic texture/micro-noise, EXIF checks, perceptual dHash) and acoustic anti-spoofing (`audio.py` — WAV + `ffmpeg` `.ogg`/`.opus` decoding with bandwidth compression calibration).
- **Civic & Inclusion Layer (`backend/app/civic/`):** Conversational Civic AI (`assistant.py` — Nigerian-Pidgin/English intent & candidate-withdrawal rumor detection + Electoral Act/public-doc Q&A), live Nigerian fact-check retrieval (`factcheck.py` — public Dubawa & FactCheckHub JSON lookup + optional Ollama/Gemini adapter with graceful offline/429 fallback), Polling Unit directory & ephemeral Haversine GPS matcher (`polling_units.py`), verified INEC public notice lookup (`notices.py`), and 5-language spoken replies (`multilingual.py`: `en`, `pcm`, `ig`, `yo`, `ha`).
- **Safety Shield & Multi-Witness Corroboration (`backend/app/safety/`):** Consent-gated Shake-to-Alert cluster escalation paired with conversational AI `"I Am Safe"` multi-witness interviewing (`corroborator.py`) that weights direct eyewitnesses vs. secondhand reports to prevent half-stories or biased spin.
- **Module B Registry Guard (`backend/app/registry/`):** Reuses `analyze_image(..., mode="portrait")` + sliding-window upload-burst & duplicate-face clustering into a dedicated INEC Supervisor Screening Desk.
- **Multi-Page Accessible Mobile PWA (`frontend/`):** Clean gateway (`/`), installable Citizen Civic AI & Shake Shield PWA (`/citizen` with explicit unticked-by-default NDPA 2023 GPS/motion consents, `manifest.webmanifest`, and `sw.js`), and INEC Screening Desk (`/screening`) served directly by FastAPI.

### Run Locally
```powershell
.\.venv\Scripts\python.exe scripts\generate_synthetic_dataset.py
.\.venv\Scripts\python.exe scripts\evaluate_forensics.py
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```
Open `http://127.0.0.1:8000` in your browser (API docs at `/docs`).
