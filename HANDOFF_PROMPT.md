# New Session Starting Prompt — VeriShield NG (`#AI4Elections`)

Open `C:\Users\shamz\.gemini\antigravity\scratch\verishield-ng` as your active workspace in a new session, then paste the prompt below:

---

```text
Read README.md in this workspace first. We are building VeriShield NG for the #AI4Elections Hackathon (Rise Networks × INEC), combining:
1. Module A (Citizen & Blind-Accessible Shield): detects WhatsApp voice-note deepfakes and forged INEC flyers/notices, cross-checks official INEC public notices, and replies with spoken verdicts in Igbo, Pidgin, Yoruba, Hausa, and English.
2. Module B (Intake & Registry Guard): reuses the same visual forensics engine on synthetic demo registration data to flag AI-generated faces, screen-photo spoofs, and insider upload-burst anomalies into a human-in-the-loop Supervisor Review Queue.

Key deadlines & constraints:
- Phase 1 application form (https://ai4elections.risenetworks.org) closes Thursday, Nov 12, 2026 at 11:59 PM WAT.
- Working prototype showcase (Grand Finale) is December 16, 2026 in Lagos.
- Zero real voter PII (100% synthetic/public data), strictly nonpartisan, never declare election results, and always output calibrated uncertainty ("Inconclusive" when audio/image degradation is high).

Let's do two things in order:
Step 1: Help me fill out the Phase 1 application form (once I paste the fields, or start by outlining the exact track choice, project title, problem statement, and technical summary).
Step 2: Set up a clean Python (FastAPI) + accessible web frontend project structure and synthetic evaluation dataset generator so we can immediately start building and testing the Shared Forensics Core.
```
