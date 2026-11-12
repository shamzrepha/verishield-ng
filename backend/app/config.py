"""Configuration, Responsible-AI constants, and calibrated forensics thresholds."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"
DATA_DIR = ROOT_DIR / "data"
SYNTHETIC_DIR = DATA_DIR / "synthetic"

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 15 * 1024 * 1024

OFFICIAL_INEC_CHANNELS = (
    "https://www.inecnigeria.org",
    "Official INEC verified social channels (@inecnigeria) and State Resident Electoral Commissioner offices",
)


class VerdictCode(str, Enum):
    """Four calibrated outcomes enforced by VeriShield NG's Responsible-AI Contract."""

    OFFICIAL_MATCH_OR_NO_INDICATORS = "OFFICIAL_MATCH_OR_NO_INDICATORS"
    SYNTHETIC_OR_TAMPER_INDICATORS = "SYNTHETIC_OR_TAMPER_INDICATORS"
    CONTRADICTS_OFFICIAL_NOTICE = "CONTRADICTS_OFFICIAL_NOTICE"
    INCONCLUSIVE = "INCONCLUSIVE"


VERDICT_LABELS: dict[VerdictCode, str] = {
    VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS: "Official Match / No Manipulation Indicators Found",
    VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS: "Synthetic or Tamper Indicators Detected",
    VerdictCode.CONTRADICTS_OFFICIAL_NOTICE: "Contradicts Verified INEC Public Notice",
    VerdictCode.INCONCLUSIVE: "Inconclusive — Verify via Official INEC Channels",
}


class SupportedLanguage(str, Enum):
    """Supported spoken and text verdict languages."""

    ENGLISH = "en"
    PIDGIN = "pcm"
    IGBO = "ig"
    YORUBA = "yo"
    HAUSA = "ha"


LANGUAGE_NAMES: dict[SupportedLanguage, str] = {
    SupportedLanguage.ENGLISH: "English",
    SupportedLanguage.PIDGIN: "Nigerian Pidgin",
    SupportedLanguage.IGBO: "Igbo",
    SupportedLanguage.YORUBA: "Yoruba",
    SupportedLanguage.HAUSA: "Hausa",
}


class ReviewStatus(str, Enum):
    """Human-in-the-loop review statuses for Module B (never auto-deletes a citizen)."""

    PENDING_REVIEW = "PENDING_REVIEW"
    CLEARED_BY_HUMAN = "CLEARED_BY_HUMAN"
    ESCALATED_FOR_AUDIT = "ESCALATED_FOR_AUDIT"
    RECAPTURE_REQUESTED = "RECAPTURE_REQUESTED"


@dataclass(frozen=True)
class ForensicsThresholds:
    """Calibrated thresholds shared across visual, acoustic, and burst-anomaly pipelines."""

    # Visual quality / degradation gate
    min_image_side_px: int = 96
    min_laplacian_blur_var: float = 8.0
    extreme_jpeg_blockiness: float = 0.78

    # Visual tamper & spoof thresholds
    ela_splice_peak_ratio: float = 2.65
    ela_localized_hotspot_frac: float = 0.035
    moire_fft_peak_ratio: float = 0.34
    glare_saturated_cluster_ratio: float = 0.018
    synthetic_smoothness_score: float = 0.62

    # Audio quality & WhatsApp compression gate
    min_audio_duration_s: float = 0.75
    min_audio_rms: float = 0.004
    min_active_bandwidth_hz: float = 3400.0

    # Audio anti-spoofing thresholds
    synthetic_silence_floor_ratio: float = 0.68
    low_spectral_flux_var: float = 0.62
    harmonic_over_smoothness: float = 0.64

    # Module B upload-burst anomaly threshold
    burst_window_minutes: int = 10
    burst_count_threshold: int = 12


THRESHOLDS = ForensicsThresholds()
