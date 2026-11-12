"""Acoustic Anti-Spoofing & WhatsApp Compression Calibration Core."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass

import numpy as np
from scipy.signal import stft

from ..config import THRESHOLDS, VerdictCode
from ..schemas import ForensicSignal

TARGET_SR = 16000


@dataclass(frozen=True)
class AudioAnalysisResult:
    """Structured acoustic forensics output with compression-aware calibration."""

    verdict_code: VerdictCode
    compression_degradation_detected: bool
    uncertainty_note: str
    signals: list[ForensicSignal]
    duration_seconds: float
    effective_bandwidth_hz: float


def _clamp01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _decode_wav_native(audio_bytes: bytes) -> tuple[np.ndarray, int] | None:
    """Fast pure-Python decode for standard PCM WAV files without spawning ffmpeg."""
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sr = wf.getframerate()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
    except Exception:
        return None

    if sample_width == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        return None

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)

    if sr != TARGET_SR and data.size > 0:
        new_len = max(1, int(round(data.size * TARGET_SR / sr)))
        x_old = np.linspace(0.0, 1.0, num=data.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
        data = np.interp(x_new, x_old, data).astype(np.float32)
        sr = TARGET_SR

    return data, sr


def decode_audio_to_mono_16k(audio_bytes: bytes, filename: str = "clip.ogg") -> tuple[np.ndarray, int]:
    """Decode WAV natively or OGG/OPUS/MP3/M4A via ffmpeg into mono 16kHz float32 PCM."""
    if not audio_bytes:
        raise ValueError("Empty audio payload.")

    native = _decode_wav_native(audio_bytes)
    if native is not None:
        return native

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise ValueError("ffmpeg is required on PATH to decode non-WAV audio formats (.ogg/.opus/.mp3).")

    suffix = os.path.splitext(filename)[1] or ".ogg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        proc = subprocess.run(
            [
                ffmpeg_bin,
                "-v",
                "error",
                "-i",
                tmp_path,
                "-ac",
                "1",
                "-ar",
                str(TARGET_SR),
                "-f",
                "s16le",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
            timeout=20,
        )
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode("utf-8", errors="ignore").strip()
        raise ValueError(f"Could not decode audio file ({err or 'unsupported codec'}).")

    samples = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    return samples, TARGET_SR


def _compute_acoustic_features(samples: np.ndarray, sr: int) -> tuple[float, float, float, float, float]:
    """Compute effective bandwidth, silence-floor drop, spectral flux uniformity, and high-band smoothness."""
    frame_len = int(0.025 * sr)  # 25ms
    hop_len = int(0.010 * sr)    # 10ms

    if samples.size < frame_len * 4:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    # 1. Effective upper bandwidth (99% cumulative power frequency)
    fft_mag = np.abs(np.fft.rfft(samples * np.hanning(samples.size))) ** 2
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / sr)
    total_power = float(np.sum(fft_mag)) + 1e-12
    cum_power = np.cumsum(fft_mag) / total_power
    bw_idx = int(np.searchsorted(cum_power, 0.99))
    effective_bw_hz = float(freqs[min(bw_idx, freqs.size - 1)])

    # 2. Frame RMS profile -> digital-silence floor ratio (TTS/clones often leave zero floor between words)
    n_frames = 1 + (samples.size - frame_len) // hop_len
    frames = np.lib.stride_tricks.sliding_window_view(samples, frame_len)[::hop_len][:n_frames]
    frame_rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    p10_rms = float(np.percentile(frame_rms, 10))
    p90_rms = float(np.percentile(frame_rms, 90)) + 1e-9
    floor_ratio_db = 20.0 * np.log10(max(p10_rms / p90_rms, 1e-6))
    # Natural room mic has floor around -20 to -42 dB; digital zero silence drops below -55 dB
    digital_silence_score = _clamp01((-floor_ratio_db - 46.0) / 28.0)

    # 3. STFT spectral flux variance across voiced frames
    _, _, zxx = stft(samples, fs=sr, nperseg=512, noverlap=256)
    mag = np.abs(zxx) + 1e-8
    log_mag = np.log(mag)
    flux = np.sqrt(np.mean(np.diff(log_mag, axis=1) ** 2, axis=0))
    frame_energy = np.mean(mag, axis=0)
    active = frame_energy[1:] > np.percentile(frame_energy, 35)
    active_flux = flux[active] if np.any(active) else flux
    flux_cv = float(np.std(active_flux) / (np.mean(active_flux) + 1e-6))
    # Unnaturally steady/repetitive synthetic vocoder frames have low flux CV
    flux_uniformity_score = _clamp01((0.46 - flux_cv) / 0.28)

    # 4. Upper-band (3.2-7.2 kHz) spectral flatness vs natural breath/fricative texture
    stft_freqs = np.fft.rfftfreq(512, d=1.0 / sr)
    high_band = (stft_freqs >= 3200.0) & (stft_freqs <= 7200.0)
    mid_band = (stft_freqs >= 300.0) & (stft_freqs < 3200.0)
    high_power = mag[high_band, :]
    mid_power = mag[mid_band, :]

    geo_mean = np.exp(np.mean(np.log(high_power + 1e-9), axis=0))
    arith_mean = np.mean(high_power + 1e-9, axis=0)
    high_flatness = float(np.median(geo_mean / arith_mean))
    high_to_mid = float(np.mean(high_power) / (np.mean(mid_power) + 1e-8))

    # Synthetic harmonic-locked audio shows either very tonal (low flatness) or unnatural high-band buzz
    harmonic_over_smooth = _clamp01((0.36 - high_flatness) / 0.28) if high_to_mid > 0.015 else 0.20

    overall_rms = float(np.sqrt(np.mean(samples ** 2)))
    return overall_rms, effective_bw_hz, digital_silence_score, flux_uniformity_score, harmonic_over_smooth


def analyze_audio(audio_bytes: bytes, filename: str = "voice_note.ogg") -> AudioAnalysisResult:
    """Run acoustic anti-spoofing and WhatsApp compression calibration on a voice note."""
    samples, sr = decode_audio_to_mono_16k(audio_bytes, filename=filename)
    duration_s = float(samples.size / sr)

    overall_rms, bw_hz, silence_score, flux_score, harmonic_score = _compute_acoustic_features(samples, sr)

    too_short = duration_s < THRESHOLDS.min_audio_duration_s
    too_quiet = overall_rms < THRESHOLDS.min_audio_rms
    narrowband = bw_hz < THRESHOLDS.min_active_bandwidth_hz
    compression_degraded = too_short or too_quiet or narrowband

    signals = [
        ForensicSignal(
            name="inter_utterance_digital_silence",
            score=round(silence_score, 3),
            threshold=THRESHOLDS.synthetic_silence_floor_ratio,
            triggered=silence_score >= THRESHOLDS.synthetic_silence_floor_ratio,
            detail=f"Digital silence floor score={silence_score:.2f} (flags mathematically dead gaps between words).",
        ),
        ForensicSignal(
            name="spectral_flux_uniformity",
            score=round(flux_score, 3),
            threshold=THRESHOLDS.low_spectral_flux_var,
            triggered=flux_score >= THRESHOLDS.low_spectral_flux_var,
            detail=f"Vocoder spectral-envelope stationarity score={flux_score:.2f}.",
        ),
        ForensicSignal(
            name="high_band_harmonic_oversmoothness",
            score=round(harmonic_score, 3),
            threshold=THRESHOLDS.harmonic_over_smoothness,
            triggered=harmonic_score >= THRESHOLDS.harmonic_over_smoothness,
            detail=f"Upper-band (3.2-7.2 kHz) harmonic lock score={harmonic_score:.2f}; active BW={bw_hz:.0f} Hz.",
        ),
    ]

    triggered_count = sum(1 for s in signals if s.triggered)
    strong_spoof = triggered_count >= 2 or (silence_score >= 0.80 and harmonic_score >= 0.50)

    if too_short or too_quiet:
        verdict_code = VerdictCode.INCONCLUSIVE
        uncertainty = (
            f"Clip is too short ({duration_s:.2f}s) or quiet (RMS={overall_rms:.4f}) for reliable "
            "acoustic verification. Verify any electoral claim via official INEC channels."
        )
    elif narrowband:
        verdict_code = VerdictCode.INCONCLUSIVE
        uncertainty = (
            f"Heavy codec/WhatsApp bandwidth truncation detected (99% energy <= {bw_hz:.0f} Hz). "
            "Compression destroys high-frequency vocoder artifacts; verify via official INEC channels."
        )
    elif strong_spoof:
        verdict_code = VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS
        uncertainty = (
            "Acoustic anti-spoofing detected synthetic silence-floor or vocoder spectral regularity. "
            "Note: multi-hop WhatsApp forwarding can alter codecs; cross-check official INEC announcements."
        )
    else:
        verdict_code = VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS
        uncertainty = (
            f"No synthetic vocoder indicators detected across {duration_s:.1f}s clip (BW={bw_hz:.0f} Hz). "
            "Acoustic authenticity alone does not prove factual accuracy—verify claims with INEC."
        )

    return AudioAnalysisResult(
        verdict_code=verdict_code,
        compression_degradation_detected=compression_degraded,
        uncertainty_note=uncertainty,
        signals=signals,
        duration_seconds=round(duration_s, 2),
        effective_bandwidth_hz=round(bw_hz, 1),
    )
