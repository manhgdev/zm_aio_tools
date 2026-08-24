from pipeline.tts.capcut import _normalize_tts_text


def test_capcut_normalizes_joined_laughter() -> None:
    assert _normalize_tts_text("Hahahaha") == "Ha."
    assert _normalize_tts_text("HAHAHA!") == "Ha."
    assert _normalize_tts_text("Ha ha ha") == "Ha."


def test_capcut_keeps_normal_speech_and_cleans_whitespace() -> None:
    assert _normalize_tts_text("  Xin lỗi\n con.  ") == "Xin lỗi con."
