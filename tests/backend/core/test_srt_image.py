from pathlib import Path

import pytest

from pipeline.srt_image import (
    _drawing_video_sources,
    _ffmpeg_subtitle,
    _log,
    _logo_position,
    _render_logo_asset,
    _render_cache_key,
    _store_cached_render,
    _cached_render,
    _text_logo_filter,
    _text_logo_position,
    LOGO_RANDOM_POSITIONS,
    create_job,
    image_resolution,
    is_video,
    media_duration,
    preview_media_window,
    parse_srt_times,
    parse_timing_times,
    parse_timeline_times,
    sequential_media_times,
    select_cues_for_media,
    shift_srt,
)
from api.routes.srt_image import _resolve_output_target


def test_missing_media_can_be_skipped_only_after_confirmation():
    cues = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]
    with pytest.raises(ValueError, match="cần ít nhất 3 file, hiện có 2"):
        select_cues_for_media(cues, 2, allow_missing=False)
    assert select_cues_for_media(cues, 2, allow_missing=True) == cues[:2]


def test_preview_only_prepares_media_needed_for_requested_output_duration():
    media = [Path("001.png"), Path("002.png"), Path("003.png")]
    selected, durations = preview_media_window(media, [10.0, 10.0, 10.0], 15.0, 1.0)
    assert selected == media[:2]
    assert durations == [10.0, 5.0]

    selected, durations = preview_media_window(media, [10.0, 10.0, 10.0], 15.0, 2.0)
    assert selected == media
    assert durations == [10.0, 10.0, 10.0]


def test_parse_srt_times(tmp_path):
    srt = tmp_path / "sample.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,500\nMột\n\n"
        "2\n00:00:01,500 --> 00:00:03,000\nHai\n",
        encoding="utf-8",
    )
    assert parse_srt_times(srt) == [(0.0, 1.5), (1.5, 3.0)]


def test_shift_srt_and_subtitle_style(tmp_path):
    source = tmp_path / "sample.srt"
    output = tmp_path / "shifted.srt"
    source.write_text(
        "1\n00:00:01,000 --> 00:00:02,500\nMột câu bị\nxuống dòng sớm\n",
        encoding="utf-8",
    )

    shift_srt(source, output, -1.5)

    assert "00:00:00,000 --> 00:00:01,000" in output.read_text(encoding="utf-8")
    assert "Một câu bị xuống dòng sớm" in output.read_text(encoding="utf-8")
    subtitle_filter = _ffmpeg_subtitle(
        output, font_size=12, margin_bottom=24, bg_style="solid"
    )
    assert "subtitles=filename=" in subtitle_filter
    ass = output.with_suffix(".sub.ass").read_text(encoding="utf-8-sig")
    assert "Style: Default,Noto Sans,12" in ass
    assert ",3," in ass
    assert ",20,20,24," in ass


def test_job_log_keeps_recent_lines(tmp_path):
    job = create_job(
        "test.mp4", tmp_path, [], None, tmp_path / "timeline.txt",
        tmp_path / "subtitles.srt", {},
    )
    for index in range(205):
        _log(job["id"], f"line {index}")
    from pipeline.srt_image import get_job
    logs = get_job(job["id"])["logs"]
    assert len(logs) == 200
    assert logs[-1].endswith("line 204")


def test_text_logo_uses_explicit_windows_font(monkeypatch, tmp_path):
    import pipeline.srt_image as module
    windows = tmp_path / "Windows"
    font = windows / "Fonts" / "arial.ttf"
    font.parent.mkdir(parents=True)
    font.touch()
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setenv("WINDIR", str(windows))

    result = _text_logo_filter({"source": "text", "text": "ZMTOOL"}, 1080)

    assert "fontfile=" in result
    assert "arial" in result


def test_text_logo_position_uses_text_dimensions():
    fixed = _text_logo_position(88, 88)
    moving = _text_logo_position(88, 88, True)
    assert fixed == (
        "min(W-tw,max(0,W*0.8800))",
        "min(H-th,max(0,H*0.8800))",
    )
    assert "W-tw" in moving[0]
    assert "-th" in moving[1]


