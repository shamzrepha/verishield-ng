"""Shared Synthetic-Media & Tamper Forensics Core used by Module A and Module B."""

from .audio import AudioAnalysisResult, analyze_audio
from .visual import VisualAnalysisResult, analyze_image, compute_dhash

__all__ = [
    "AudioAnalysisResult",
    "VisualAnalysisResult",
    "analyze_audio",
    "analyze_image",
    "compute_dhash",
]
