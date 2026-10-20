from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

from ai.services.captions import wrap_caption

logger = logging.getLogger(__name__)

# Digital silence is around -90 dB. Anything at or below this is not audible.
SILENT_MEAN_DB = -80.0
SILENT_MAX_DB = -70.0


class FFmpegError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    configured = (settings.FFMPEG_PATH or "").strip()
    if configured:
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise FFmpegError("FFmpeg is not installed.") from exc


TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_SIZE = f"{TARGET_WIDTH}x{TARGET_HEIGHT}"
TARGET_FPS = 30
X264_PRESET = "veryfast"
X264_CRF = "23"
SCENE_TRANSITION_SECONDS = 0.28
LAST_JOIN_MODE = ""


def run_ffmpeg(args: list[str]) -> None:
    command = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        logger.error("FFmpeg failed: %s", completed.stderr[-2000:])
        raise FFmpegError("Video processing failed.")


def _encode_video_args() -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-preset",
        X264_PRESET,
        "-crf",
        X264_CRF,
        "-threads",
        "0",
        "-pix_fmt",
        "yuv420p",
    ]


def _encode_audio_args() -> list[str]:
    return ["-c:a", "aac", "-ar", "44100", "-ac", "2"]


def _scale_filter(size: str) -> str:
    width, height = size.replace("x", ":").split(":")
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={TARGET_FPS}"
    )


def _caption_font() -> tuple[str, str]:
    """CJK-capable caption font. Arial drops Cantonese/Chinese glyphs on this host."""
    configured = Path(str(getattr(settings, "CAPTION_FONT_PATH", "") or "").strip())
    candidates = [
        configured if configured.is_file() else None,
        Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
        Path("/usr/share/fonts/truetype/droid/DroidSansFallback.ttf"),
    ]
    for path in candidates:
        if path and path.is_file():
            return "Droid Sans Fallback", str(path.parent)
    return "Droid Sans Fallback", "/usr/share/fonts/truetype/droid"


def _ass_time(seconds: float) -> str:
    millis = max(0, int(round(float(seconds) * 100)))
    hours, rem = divmod(millis, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{cs:02}"


def _ass_escape(text: str) -> str:
    return (
        str(text or "")
        .replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", r"\N")
    )


def _to_ass(captions: list[dict], placement: str = "bottom") -> str:
    """ASS at 1080x1920 so the story caption sits inside a vertical phone frame."""
    font_name, _ = _caption_font()
    align = 8 if str(placement or "bottom").lower() == "top" else 2
    margin_v = 180 if align == 8 else 220
    events = []
    start = 0.0
    for item in captions:
        text = wrap_caption(item.get("text") or "")
        duration = float(item.get("duration") or 4)
        end = start + duration
        if text:
            events.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{_ass_escape(text)}"
            )
        start = end
    header = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "WrapStyle: 0",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            (
                f"Style: Caption,{font_name},54,&H00FFFFFF,&H00FFFFFF,&H00111111,&H64000000,"
                f"0,0,0,0,100,100,0,0,1,3,0,{align},72,72,{margin_v},1"
            ),
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events,
            "",
        ]
    )
    return header


def _ass_filter(ass_path: Path) -> str:
    escaped = ass_path.as_posix().replace("\\", "/").replace(":", "\\:")
    _, font_dir = _caption_font()
    fontsdir = Path(font_dir).as_posix().replace("\\", "/").replace(":", "\\:")
    if Path(font_dir).is_dir():
        return f"ass='{escaped}':fontsdir='{fontsdir}'"
    return f"ass='{escaped}'"


def _caption_cover_filter() -> str:
    """Hide provider-painted captions in the lower third so only the story caption remains."""
    return "drawbox=x=0:y=ih-640:w=iw:h=640:color=black@1:t=fill"


def _video_filter(size: str, subtitle_filter: str = "") -> str:
    base = _scale_filter(size)
    if not subtitle_filter:
        return base
    return f"{base},{_caption_cover_filter()},{subtitle_filter}"


def ffprobe_bin() -> str | None:
    found = shutil.which("ffprobe")
    if found:
        return found
    ffmpeg = ffmpeg_bin()
    candidate = Path(ffmpeg).with_name(Path(ffmpeg).name.replace("ffmpeg", "ffprobe"))
    if candidate.exists():
        return str(candidate)
    return None