def test_random_text_logo_uses_standard_show_hide_cycle():
    result = _text_logo_filter({
        "source": "text", "text": "ZMTOOL", "motion": "random",
        "visibleSec": 4, "hiddenSec": 2, "fadeSec": 0.5,
        "safeMargin": 4, "fontSize": 42, "color": "#ffd166",
    }, 1080)
    assert "floor(t/6.000)" in result
    assert "mod(t,6.000)" in result
    assert "fontcolor=#ffd166" in result
    assert "shadowcolor=black@0.85" in result


def test_parse_timeline_times(tmp_path):
    timeline = tmp_path / "prompts.txt"
    timeline.write_text(
        "001_[00:00.000-00:01.500] cảnh một\n"
        "002_[00:01.500-00:03.000] cảnh hai\n",
        encoding="utf-8",
    )
    assert parse_timeline_times(timeline) == [(0.0, 1.5), (1.5, 3.0)]


def test_parse_dot_timecode_timeline(tmp_path):
    timeline = tmp_path / "video-prompts.txt"
    timeline.write_text(
        "001_[00.00.00.00-00.00.04.00] clip one\n\n"
        "002_[00.00.04.00-00.00.10.00] clip two\n",
        encoding="utf-8",
    )
    assert parse_timeline_times(timeline) == [(0.0, 4.0), (4.0, 10.0)]


def test_srt_can_supply_media_timing(tmp_path):
    timeline = tmp_path / "timeline.srt"
    timeline.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nMột\n\n"
        "2\n00:00:02,000 --> 00:00:05,000\nHai\n",
        encoding="utf-8",
    )

    assert parse_timing_times(timeline) == [(0.0, 2.0), (2.0, 5.0)]


def test_common_timeline_formats_supply_media_timing(tmp_path):
    samples = {
        "timeline.vtt": "WEBVTT\n\n00:00.000 --> 00:02.000\nOne\n\n00:02.000 --> 00:05.000\nTwo\n",
        "timeline.ass": "[Events]\nDialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,One\nDialogue: 0,0:00:02.00,0:00:05.00,Default,,0,0,0,,Two\n",
        "timeline.csv": "start,end,text\n0,2,One\n2,5,Two\n",
        "timeline.tsv": "start_time\tend_time\ttext\n0\t2\tOne\n2\t5\tTwo\n",
        "timeline.json": '{"scenes":[{"start":0,"end":2},{"startTime":"00:02.000","endTime":"00:05.000"}]}',
        "timeline.lrc": "[00:00.00]One\n[00:02.00]Two\n[00:05.00]End\n",
    }
    for name, content in samples.items():
        timeline = tmp_path / name
        timeline.write_text(content, encoding="utf-8")
        assert parse_timing_times(timeline) == [(0.0, 2.0), (2.0, 5.0)], name


def test_sequential_media_times_works_without_a_timeline(monkeypatch, tmp_path):
    image = tmp_path / "001.jpg"
    video = tmp_path / "002.mp4"
    image.touch()
    video.touch()
    monkeypatch.setattr(
        "pipeline.srt_image.media_duration",
        lambda path, image_duration=5.0: 7.5 if path == video else image_duration,
    )

    assert sequential_media_times([image, video]) == [(0.0, 5.0), (5.0, 12.5)]


