"""Multilingual (~20s) spoken verdict generator & accessible audio earcon synthesis."""

from __future__ import annotations

import base64
import io
import wave

import numpy as np

from ..config import LANGUAGE_NAMES, SupportedLanguage, VerdictCode
from ..schemas import SpokenVerdict

# Uniform mapping: (VerdictCode, SupportedLanguage) -> localized ~15-22s spoken script
_SPOKEN_TEMPLATES: dict[VerdictCode, dict[SupportedLanguage, str]] = {
    VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS: {
        SupportedLanguage.ENGLISH: (
            "VeriShield update: No synthetic voice or image-tampering indicators were detected in this media. "
            "However, signal screening alone does not confirm breaking news. Please verify election dates and polling "
            "updates directly on INEC Nigeria dot org before sharing."
        ),
        SupportedLanguage.PIDGIN: (
            "VeriShield report: We check dis voice note or flyer, we no see sign say AI fake am or edit am. "
            "Even so, abeg make sure say you confirm any election date or polling unit news for INEC official website "
            "inecnigeria dot org before you forward am."
        ),
        SupportedLanguage.IGBO: (
            "Nkwupụta VeriShield: Anyị enyochala faịlụ a, ahụghịkwa ihe gosiri na e ji AI mepụta ya ma ọ bụ gbanwee ya. "
            "Ma biko, lelee ozi ntuli aka niile na webụsaịtị gọọmentị INEC bụ inecnigeria dot org tupu i kesaa ya."
        ),
        SupportedLanguage.YORUBA: (
            "Ìròyìn VeriShield: A ṣe àyẹ̀wò fídíò tàbí àwòrán yìí, a kò sì rí àmì àtúnṣe tàbí ohùn AI kankan. "
            "Síbẹ̀síbẹ̀, ẹ rí i dájú pé ẹ fìdí ọjọ́ ìdìbò múlẹ̀ lórí ojú-òpó INEC ní inecnigeria dot org kí ẹ tó pín in."
        ),
        SupportedLanguage.HAUSA: (
            "Sakon VeriShield: Mun duba wannan sako kuma ba mu ga alamar kirkirar AI ko sauya hoto ba. "
            "Duk da haka, a tabbatar da sahihancin labarin zabe a shafin hukumar INEC na inecnigeria dot org kafin a yada."
        ),
    },
    VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS: {
        SupportedLanguage.ENGLISH: (
            "VeriShield alert: Forensic indicators of synthetic audio or localized image tampering were detected. "
            "Do not act on polling changes or forward this file blindly. Verify directly via official INEC channels at "
            "inecnigeria dot org."
        ),
        SupportedLanguage.PIDGIN: (
            "VeriShield warning: Our check see strong sign say dis voice note or flyer get AI clone or editing scatter inside. "
            "No believe am or forward am anyhow. Check INEC official website inecnigeria dot org to know true election update."
        ),
        SupportedLanguage.IGBO: (
            "Ịdọ aka ná ntị VeriShield: Nnyocha gosiri ihe ịrịba ama na e ji AI mepụta olu a ma ọ bụ gbanwee akwụkwọ a. "
            "Ekesala ya ma ọ bụ tụkwasị ya obi n'ebughị ụzọ lelee ozi INEC n'ezie na inecnigeria dot org."
        ),
        SupportedLanguage.YORUBA: (
            "Ìkìlọ̀ VeriShield: Àyẹ̀wò fi àmì hàn pé wọ́n lo AI tàbí àtúnṣe ẹ̀rọ láti ṣe ohùn tàbí ìwé ìròyìn yìí. "
            "Má ṣe gba àtúnṣe ìdìbò rẹ̀ gbọ́ tàbí pín in; ṣe ìwádìí lórí ojú-òpó INEC ní inecnigeria dot org."
        ),
        SupportedLanguage.HAUSA: (
            "Gargadin VeriShield: Bincike ya nuna alamun kirkirar muryar AI ko sauya fasalin wannan takarda. "
            "Kada ku yada ko ku dogara da shi; ku duba shafin hukumar INEC na gaskiya a inecnigeria dot org."
        ),
    },
    VerdictCode.CONTRADICTS_OFFICIAL_NOTICE: {
        SupportedLanguage.ENGLISH: (
            "VeriShield alert: Claims in this notice contradict verified public INEC electoral guidelines or timetables. "
            "Elections are not postponed or moved by anonymous forwards. Check inecnigeria dot org for official schedules."
        ),
        SupportedLanguage.PIDGIN: (
            "VeriShield alert: Wetin dis flyer or message dey talk no match official INEC rules or election date. "
            "INEC no dey shift election or cancel PVC through WhatsApp forward. Confirm real news for inecnigeria dot org."
        ),
        SupportedLanguage.IGBO: (
            "Ịdọ aka ná ntị VeriShield: Ihe dị n'akwụkwọ ozi a megidere ụkpụrụ na usoro oge gọọmentị INEC kwadoro. "
            "INEC anaghị eigharị ntuli aka site n'ozi nzuzo. Biko lelee inecnigeria dot org maka ezi ozi."
        ),
        SupportedLanguage.YORUBA: (
            "Ìkìlọ̀ VeriShield: Ohun tí ìwé ìròyìn yìí sọ lòdì sí àṣẹ àti ìtòlẹ́sẹẹsẹ ìdìbò tí INEC fọwọ́ sí. "
            "INEC kì í sún ìdìbò sẹ́yìn nípasẹ̀ ìfiránṣẹ́ lásán. Ẹ yẹ inecnigeria dot org wò fún ìròyìn òótọ́."
        ),
        SupportedLanguage.HAUSA: (
            "Gargadin VeriShield: Abin da ke cikin wannan sako ya saba wa jadawalin hukumar INEC da ka'idojin zabe. "
            "Ba a dage zabe ta sakonnin WhatsApp na jita-jita ba. Ku tabbatar da gaskiya a inecnigeria dot org."
        ),
    },
    VerdictCode.INCONCLUSIVE: {
        SupportedLanguage.ENGLISH: (
            "VeriShield notice: Results are inconclusive because WhatsApp compression, blur, or short audio length "
            "reduced signal clarity. Please do not guess—verify this claim directly on INEC Nigeria dot org."
        ),
        SupportedLanguage.PIDGIN: (
            "VeriShield notice: We no fit talk final word because WhatsApp compression or blur don spoil clear signal inside. "
            "Abeg no guess—go straight to official INEC website inecnigeria dot org to check true update."
        ),
        SupportedLanguage.IGBO: (
            "Ozi VeriShield: Nnyocha a enweghị ike inye nkwubi okwu doro anya n'ihi na mbelata mma WhatsApp ma ọ bụ "
            "adịghị mma foto mebiri ihe àmà. Biko lelee ozi gọọmentị na inecnigeria dot org."
        ),
        SupportedLanguage.YORUBA: (
            "Ìfitónilétí VeriShield: Àyẹ̀wò kò le fúnni ní ìdánilójú nítorí ìdàpọ̀ WhatsApp tàbí àìdára àwòrán ti dín "
            "ààmì ìwádìí kù. Ẹ jọ̀wọ́, ẹ yẹ ojú-òpó INEC wò ní inecnigeria dot org."
        ),
        SupportedLanguage.HAUSA: (
            "Sanarwar VeriShield: Sakamakon bai kai ga yanke hukunci ba saboda matsewar WhatsApp ko rashin kyawun hoto "
            "ya rage ingancin bincike. A duba sahihin bayani kai tsaye a inecnigeria dot org."
        ),
    },
}

