"""Deterministic 100% synthetic benchmark & demo dataset generator for VeriShield NG.

Generates:
- data/synthetic/flyers/ (authentic, spliced-tamper, screen-moire, heavily-degraded)
- data/synthetic/audio/ (clean, vocoder-spoof, WhatsApp .ogg/.opus low-bandwidth)
- data/synthetic/portraits/ + data/synthetic/registry_batch.json (Module B zero-PII batch)
- data/synthetic/manifest.json (UI quick-test fixture list)
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, PngImagePlugin

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import SYNTHETIC_DIR  # noqa: E402


def _make_base_flyer(title: str, body_lines: list[str], rng: np.random.Generator) -> Image.Image:
    w, h = 820, 580
    img = Image.new("RGB", (w, h), (242, 246, 244))
    draw = ImageDraw.Draw(img)

    # Nonpartisan civic notice header banner
    draw.rectangle([(0, 0), (w, 86)], fill=(15, 76, 92))
    draw.text((28, 28), title, fill=(255, 255, 255))
    draw.rectangle([(24, 110), (w - 24, h - 24)], outline=(30, 64, 82), width=3)

    y = 140
    for line in body_lines:
        draw.text((48, y), line, fill=(20, 30, 42))
        y += 46

    # Add realistic camera/print micro-grain
    arr = np.asarray(img, dtype=np.float32)
    noise = rng.normal(0.0, 3.8, size=arr.shape)
    noisy = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(noisy)


def generate_flyers(out_dir: Path, rng: np.random.Generator) -> list[dict[str, str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, str]] = []

    # 1. Clean authentic-style notice
    clean_img = _make_base_flyer(
        "SYNTHETIC CIVIC NOTICE: OFFICIAL 2027 ELECTION TIMETABLE",
        [
            "Presidential & NASS Elections: Saturday, January 16, 2027",
            "Governorship & State Assembly: Saturday, February 6, 2027",
            "Verify updates strictly on https://www.inecnigeria.org",
        ],
        rng,
    )
    clean_path = out_dir / "flyer_authentic_timetable.jpg"
    clean_img.save(clean_path, format="JPEG", quality=88)
    items.append(
        {
            "id": "flyer_authentic",
            "label": "Flyer: Authentic Timetable Notice",
            "category": "flyers",
            "filename": clean_path.name,
            "expected_verdict": "OFFICIAL_MATCH_OR_NO_INDICATORS",
            "claim_text": "INEC 2027 General Election Official Timetable January 16, 2027.",
        }
    )

    # 2. Localized Photoshop/splice-tampered flyer (spliced low-Q patch into clean high-Q flyer)
    base_buf = io.BytesIO()
    clean_img.save(base_buf, format="JPEG", quality=96)
    base_buf.seek(0)
    spliced = Image.open(base_buf).convert("RGB")

    patch = Image.new("RGB", (440, 120), (255, 240, 240))
    p_draw = ImageDraw.Draw(patch)
    p_draw.rectangle([(0, 0), (439, 119)], outline=(160, 20, 20), width=4)
    p_draw.text((18, 24), "BREAKING: ELECTION POSTPONED INDEFINITELY", fill=(140, 10, 10))
    p_draw.text((18, 64), "VOTE BY SMS OR WHATSAPP — NO PVC NEEDED", fill=(30, 30, 30))
    # Heavy differential compression on the pasted patch before compositing
    p_buf = io.BytesIO()
    patch.save(p_buf, format="JPEG", quality=42)
    p_buf.seek(0)
    patch_recomp = Image.open(p_buf).convert("RGB")
    spliced.paste(patch_recomp, (190, 210))
    spliced_path = out_dir / "flyer_spliced_forged.jpg"
    spliced.save(spliced_path, format="JPEG", quality=96)
    items.append(
        {
            "id": "flyer_spliced",
            "label": "Flyer: Spliced Forged Postponement",
            "category": "flyers",
            "filename": spliced_path.name,
            "expected_verdict": "SYNTHETIC_OR_TAMPER_INDICATORS",
            "claim_text": "Breaking: Presidential election postponed indefinitely, vote by SMS, no PVC needed.",
        }
    )

    # 3. Screen-recapture moire + glare spoof flyer
    arr = np.asarray(clean_img, dtype=np.float32)
    yy, xx = np.mgrid[0 : arr.shape[0], 0 : arr.shape[1]]
    moire = 18.0 * np.sin(2.0 * np.pi * xx / 4.0) * np.sin(2.0 * np.pi * yy / 4.0)
    arr += moire[:, :, None]
    # Add diagonal specular screen glare hotspot
    glare = np.exp(-(((xx - 520) ** 2 + (yy - 260) ** 2) / (2.0 * 52.0 ** 2))) * 190.0
    arr = np.clip(arr + glare[:, :, None], 0, 255).astype(np.uint8)
    moire_path = out_dir / "flyer_screen_spoof.jpg"
    Image.fromarray(arr).save(moire_path, format="JPEG", quality=90)
    items.append(
        {
            "id": "flyer_moire",
            "label": "Flyer: Photo-of-Phone-Screen Spoof",
            "category": "flyers",
            "filename": moire_path.name,
            "expected_verdict": "SYNTHETIC_OR_TAMPER_INDICATORS",
            "claim_text": "",
        }
    )

    # 4. Heavily compressed & blurred WhatsApp forward -> Inconclusive calibration test
    degraded = clean_img.resize((120, 86), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(radius=3.2))
    degraded_path = out_dir / "flyer_whatsapp_blur_inconclusive.jpg"
    degraded.save(degraded_path, format="JPEG", quality=22)
    items.append(
        {
            "id": "flyer_inconclusive",
            "label": "Flyer: Heavily Blurred WhatsApp Forward",
            "category": "flyers",
            "filename": degraded_path.name,
            "expected_verdict": "INCONCLUSIVE",
            "claim_text": "",
        }
    )

    return items


def _write_wav(path: Path, samples: np.ndarray, sr: int = 16000) -> None:
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def generate_audio(out_dir: Path, rng: np.random.Generator) -> list[dict[str, str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sr = 16000
    dur = 2.6
    t = np.linspace(0.0, dur, int(sr * dur), endpoint=False)
    items: list[dict[str, str]] = []

    # 1. Natural-like multi-formant speech envelope with natural room mic floor & varied consonants
    f0 = 135.0 + 18.0 * np.sin(2.0 * np.pi * 1.4 * t) + 6.0 * np.sin(2.0 * np.pi * 4.3 * t)
    phase = 2.0 * np.pi * np.cumsum(f0) / sr
    harmonic = (
        0.50 * np.sin(phase)
        + 0.30 * np.sin(2.0 * phase)
        + 0.18 * np.sin(3.0 * phase)
        + 0.12 * np.sin(14.0 * phase)
    )
    # Add realistic syllabic envelope + unvoiced fricative bursts (high-band natural texture)
    syllable_env = np.clip(0.55 + 0.55 * np.sin(2.0 * np.pi * 3.2 * t), 0.05, 1.0)
    fricatives = rng.normal(0.0, 0.06, size=t.size) * (np.sin(2.0 * np.pi * 2.1 * t) > 0.35)
    room_floor = rng.normal(0.0, 0.014, size=t.size)  # Natural ~-30dB ambient floor
    clean_sig = 0.42 * harmonic * syllable_env + fricatives + room_floor
    clean_path = out_dir / "voice_authentic_demo.wav"
    _write_wav(clean_path, clean_sig, sr)
    items.append(
        {
            "id": "audio_authentic",
            "label": "Voice Note: Authentic Acoustic Profile",
            "category": "audio",
            "filename": clean_path.name,
            "expected_verdict": "OFFICIAL_MATCH_OR_NO_INDICATORS",
            "claim_text": "",
        }
    )

    # 2. Synthetic AI-clone-like waveform: dead digital silence gaps + stationary harmonic lock
    spoof = np.zeros_like(t)
    # Two rigid utterances separated by mathematically dead zero silence
    for start_s, end_s in ((0.15, 0.95), (1.35, 2.35)):
        idx = (t >= start_s) & (t <= end_s)
        tt = t[idx]
        tone = (
            0.45 * np.sin(2.0 * np.pi * 150.0 * tt)
            + 0.25 * np.sin(2.0 * np.pi * 300.0 * tt)
            + 0.15 * np.sin(2.0 * np.pi * 450.0 * tt)
            + 0.12 * np.sin(2.0 * np.pi * 4200.0 * tt)
        )
        spoof[idx] = tone
    spoof_path = out_dir / "voice_synthetic_clone_demo.wav"
    _write_wav(spoof_path, spoof, sr)
    items.append(
        {
            "id": "audio_spoof",
            "label": "Voice Note: Synthetic Vocoder / Silence-Floor Spoof",
            "category": "audio",
            "filename": spoof_path.name,
            "expected_verdict": "SYNTHETIC_OR_TAMPER_INDICATORS",
            "claim_text": "Election don shift to next month, no go polling unit tomorrow.",
        }
    )

    # 3. Heavy WhatsApp Opus/OGG narrowband degraded clip -> tests ffmpeg + Inconclusive calibration
    tmp_wav = out_dir / "_tmp_degraded.wav"
    narrow = np.convolve(clean_sig, np.ones(11) / 11.0, mode="same")  # Steep <2.5kHz low-pass
    _write_wav(tmp_wav, narrow, sr)

    ogg_path = out_dir / "voice_whatsapp_narrowband.ogg"
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-v",
                "error",
                "-i",
                str(tmp_wav),
                "-af",
                "lowpass=f=2400",
                "-c:a",
                "libopus",
                "-b:a",
                "10k",
                str(ogg_path),
            ],
            check=True,
        )
        tmp_wav.unlink(missing_ok=True)
        items.append(
            {
                "id": "audio_whatsapp_inconclusive",
                "label": "Voice Note: Heavy WhatsApp .ogg Compression",
                "category": "audio",
                "filename": ogg_path.name,
                "expected_verdict": "INCONCLUSIVE",
                "claim_text": "",
            }
        )
    else:
        tmp_wav.rename(out_dir / "voice_whatsapp_narrowband.wav")

    return items


def _make_synthetic_portrait(kind: str, seed_offset: int, rng: np.random.Generator) -> Image.Image:
    w, h = 256, 256
    canvas = np.full((h, w, 3), (218, 224, 232), dtype=np.float32)

    # Draw distinct synthetic geometric avatar silhouette (100% synthetic, zero real faces/PII)
    yy, xx = np.mgrid[0:h, 0:w]
    bg_tone = 178 + (seed_offset * 19) % 55
    canvas[:, :] = (bg_tone, bg_tone + (seed_offset * 7) % 20, bg_tone + 14)

    # Diagonal background gradient & distinct background circles before silhouette
    canvas[:, :, 0] += ((xx - 128) * (0.12 if seed_offset % 2 == 0 else -0.12))
    p_rng = np.random.default_rng(1000 + seed_offset)
    for _ in range(8):
        px, py = int(p_rng.integers(10, w - 10)), int(p_rng.integers(10, h - 10))
        pr = int(p_rng.integers(10, 24))
        pcol = tuple(int(c) for c in p_rng.integers(60, 230, size=3))
        cv2.circle(canvas, (px, py), pr, pcol, -1)

    cx = 114 + (seed_offset * 7) % 29
    cy = 96 + (seed_offset * 5) % 19
    rx = 38 + (seed_offset * 3) % 14
    ry = 48 + (seed_offset * 4) % 14

    head_mask = ((xx - cx) ** 2 / (rx ** 2) + (yy - cy) ** 2 / (ry ** 2)) <= 1.0
    skin = np.array([128 + (seed_offset * 13) % 55, 88 + (seed_offset * 7) % 35, 68], dtype=np.float32)
    canvas[head_mask] = skin

    shoulder_mask = ((xx - cx) ** 2 / (84 ** 2) + (yy - 235) ** 2 / (65 ** 2)) <= 1.0
    shirt = np.array([35 + (seed_offset * 17) % 90, 50 + (seed_offset * 23) % 90, 125], dtype=np.float32)
    canvas[shoulder_mask] = shirt

    # Distinct accessories/hairline bands so each synthetic persona has a unique perceptual dHash
    if seed_offset % 3 == 0:
        cv2.rectangle(canvas, (cx - rx, cy - ry - 6), (cx + rx, cy - ry + 16), (35, 35, 45), -1)
    if seed_offset % 2 == 1:
        cv2.rectangle(canvas, (cx - 26, cy - 12), (cx - 4, cy + 2), (20, 20, 25), 2)
        cv2.rectangle(canvas, (cx + 4, cy - 12), (cx + 26, cy + 2), (20, 20, 25), 2)

    cv2.circle(canvas, (cx - 14, cy - 6), 5, (30, 30, 35), -1)
    cv2.circle(canvas, (cx + 14, cy - 6), 5, (30, 30, 35), -1)
    cv2.ellipse(canvas, (cx, cy + 16), (15, 7), 0, 10, 170, (70, 40, 40), 2)

    if kind == "clean":
        canvas += rng.normal(0.0, 5.8, size=canvas.shape)
    elif kind == "ai_smooth":
        # Ultra-smooth synthetic skin/background + crisp edges (near-zero PRNU noise)
        canvas = cv2.bilateralFilter(np.clip(canvas, 0, 255).astype(np.uint8), 9, 45, 45).astype(np.float32)
    elif kind == "screen_spoof":
        canvas += rng.normal(0.0, 3.0, size=canvas.shape)
        moire = 22.0 * np.sin(2.0 * np.pi * xx / 4.0) * np.sin(2.0 * np.pi * yy / 4.0)
        glare = np.exp(-(((xx - 165) ** 2 + (yy - 75) ** 2) / (2.0 * 24.0 ** 2))) * 210.0
        canvas += moire[:, :, None] + glare[:, :, None]

    img = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))
    return img


def generate_module_b_batch(out_dir: Path, rng: np.random.Generator) -> Path:
    portraits_dir = out_dir / "portraits"
    portraits_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, str]] = []
    base_time = datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc)

    # 6 normal daytime synthetic registrations
    for i in range(6):
        fname = f"synth_clean_{i + 1:02d}.jpg"
        _make_synthetic_portrait("clean", i + 1, rng).save(portraits_dir / fname, format="JPEG", quality=89)
        records.append(
            {
                "record_id": f"SYNTH-REG-{i + 1:04d}",
                "synthetic_applicant_alias": f"SYNTH-CITIZEN-{i + 1:03d}",
                "operator_id": f"OP-LAGOS-0{(i % 2) + 1}",
                "station_code": f"STN-IKEJA-0{(i % 3) + 1}",
                "captured_at": (base_time + timedelta(minutes=i * 18)).isoformat(),
                "image_filename": fname,
                "claimed_capture_source": "registration_tablet",
            }
        )

    # 2 AI-smooth synthetic portrait spoofs (one pure signal, one also carrying AI metadata)
    ai_1 = _make_synthetic_portrait("ai_smooth", 21, rng)
    ai_1.save(portraits_dir / "synth_ai_face_01.png", format="PNG")
    records.append(
        {
            "record_id": "SYNTH-REG-0007",
            "synthetic_applicant_alias": "SYNTH-CITIZEN-007",
            "operator_id": "OP-LAGOS-02",
            "station_code": "STN-IKEJA-02",
            "captured_at": (base_time + timedelta(hours=2)).isoformat(),
            "image_filename": "synth_ai_face_01.png",
            "claimed_capture_source": "registration_tablet",
        }
    )

    ai_2 = _make_synthetic_portrait("ai_smooth", 25, rng)
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Software", "Stable Diffusion Synthetic Demo")
    ai_2.save(portraits_dir / "synth_ai_face_02.png", format="PNG", pnginfo=meta)
    records.append(
        {
            "record_id": "SYNTH-REG-0008",
            "synthetic_applicant_alias": "SYNTH-CITIZEN-008",
            "operator_id": "OP-ABUJA-03",
            "station_code": "STN-WUSE-01",
            "captured_at": (base_time + timedelta(hours=3)).isoformat(),
            "image_filename": "synth_ai_face_02.png",
            "claimed_capture_source": "registration_tablet",
        }
    )

    # 1 screen-recapture spoof portrait
    _make_synthetic_portrait("screen_spoof", 30, rng).save(
        portraits_dir / "synth_screen_spoof_01.jpg", format="JPEG", quality=90
    )
    records.append(
        {
            "record_id": "SYNTH-REG-0009",
            "synthetic_applicant_alias": "SYNTH-CITIZEN-009",
            "operator_id": "OP-ABUJA-03",
            "station_code": "STN-WUSE-01",
            "captured_at": (base_time + timedelta(hours=3, minutes=20)).isoformat(),
            "image_filename": "synth_screen_spoof_01.jpg",
            "claimed_capture_source": "registration_tablet",
        }
    )

    # 2 perceptual duplicate faces across distinct synthetic aliases
    dup_img = _make_synthetic_portrait("clean", 42, rng)
    dup_img.save(portraits_dir / "synth_dup_a.jpg", format="JPEG", quality=90)
    dup_img.save(portraits_dir / "synth_dup_b.jpg", format="JPEG", quality=86)
    records.append(
        {
            "record_id": "SYNTH-REG-0010",
            "synthetic_applicant_alias": "SYNTH-CITIZEN-010",
            "operator_id": "OP-KANO-05",
            "station_code": "STN-NASSARAWA-01",
            "captured_at": (base_time + timedelta(hours=4)).isoformat(),
            "image_filename": "synth_dup_a.jpg",
            "claimed_capture_source": "registration_tablet",
        }
    )
    records.append(
        {
            "record_id": "SYNTH-REG-0011",
            "synthetic_applicant_alias": "SYNTH-CITIZEN-011",
            "operator_id": "OP-KANO-05",
            "station_code": "STN-NASSARAWA-01",
            "captured_at": (base_time + timedelta(hours=4, minutes=35)).isoformat(),
            "image_filename": "synth_dup_b.jpg",
            "claimed_capture_source": "registration_tablet",
        }
    )

    # 14-record off-hours 02:00 AM upload-burst anomaly by OP-SYNTH-BURST-99 within 7 minutes
    burst_start = datetime(2026, 11, 11, 2, 2, tzinfo=timezone.utc)
    for j in range(14):
        fname = f"synth_burst_{j + 1:02d}.jpg"
        _make_synthetic_portrait("clean", 60 + j, rng).save(portraits_dir / fname, format="JPEG", quality=88)
        records.append(
            {
                "record_id": f"SYNTH-BURST-{j + 1:04d}",
                "synthetic_applicant_alias": f"SYNTH-BURST-ALIAS-{j + 1:03d}",
                "operator_id": "OP-SYNTH-BURST-99",
                "station_code": "STN-SYNTH-REMOTE-99",
                "captured_at": (burst_start + timedelta(seconds=j * 28)).isoformat(),
                "image_filename": fname,
                "claimed_capture_source": "registration_tablet",
            }
        )

    batch_path = out_dir / "registry_batch.json"
    batch_path.write_text(
        json.dumps(
            {
                "dataset_notice": "100% synthetic zero-PII benchmark batch for VeriShield NG Module B",
                "records": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return batch_path


def main() -> None:
    rng = np.random.default_rng(2026)
    SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)
    flyer_items = generate_flyers(SYNTHETIC_DIR / "flyers", rng)
    audio_items = generate_audio(SYNTHETIC_DIR / "audio", rng)
    batch_path = generate_module_b_batch(SYNTHETIC_DIR, rng)

    manifest_path = SYNTHETIC_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps({"samples": flyer_items + audio_items}, indent=2),
        encoding="utf-8",
    )
    print(f"Generated {len(flyer_items)} flyers, {len(audio_items)} audio fixtures, and {batch_path}")


if __name__ == "__main__":
    main()
