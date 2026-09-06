from types import SimpleNamespace

from pipeline.asr.whisper import _segments_from_whisper


def test_whisper_word_groups_preserve_spaces_for_app_script():
    row = SimpleNamespace(
        start=0.0,
        end=2.8,
        text="Today, Victor's company successfully went purblet.",
        words=[
            SimpleNamespace(start=0.0, end=0.3, word=" Today,"),
            SimpleNamespace(start=0.4, end=0.8, word=" Victor's"),
            SimpleNamespace(start=0.8, end=1.1, word=" company"),
            SimpleNamespace(start=1.2, end=1.7, word=" successfully"),
            SimpleNamespace(start=1.8, end=2.2, word=" went"),
            SimpleNamespace(start=2.2, end=2.7, word=" purblet."),
        ],
    )

    segments = _segments_from_whisper(row)

    assert len(segments) == 1
    assert segments[0]["source"] == "Today, Victor's company successfully went purblet."