def probe_duration(path: Path) -> float | None:
    report = probe_media(path)
    return report.get("duration")


def probe_media(path: Path) -> dict:
    """Inspect video/audio streams. An AAC track alone does not mean audible audio."""
    empty = {
        "has_video": False,
        "has_audio": False,
        "duration": None,
        "video_duration": None,
        "audio_duration": None,
        "audio_codec": "",
        "video_codec": "",
        "width": None,
        "height": None,
        "fps": None,
    }
    if not path or not Path(path).exists():
        return empty
    probe = ffprobe_bin()
    if probe:
        completed = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,codec_name,duration,width,height,avg_frame_rate",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            try:
                import json

                data = json.loads(completed.stdout)
            except Exception:
                data = {}
            streams = data.get("streams") or []
            fmt = data.get("format") or {}
            duration = _as_float(fmt.get("duration"))
            video_duration = None
            audio_duration = None
            audio_codec = ""
            video_codec = ""
            has_video = False
            has_audio = False
            width = None
            height = None
            fps = None
            for stream in streams:
                kind = str(stream.get("codec_type") or "")
                stream_duration = _as_float(stream.get("duration")) or duration
                if kind == "video":
                    has_video = True
                    video_duration = stream_duration
                    video_codec = str(stream.get("codec_name") or "")
                    width = int(stream.get("width") or 0) or None
                    height = int(stream.get("height") or 0) or None
                    fps = _as_fps(stream.get("avg_frame_rate"))
                elif kind == "audio":
                    has_audio = True
                    audio_duration = stream_duration
                    audio_codec = str(stream.get("codec_name") or "")
            return {
                "has_video": has_video,
                "has_audio": has_audio,
                "duration": duration or video_duration or audio_duration,
                "video_duration": video_duration or duration,
                "audio_duration": audio_duration,
                "audio_codec": audio_codec,
                "video_codec": video_codec,
                "width": width,
                "height": height,
                "fps": fps,
            }
    completed = subprocess.run(
        [ffmpeg_bin(), "-i", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    text = completed.stderr or ""
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", text)
    duration = None
    if match:
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    video_match = re.search(r"Video:.*?\s(\d{2,5})x(\d{2,5})", text)
    fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", text)
    return {
        "has_video": bool(re.search(r"Stream #\d+:\d+.*Video:", text)),
        "has_audio": bool(re.search(r"Stream #\d+:\d+.*Audio:", text)),
        "duration": duration,
        "video_duration": duration,
        "audio_duration": duration if re.search(r"Stream #\d+:\d+.*Audio:", text) else None,
        "audio_codec": "",
        "video_codec": "",
        "width": int(video_match.group(1)) if video_match else None,
        "height": int(video_match.group(2)) if video_match else None,
        "fps": _as_float(fps_match.group(1)) if fps_match else None,
    }


def measure_volume(path: Path) -> dict:
    """Return mean/max volume in dB. Missing values mean the measurement could not run."""
    if not path or not Path(path).exists():
        return {}
    completed = subprocess.run(
        [
            ffmpeg_bin(),
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    text = (completed.stderr or "") + (completed.stdout or "")
    mean = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", text)
    peak = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", text)
    report = {}
    if mean:
        report["mean_volume"] = float(mean.group(1))
    if peak:
        report["max_volume"] = float(peak.group(1))
    return report


def inspect_audio(path: Path) -> dict:
    """Decide whether a file has real audible audio, not just an empty AAC stream."""
    probe = probe_media(path)
    volume = measure_volume(path) if probe.get("has_audio") else {}
    mean = volume.get("mean_volume")
    peak = volume.get("max_volume")
    video_duration = probe.get("video_duration") or probe.get("duration") or 0
    audio_duration = probe.get("audio_duration") or (video_duration if probe.get("has_audio") else 0)
    coverage = 1.0
    if video_duration and audio_duration:
        coverage = min(float(audio_duration) / float(video_duration), 1.0)
    silent = False
    if mean is not None and mean <= SILENT_MEAN_DB:
        silent = True
    if peak is not None and peak <= SILENT_MAX_DB and (mean is None or mean <= SILENT_MEAN_DB + 5):
        silent = True
    audible = bool(probe.get("has_audio") and not silent and mean is not None and mean > SILENT_MEAN_DB)
    if coverage < 0.5:
        audible = False
    reason = ""
    if not probe.get("has_audio"):
        reason = "No audio stream in the generated file."
    elif silent or (mean is not None and mean <= SILENT_MEAN_DB):
        reason = "Audio track is present but effectively silent"
    elif coverage < 0.5:
        reason = "Audio does not cover the expected video duration."
    elif mean is None and probe.get("has_audio"):
        reason = "Audio level could not be measured."
    return {
        **probe,
        **volume,
        "coverage": round(coverage, 3),
        "audible": audible,
        "silent": silent or (mean is not None and mean <= SILENT_MEAN_DB),
        "reason": reason,
        "measured": mean is not None,
    }


def _as_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_fps(value) -> float | None:
    raw = str(value or "").strip()
    if not raw or raw in {"0/0", "N/A"}:
        return None
    if "/" in raw:
        num, den = raw.split("/", 1)
        top = _as_float(num)
        bottom = _as_float(den)
        if top is None or not bottom:
            return None
        return top / bottom
    return _as_float(raw)


def clip_is_assembly_ready(path: Path, size: str = TARGET_SIZE) -> bool:
    """True when a clip can be concat-copied without another x264 pass."""
    report = probe_media(path)
    try:
        width, height = size.replace("x", ":").split(":")
        target_w, target_h = int(width), int(height)
    except (TypeError, ValueError):
        target_w, target_h = TARGET_WIDTH, TARGET_HEIGHT
    fps = report.get("fps") or 0
    return bool(
        report.get("has_video")
        and report.get("has_audio")
        and report.get("width") == target_w
        and report.get("height") == target_h
        and abs(float(fps) - TARGET_FPS) < 0.6
    )


def image_to_clip(image_path: Path, dest: Path, duration: float, size: str = TARGET_SIZE) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-loop",
            "1",
            "-i",
            str(image_path),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            str(max(duration, 1)),
            "-vf",
            _scale_filter(size),
            *_encode_video_args(),
            *_encode_audio_args(),
            "-shortest",
            str(dest),
        ]
    )
    return dest


def prepare_scene_clip(
    source: Path,
    dest: Path,
    *,
    caption: str = "",
    duration: float | None = None,
    placement: str = "bottom",
    size: str = TARGET_SIZE,
) -> Path:
    """One encode: scale to 9:16, optional burned-in caption. Used while each scene is generated."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = wrap_caption(caption or "")
    ass_path = dest.with_suffix(".ass")
    subtitle = ""
    if text:
        clip_duration = float(duration or probe_duration(source) or 4)
        ass_path.write_text(
            _to_ass([{"text": text, "duration": clip_duration}], placement),
            encoding="utf-8",
        )
        subtitle = _ass_filter(ass_path)
    has_audio = bool(probe_media(source).get("has_audio"))
    vf = _video_filter(size, subtitle)
    args = ["-i", str(source)]
    if has_audio:
        args.extend(
            [
                "-vf",
                vf,
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                *_encode_video_args(),
                *_encode_audio_args(),
                "-shortest",
            ]
        )
    else:
        args.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=44100:cl=stereo",
                "-filter_complex",
                f"[0:v]{vf}[v]",
                "-map",
                "[v]",
                "-map",
                "1:a",
                *_encode_video_args(),
                *_encode_audio_args(),
                "-shortest",
            ]
        )
    if duration:
        args.extend(["-t", str(duration)])
    args.append(str(dest))
    try:
        run_ffmpeg(args)
    finally:
        ass_path.unlink(missing_ok=True)
    return dest


def normalize_clip(source: Path, dest: Path, duration: float | None = None, size: str = TARGET_SIZE) -> Path:
    if clip_is_assembly_ready(source, size) and not duration:
        if source.resolve() != dest.resolve():
            dest.write_bytes(source.read_bytes())
        return dest
    return prepare_scene_clip(source, dest, duration=duration, size=size)


def concat_clips(clips: list[Path], dest: Path, *, fade: float | None = None) -> Path:
    global LAST_JOIN_MODE
    dest.parent.mkdir(parents=True, exist_ok=True)
    overlap = SCENE_TRANSITION_SECONDS if fade is None else float(fade)
    if len(clips) >= 2 and overlap > 0:
        try:
            LAST_JOIN_MODE = "reencode"
            return _concat_with_fade(clips, dest, overlap)
        except FFmpegError:
            logger.warning("Crossfade join failed; falling back to hard concat for %s clips", len(clips))
    listing = dest.with_suffix(".txt")
    listing.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in clips),
        encoding="utf-8",
    )
    concat_input = [
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listing),
    ]
    try:
        run_ffmpeg([*concat_input, "-c", "copy", str(dest)])
        LAST_JOIN_MODE = "copy"
        logger.info("join_mode=copy clips=%s reason=stream_copy", len(clips))
        return dest
    except FFmpegError:
        logger.warning("join_mode=reencode clips=%s reason=stream_copy_failed", len(clips))
    run_ffmpeg(
        [
            *concat_input,
            *_encode_video_args(),
            *_encode_audio_args(),
            str(dest),
        ]
    )
    LAST_JOIN_MODE = "reencode"
    return dest


def split_copy(source: Path, dest: Path, start: float, end: float) -> Path:
    """Copy a time range without re-encoding. Used to rebuild storyboard clips."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.1, float(end) - float(start))
    run_ffmpeg(
        [
            "-ss",
            f"{max(0.0, float(start)):.3f}",
            "-i",
            str(source),
            "-t",
            f"{duration:.3f}",
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(dest),
        ]
    )
    return dest


def trim_copy(source: Path, dest: Path, duration: float) -> Path:
    """Keep the first `duration` seconds. Stream-copy first; re-encode if copy fails."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    length = max(0.1, float(duration))
    try:
        split_copy(source, dest, 0.0, length)
        if dest.exists() and dest.stat().st_size > 0:
            return dest
    except FFmpegError:
        logger.warning("trim stream-copy failed; re-encoding to %ss", length)
    run_ffmpeg(
        [
            "-i",
            str(source),
            "-t",
            f"{length:.3f}",
            *_encode_video_args(),
            *_encode_audio_args(),
            str(dest),
        ]
    )
    return dest


def _concat_with_fade(clips: list[Path], dest: Path, fade: float) -> Path:
    durations = [float(probe_duration(path) or 0) for path in clips]
    if any(duration <= fade + 0.2 for duration in durations):
        raise FFmpegError("Clips are too short for a crossfade.")
    inputs: list[str] = []
    for path in clips:
        inputs.extend(["-i", str(path)])
    video_filters = []
    audio_filters = []
    last_v = "0:v"
    last_a = "0:a"
    elapsed = durations[0]
    for index in range(1, len(clips)):
        offset = elapsed - fade
        v_out = f"v{index}"
        a_out = f"a{index}"
        video_filters.append(
            f"[{last_v}][{index}:v]xfade=transition=fade:duration={fade:.3f}:offset={offset:.3f}[{v_out}]"
        )
        audio_filters.append(f"[{last_a}][{index}:a]acrossfade=d={fade:.3f}[{a_out}]")
        last_v = v_out
        last_a = a_out
        elapsed = elapsed + durations[index] - fade
    run_ffmpeg(
        [
            *inputs,
            "-filter_complex",
            ";".join([*video_filters, *audio_filters]),
            "-map",
            f"[{last_v}]",
            "-map",
            f"[{last_a}]",
            *_encode_video_args(),
            *_encode_audio_args(),
            str(dest),
        ]
    )
    return dest


def mix_narration(video_path: Path, audio_path: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-c:v",
            "copy",
            "-filter:a",
            "apad",
            "-c:a",
            "aac",
            "-shortest",
            str(dest),
        ]
    )
    return dest


def burn_captions(video_path: Path, captions: list[dict], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    placement = "top" if _caption_alignment(captions) == 8 else "bottom"
    ass_path = dest.with_suffix(".ass")
    ass_path.write_text(_to_ass(captions, placement), encoding="utf-8")
    try:
        run_ffmpeg(
            [
                "-i",
                str(video_path),
                "-vf",
                _ass_filter(ass_path),
                *_encode_video_args(),
                "-c:a",
                "copy",
                str(dest),
            ]
        )
    finally:
        ass_path.unlink(missing_ok=True)
    return dest


def _caption_alignment(captions: list[dict]) -> int:
    placements = [str(item.get("placement") or "bottom").lower() for item in captions if item.get("text")]
    if placements and all(item == "top" for item in placements):
        return 8
    return 2


def export_vertical(source: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if clip_is_assembly_ready(source):
        run_ffmpeg(
            [
                "-i",
                str(source),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(dest),
            ]
        )
        return dest
    run_ffmpeg(
        [
            "-i",
            str(source),
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1",
            *_encode_video_args(),
            *_encode_audio_args(),
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )
    return dest


def assemble_project(
    clips: list[Path],
    audio_path: Path | None,
    captions: list[dict],
    dest: Path,
    *,
    mix_external_audio: bool = False,
    captions_already_burned: bool = False,
) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        ready = []
        for index, clip in enumerate(clips):
            caption = dict(captions[index]) if index < len(captions) else {"text": "", "duration": 4}
            text = wrap_caption(caption.get("text") or "") if not captions_already_burned else ""
            needs_caption = bool(text)
            if clip_is_assembly_ready(clip) and not needs_caption:
                ready.append(clip)
                continue
            out = tmp_dir / f"clip-{index}.mp4"
            prepare_scene_clip(
                clip,
                out,
                caption=text,
                placement=str(caption.get("placement") or "bottom"),
            )
            ready.append(out)
        combined = tmp_dir / "combined.mp4"
        concat_clips(ready, combined)
        current = combined
        if mix_external_audio and audio_path and Path(audio_path).exists():
            voiced = tmp_dir / "voiced.mp4"
            mix_narration(current, Path(audio_path), voiced)
            current = voiced
        return export_vertical(current, dest)


def _to_srt(captions: list[dict]) -> str:
    chunks = []
    start = 0.0
    for index, item in enumerate(captions, start=1):
        duration = float(item.get("duration") or 4)
        end = start + duration
        chunks.append(
            f"{index}\n{_ts(start)} --> {_ts(end)}\n{wrap_caption(item.get('text') or '')}\n"
        )
        start = end
    return "\n".join(chunks)


def _ts(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def sample_plan(duration: float) -> list[float]:
    """Representative timestamps. Short clips use fewer frames."""
    length = max(float(duration or 0), 0.2)
    if length <= 3:
        points = [0.05, max(length - 0.08, 0.1)]
    elif length <= 8:
        points = [0.05, length * 0.5, max(length - 0.08, 0.1)]
    else:
        points = [
            0.05,
            length * 0.2,
            length * 0.5,
            length * 0.8,
            max(length - 0.08, 0.1),
        ]
    cleaned = []
    for point in points:
        value = min(max(point, 0.0), max(length - 0.04, 0.0))
        if cleaned and abs(value - cleaned[-1]) < 0.04:
            continue
        cleaned.append(round(value, 3))
    return cleaned or [0.0]


def sample_frames(video_path: Path, dest_dir: Path, timestamps: list[float] | None = None) -> list[tuple[float, Path]]:
    """Extract a few JPEG frames. Returns (timestamp, path) for frames that actually exist."""
    if not video_path or not Path(video_path).exists():
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(Path(video_path)) or 0
    plan = timestamps if timestamps is not None else sample_plan(duration)
    frames = []
    for index, stamp in enumerate(plan):
        dest = dest_dir / f"frame-{index}-{int(stamp * 1000)}.jpg"
        try:
            run_ffmpeg(
                [
                    "-ss",
                    f"{stamp:.3f}",
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    str(dest),
                ]
            )
        except FFmpegError:
            logger.warning("Frame sample failed at %ss from %s", stamp, video_path)
            continue
        if dest.exists() and dest.stat().st_size > 0:
            frames.append((stamp, dest))
    return frames


def extract_first_frame(video_path: Path, dest: Path) -> Path:
    run_ffmpeg(
        [
            "-ss",
            "0",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(dest),
        ]
    )
    if not dest.exists() or dest.stat().st_size < 32:
        raise FFmpegError("Could not capture the first screen of this video.")
    return dest


def extract_audio(video_path: Path, dest: Path) -> Path | None:
    if not video_path or not Path(video_path).exists():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_ffmpeg(
            [
                "-i",
                str(video_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "libmp3lame",
                str(dest),
            ]
        )
    except FFmpegError:
        logger.warning("Audio extract failed from %s", video_path)
        return None
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    return None