_EARCON_FREQS: dict[VerdictCode, tuple[float, float]] = {
    VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS: (523.25, 659.25),
    VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS: (440.0, 311.13),
    VerdictCode.CONTRADICTS_OFFICIAL_NOTICE: (493.88, 329.63),
    VerdictCode.INCONCLUSIVE: (392.0, 392.0),
}


def _synthesize_earcon_wav_b64(verdict: VerdictCode) -> str:
    """Create a tiny 0.35s accessible auditory earcon WAV for screen-reader / audio feedback."""
    sr = 16000
    f1, f2 = _EARCON_FREQS[verdict]
    t = np.linspace(0.0, 0.16, int(sr * 0.16), endpoint=False)
    env = np.hanning(t.size)
    tone1 = 0.28 * np.sin(2.0 * np.pi * f1 * t) * env
    gap = np.zeros(int(sr * 0.04))
    tone2 = 0.28 * np.sin(2.0 * np.pi * f2 * t) * env
    pcm = (np.concatenate([tone1, gap, tone2]) * 32767.0).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return base64.b64encode(buf.getvalue()).decode("ascii")


def build_spoken_verdict(verdict: VerdictCode, language: SupportedLanguage) -> SpokenVerdict:
    """Build localized ~20s spoken verdict script and accessible auditory cue."""
    script = _SPOKEN_TEMPLATES[verdict][language]
    word_count = len(script.split())
    est_seconds = max(8, min(28, int(round(word_count / 2.3))))
    return SpokenVerdict(
        language=language,
        language_name=LANGUAGE_NAMES[language],
        text=script,
        estimated_duration_seconds=est_seconds,
        audio_b64_wav=_synthesize_earcon_wav_b64(verdict),
    )