def test_video_duration_falls_back_to_default_when_probe_fails(monkeypatch, tmp_path):
    video = tmp_path / "clip.mp4"
    video.touch()
    monkeypatch.setattr("pipeline.srt_image.subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))

    assert media_duration(video) == 5.0


def test_image_resolution_is_even(monkeypatch, tmp_path):
    class Result:
        stdout = '{"streams":[{"width":1921,"height":1081}]}'

    monkeypatch.setattr("pipeline.srt_image.subprocess.run", lambda *args, **kwargs: Result())
    assert image_resolution(tmp_path / "image.jpg") == (1920, 1080)


def test_logo_position():
    assert "W*0.0000" in _logo_position(0, 0)[0]
    assert "floor(t/6.000)" in _logo_position(moving=True)[0]


def test_random_logo_positions_do_not_jump_to_adjacent_nearby_regions():
    pairs = zip(LOGO_RANDOM_POSITIONS, (*LOGO_RANDOM_POSITIONS[1:], LOGO_RANDOM_POSITIONS[0]))
    assert all((right[0] - left[0]) ** 2 + (right[1] - left[1]) ** 2 >= 0.16 for left, right in pairs)


def test_text_logo_is_rendered_as_png_without_ffmpeg_drawtext(tmp_path):
    output = _render_logo_asset({"source": "text", "text": "ZM TOOL", "fontSize": 24, "color": "#ffffff"}, tmp_path)
    assert output == tmp_path / "logo-generated.png"
    assert output.is_file()


def test_video_extensions():
    assert is_video(Path("001.MP4"))
    assert is_video(Path("002.webm"))
    assert not is_video(Path("003.png"))
    assert not is_video(Path("004.jfif"))


def test_drawing_mode_only_renders_still_images(monkeypatch, tmp_path):
    image = tmp_path / "001.png"
    video = tmp_path / "002.mp4"
    drawing_output = tmp_path / "drawing-source.mp4"
    work = tmp_path / "work"
    image.touch()
    video.touch()
    drawing_output.touch()
    work.mkdir()
    submitted: list[Path] = []

    def create_drawing(name, source, options):
        submitted.append(source)
        return {"id": "drawing-1"}

    monkeypatch.setattr("pipeline.srt_image.create_drawing_job", create_drawing)
    batches: list[list[str]] = []
    monkeypatch.setattr("pipeline.srt_image.start_drawing_batch", lambda job_ids: batches.append(job_ids))
    monkeypatch.setattr(
        "pipeline.srt_image.get_drawing_job",
        lambda _job_id: {"status": "done", "output": str(drawing_output)},
    )
    monkeypatch.setattr("pipeline.srt_image._log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pipeline.srt_image._update", lambda *_args, **_kwargs: None)

    rendered = _drawing_video_sources(
        "srt-image-test", [image, video], [5.0, 5.0],
        {"drawing": {"enabled": True}}, work,
    )

    assert submitted == [image]
    assert batches == [["drawing-1"]]
    assert rendered[1] == video


def test_create_job_uses_selected_output(tmp_path):
    selected = tmp_path / "my-video.mp4"
    job = create_job(
        selected.name, tmp_path, [], None, tmp_path / "timeline.txt",
        tmp_path / "subtitles.srt", {}, output_target=selected,
    )
    assert job["output"] == str(selected)


def test_render_cache_key_covers_inputs_and_every_option(tmp_path):
    media = tmp_path / "001.png"
    timeline = tmp_path / "timeline.txt"
    media.write_bytes(b"image-v1")
    timeline.write_text("[00:00:00-00:00:05]", encoding="utf-8")
    job = {
        "images": [str(media)], "timeline": str(timeline), "audio": "",
        "srt": "", "watermark": "", "options": {"fps": 30, "zoom": "off"},
    }

    first = _render_cache_key(job)
    assert _render_cache_key(job) == first
    assert _render_cache_key({**job, "options": {**job["options"], "fps": 60}}) != first
    media.write_bytes(b"image-v2-is-different")
    assert _render_cache_key(job) != first


def test_completed_render_cache_survives_memory_state(monkeypatch, tmp_path):
    import pipeline.srt_image as module
    cache_root = tmp_path / "render-cache"
    monkeypatch.setattr(module, "CACHE_ROOT", cache_root)
    monkeypatch.setattr(module, "CACHE_INDEX", cache_root / "index.json")
    source = tmp_path / "output.mp4"
    source.write_bytes(b"rendered-video")

    cached = _store_cached_render("same-settings", source)

    assert cached.read_bytes() == b"rendered-video"
    assert _cached_render("same-settings") == cached
    assert module.CACHE_INDEX.is_file()


def test_relative_srt_image_output_stays_under_shared_app_folder(monkeypatch, tmp_path):
    monkeypatch.setattr("api.routes.srt_image.downloads_folder", lambda _tab: tmp_path / "ZM_AIO_TOOL" / "subtitles" / "image-video")
    assert _resolve_output_target("series-01/output.mp4") == tmp_path / "ZM_AIO_TOOL" / "subtitles" / "image-video" / "series-01" / "output.mp4"
