"""Shared Visual Forensics Core: ELA tamper detection, screen-spoof moiré/glare, synthetic face texture, and metadata checks."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np
from PIL import ExifTags, Image

from ..config import THRESHOLDS, VerdictCode
from ..schemas import ForensicSignal

_SUSPICIOUS_SOFTWARE_MARKERS = (
    "photoshop",
    "gimp",
    "canva",
    "corel",
    "lightroom",
    "midjourney",
    "dall-e",
    "dalle",
    "stable diffusion",
    "comfyui",
    "automatic1111",
    "flux",
    "firefly",
    "remini",
    "faceapp",
    "faceswap",
)


@dataclass(frozen=True)
class VisualAnalysisResult:
    """Structured output from the Shared Visual Forensics Core."""

    verdict_code: VerdictCode
    compression_degradation_detected: bool
    uncertainty_note: str
    signals: list[ForensicSignal]
    ai_face_likelihood: float
    screen_spoof_likelihood: float
    dhash_hex: str
    image_width: int
    image_height: int
    rgb_array: np.ndarray


def _clamp01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def compute_dhash(gray: np.ndarray, hash_size: int = 8) -> str:
    """Compute a 64-bit perceptual difference hash (dHash) for duplicate face/flyer clustering."""
    resized = cv2.resize(gray, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    diff = resized[:, 1:] > resized[:, :-1]
    bits = "".join("1" if bit else "0" for bit in diff.flatten())
    return f"{int(bits, 2):0{hash_size * hash_size // 4}x}"


def hamming_distance_hex(hex_a: str, hex_b: str) -> int:
    """Compute bit-level Hamming distance between two hex dHashes."""
    if len(hex_a) != len(hex_b):
        return 64
    return (int(hex_a, 16) ^ int(hex_b, 16)).bit_count()


def inspect_image_metadata(pil_img: Image.Image) -> tuple[float, str]:
    """Inspect EXIF and PNG text chunks for editing or AI-generation software tags."""
    found_tags: list[str] = []

    info_text = " ".join(f"{k}:{v}" for k, v in (pil_img.info or {}).items() if isinstance(v, (str, bytes)))
    info_lower = info_text.lower()
    for marker in _SUSPICIOUS_SOFTWARE_MARKERS:
        if marker in info_lower:
            found_tags.append(marker)

    try:
        exif = pil_img.getexif()
        for tag_id, value in exif.items():
            tag_name = str(ExifTags.TAGS.get(tag_id, tag_id)).lower()
            val_str = str(value).lower()
            if tag_name in {"software", "processingsoftware", "imagedescription", "artist"}:
                for marker in _SUSPICIOUS_SOFTWARE_MARKERS:
                    if marker in val_str and marker not in found_tags:
                        found_tags.append(marker)
    except Exception:
        pass

    if found_tags:
        return 0.92, f"Editing/AI tool signature in metadata: {', '.join(found_tags[:3])}."
    return 0.12, "No explicit editing or AI-generator software tags found in image metadata."


def assess_image_quality(gray: np.ndarray) -> tuple[float, float, bool, str]:
    """Measure blur (Laplacian variance) and 8x8 JPEG blocking degradation."""
    h, w = gray.shape
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    # Estimate 8x8 JPEG blocking artifacts from boundary vs interior horizontal/vertical gradients
    gray_f = gray.astype(np.float32)
    dx = np.abs(np.diff(gray_f, axis=1))
    dy = np.abs(np.diff(gray_f, axis=0))

    b_cols = dx[:, 7::8]
    i_cols = np.delete(dx, slice(7, dx.shape[1], 8), axis=1)
    b_rows = dy[7::8, :]
    i_rows = np.delete(dy, slice(7, dy.shape[0], 8), axis=0)

    boundary_grad = float(np.mean(b_cols) + np.mean(b_rows)) * 0.5 if b_cols.size and b_rows.size else 0.0
    interior_grad = float(np.mean(i_cols) + np.mean(i_rows)) * 0.5 if i_cols.size and i_rows.size else 1.0
    block_ratio = boundary_grad / max(interior_grad, 1e-3)
    blockiness_norm = _clamp01((block_ratio - 1.05) / 1.15)

    too_small = min(h, w) < THRESHOLDS.min_image_side_px
    too_blurry = lap_var < THRESHOLDS.min_laplacian_blur_var
    heavy_blocks = blockiness_norm >= THRESHOLDS.extreme_jpeg_blockiness
    degraded = too_small or too_blurry or heavy_blocks

    reasons: list[str] = []
    if too_small:
        reasons.append(f"resolution too low ({w}x{h}px)")
    if too_blurry:
        reasons.append(f"severe motion/compression blur (Laplacian var={lap_var:.1f})")
    if heavy_blocks:
        reasons.append(f"heavy 8x8 WhatsApp/JPEG blocking (score={blockiness_norm:.2f})")

    note = "; ".join(reasons) if reasons else f"Readable fidelity ({w}x{h}px, sharpness={lap_var:.1f})."
    return lap_var, blockiness_norm, degraded, note


def compute_ela_metrics(pil_rgb: Image.Image) -> tuple[float, str]:
    """Compute localized Error Level Analysis (ELA) splice score.

    Uniform re-compression (like normal WhatsApp forwarding) produces low MAD across blocks;
    localized text/face splices create localized residual clusters diverging sharply
    from the host image's median error (either hotter or colder).
    """
    buf = io.BytesIO()
    pil_rgb.save(buf, format="JPEG", quality=90)
    buf.seek(0)
    recompressed = Image.open(buf).convert("RGB")

    orig_arr = np.asarray(pil_rgb, dtype=np.float32)
    rec_arr = np.asarray(recompressed, dtype=np.float32)
    residual = np.mean(np.abs(orig_arr - rec_arr), axis=2)

    h, w = residual.shape
    block = 16 if min(h, w) >= 128 else 8
    bh, bw = h // block, w // block
    if bh < 3 or bw < 3:
        return 0.15, "Image too small for reliable blockwise ELA localization."

    trimmed = residual[: bh * block, : bw * block]
    blocks = trimmed.reshape(bh, block, bw, block).mean(axis=(1, 3))

    median_err = float(np.median(blocks))
    dev = np.abs(blocks - median_err)
    mad = float(np.median(dev))
    p95_dev = float(np.percentile(dev, 95))
    p99_dev = float(np.percentile(dev, 99))

    anomalous_thresh = max(1.15, 4.5 * mad)
    anomalous_frac = float(np.mean(dev > anomalous_thresh))

    dev_score = _clamp01((p95_dev - 0.85) / 1.35)
    cluster_score = _clamp01((anomalous_frac - 0.018) / 0.065)
    peak_score = _clamp01((p99_dev - 1.4) / 2.2)

    ela_score = _clamp01(0.45 * dev_score + 0.35 * cluster_score + 0.20 * peak_score)
    detail = (
        f"Blockwise ELA median={median_err:.2f}, MAD={mad:.2f}, "
        f"p95-dev={p95_dev:.2f}, anomalous-blocks={anomalous_frac:.1%}."
    )
    return ela_score, detail


def compute_screen_spoof_metrics(
    gray: np.ndarray,
    rgb: np.ndarray,
    degraded: bool = False,
) -> tuple[float, str]:
    """Detect photo-of-a-screen spoofs via 2D FFT moiré periodicity and localized specular glare."""
    if degraded:
        return 0.15, "Image fidelity too degraded for reliable 2D-FFT moiré or glare analysis."

    h, w = gray.shape
    size = min(h, w, 512)
    crop = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32)

    # Apply 2D Hann window to avoid boundary cross artifacts in FFT
    hann_1d = np.hanning(size).astype(np.float32)
    window = np.outer(hann_1d, hann_1d)
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2((crop - np.mean(crop)) * window)))

    cy, cx = size // 2, size // 2
    yy, xx = np.ogrid[:size, :size]
    dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    r_norm = dist / (size * 0.5)

    # Exclude DC + cross axes, inspect mid-to-high frequency annulus for periodic LCD grid spikes
    annulus = (r_norm >= 0.16) & (r_norm <= 0.88) & (np.abs(yy - cy) > 3) & (np.abs(xx - cx) > 3)
    annulus_vals = spectrum[annulus]
    if annulus_vals.size == 0:
        return 0.1, "Insufficient frequency bins for moiré inspection."

    median_mag = float(np.median(annulus_vals)) + 1e-6
    top_k = np.sort(annulus_vals)[-max(8, annulus_vals.size // 400) :]
    peak_ratio = float(np.mean(top_k) / median_mag)
    moire_norm = _clamp01((peak_ratio - 7.5) / 11.0)

    # Localized specular glare: contiguous saturated spots (0.5%-20% area) brighter than surround
    bright_mask = (np.min(rgb, axis=2) >= 248).astype(np.uint8)
    kernel = np.ones((7, 7), np.uint8)
    glare_clusters = cv2.morphologyEx(bright_mask, cv2.MORPH_OPEN, kernel)
    glare_ratio = float(np.mean(glare_clusters))

    is_localized_hotspot = 0.004 <= glare_ratio <= 0.22
    glare_norm = _clamp01((glare_ratio - 0.004) / 0.05) if is_localized_hotspot else 0.0

    combined = _clamp01(max(moire_norm * 0.85 + glare_norm * 0.15, glare_norm * 0.80 + moire_norm * 0.20))
    detail = f"2D-FFT moiré peak-to-median={peak_ratio:.2f}, localized glare coverage={glare_ratio:.2%}."
    return combined, detail


def compute_synthetic_portrait_metrics(gray: np.ndarray, rgb: np.ndarray) -> tuple[float, str]:
    """Detect overly smooth micro-texture & flat chrominance typical of AI portraits."""
    gray_f = gray.astype(np.float32)
    denoised = cv2.GaussianBlur(gray_f, (5, 5), sigmaX=1.2)
    micro_noise = np.abs(gray_f - denoised)

    # Inspect the smoothest 25% regions (interior skin/background away from edges)
    grad_x = cv2.Sobel(gray_f, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray_f, cv2.CV_32F, 0, 1, ksize=3)
    grad_mag = np.sqrt(grad_x ** 2 + grad_y ** 2)

    smooth_mask = grad_mag <= np.percentile(grad_mag, 25)
    smooth_micro_med = float(np.median(micro_noise[smooth_mask])) if np.any(smooth_mask) else 1.0

    global_contrast = float(np.std(gray_f))
    smoothness_anomaly = _clamp01((1.25 - smooth_micro_med) / 0.95) if global_contrast > 18.0 else 0.15

    # Check high-frequency color-plane divergence in smooth regions
    rg_diff = rgb[:, :, 0].astype(np.float32) - rgb[:, :, 1].astype(np.float32)
    rg_residual = np.abs(rg_diff - cv2.GaussianBlur(rg_diff, (5, 5), 1.0))
    chroma_med = float(np.median(rg_residual[smooth_mask])) if np.any(smooth_mask) else 1.0
    chroma_flatness = _clamp01((0.95 - chroma_med) / 0.80) if global_contrast > 18.0 else 0.15

    score = _clamp01(0.65 * smoothness_anomaly + 0.35 * chroma_flatness)
    detail = (
        f"Smooth-patch sensor micro-noise median={smooth_micro_med:.2f}, "
        f"chroma residual median={chroma_med:.2f}."
    )
    return score, detail


def analyze_image(
    image_bytes: bytes,
    mode: Literal["flyer", "portrait"] = "flyer",
) -> VisualAnalysisResult:
    """Run the Shared Visual Forensics Core on a flyer/notice or registration portrait."""
    if not image_bytes:
        raise ValueError("Empty image payload.")

    try:
        pil_img = Image.open(io.BytesIO(image_bytes))
        pil_img.load()
    except Exception as exc:
        raise ValueError(f"Unsupported or corrupted image file: {exc}") from exc

    meta_score, meta_detail = inspect_image_metadata(pil_img)
    pil_rgb = pil_img.convert("RGB")
    rgb = np.asarray(pil_rgb, dtype=np.uint8)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    h, w = gray.shape
    dhash_hex = compute_dhash(gray)
    lap_var, blockiness_norm, degraded, quality_note = assess_image_quality(gray)

    ela_score, ela_detail = compute_ela_metrics(pil_rgb)
    spoof_score, spoof_detail = compute_screen_spoof_metrics(gray, rgb, degraded=degraded)
    portrait_score, portrait_detail = compute_synthetic_portrait_metrics(gray, rgb)

    signals = [
        ForensicSignal(
            name="ela_localized_splice",
            score=round(ela_score, 3),
            threshold=0.55,
            triggered=ela_score >= 0.55,
            detail=ela_detail,
        ),
        ForensicSignal(
            name="screen_recapture_moire_glare",
            score=round(spoof_score, 3),
            threshold=0.52,
            triggered=spoof_score >= 0.52,
            detail=spoof_detail,
        ),
        ForensicSignal(
            name="metadata_editor_signature",
            score=round(meta_score, 3),
            threshold=0.50,
            triggered=meta_score >= 0.50,
            detail=meta_detail,
        ),
        ForensicSignal(
            name="synthetic_texture_smoothness",
            score=round(portrait_score, 3),
            threshold=THRESHOLDS.synthetic_smoothness_score,
            triggered=portrait_score >= THRESHOLDS.synthetic_smoothness_score,
            detail=portrait_detail,
        ),
    ]

    # Calibrated verdict synthesis respecting quality / compression uncertainty
    if mode == "flyer":
        strong_tamper = ela_score >= 0.55 or meta_score >= 0.70 or spoof_score >= 0.52
        moderate_tamper = sum(1 for s in signals[:3] if s.score >= 0.45) >= 2
        if degraded and meta_score < 0.70:
            verdict_code = VerdictCode.INCONCLUSIVE
            uncertainty = (
                f"Degraded image quality ({quality_note}). Heavy WhatsApp compression or blur "
                "obscures fine tamper traces; verify directly via official INEC channels."
            )
        elif strong_tamper or moderate_tamper:
            verdict_code = VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS
            uncertainty = (
                "Localized compression/metadata/recapture anomalies detected. Treat as unverified "
                "until confirmed against official INEC notices."
            )
        else:
            verdict_code = VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS
            uncertainty = (
                f"No localized pixel-splice or screen-recapture indicators detected ({quality_note}). "
                "Cross-check notice content against official INEC records."
            )
    else:
        # Portrait mode (Module B intake screening)
        strong_spoof = (
            spoof_score >= 0.52
            or portrait_score >= THRESHOLDS.synthetic_smoothness_score
            or ela_score >= 0.62
            or meta_score >= 0.70
        )
        if degraded and not strong_spoof:
            verdict_code = VerdictCode.INCONCLUSIVE
            uncertainty = (
                f"Low-fidelity portrait capture ({quality_note}). Flag for human review or recapture "
                "rather than automated rejection."
            )
        elif strong_spoof:
            verdict_code = VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS
            uncertainty = (
                "Synthetic-texture, recapture-moiré, or edit-trace indicator triggered. "
                "Routed to Supervisor Review Queue for human sign-off."
            )
        else:
            verdict_code = VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS
            uncertainty = f"No visual spoof indicators found ({quality_note})."

    return VisualAnalysisResult(
        verdict_code=verdict_code,
        compression_degradation_detected=degraded or blockiness_norm >= 0.55,
        uncertainty_note=uncertainty,
        signals=signals,
        ai_face_likelihood=round(max(portrait_score, meta_score * 0.85 if meta_score >= 0.5 else 0.0), 3),
        screen_spoof_likelihood=round(spoof_score, 3),
        dhash_hex=dhash_hex,
        image_width=w,
        image_height=h,
        rgb_array=rgb,
    )
