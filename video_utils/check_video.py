#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch video metadata audit & statistics (ffprobe-based).

Goals
- Fast "inventory" of a batch of videos (even if extensions lie).
- Save per-file normalized metadata (JSONL + CSV).
- Produce an aggregated summary (JSON + Markdown report).
- Optional "deep" mode to count frames via ffprobe -count_frames (slower).

Requirements
- ffprobe (from FFmpeg) available in PATH.

Usage
  python video_meta_audit.py /path/to/videos -o out
  python video_meta_audit.py /path/to/videos --glob "*.MP4" --recursive -o out
  python video_meta_audit.py /path/to/videos --all-files --deep -o out
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# -----------------------------
# Utilities
# -----------------------------

def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def which_or_die(exe: str) -> str:
    p = shutil.which(exe)
    if not p:
        raise SystemExit(f"[FATAL] '{exe}' not found in PATH. Please install FFmpeg (ffprobe).")
    return p


def safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        x = str(x).strip()
        if x == "" or x.lower() in {"nan", "n/a"}:
            return None
        return float(x)
    except Exception:
        return None


def safe_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        if isinstance(x, bool):
            return int(x)
        if isinstance(x, int):
            return x
        x = str(x).strip()
        if x == "" or x.lower() in {"nan", "n/a"}:
            return None
        # some fields are float-ish but integral
        return int(float(x))
    except Exception:
        return None


def rat_to_float(r: Any) -> Optional[float]:
    """
    Convert ffprobe rational like "30000/1001" to float.
    """
    if r is None:
        return None
    if isinstance(r, (int, float)):
        return float(r)
    s = str(r).strip()
    if not s or s in {"0/0", "N/A"}:
        return None
    if "/" in s:
        num, den = s.split("/", 1)
        try:
            num_f = float(num)
            den_f = float(den)
            if den_f == 0:
                return None
            return num_f / den_f
        except Exception:
            return None
    return safe_float(s)


def pct(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    vs = sorted(values)
    k = (len(vs) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return vs[int(k)]
    return vs[f] * (c - k) + vs[c] * (k - f)


def human_bytes(n: Optional[int]) -> str:
    if n is None:
        return "N/A"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.2f} {u}"
        f /= 1024
    return f"{f:.2f} B"


def human_seconds(s: Optional[float]) -> str:
    if s is None:
        return "N/A"
    # keep it simple
    if s < 60:
        return f"{s:.2f}s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{int(m)}m{sec:05.2f}s"
    h, m = divmod(m, 60)
    return f"{int(h)}h{int(m):02d}m{sec:05.2f}s"


@dataclass
class ProbeResult:
    path: str
    ok: bool
    used_input_format: Optional[str]
    ffprobe_stdout: Optional[str]
    ffprobe_stderr: Optional[str]
    data: Optional[Dict[str, Any]]
    error_message: Optional[str]


# -----------------------------
# File discovery
# -----------------------------

DEFAULT_GLOBS = ["*.mp4", "*.MP4", "*.mov", "*.MOV", "*.mkv", "*.MKV", "*.avi", "*.AVI",
                "*.ts", "*.TS", "*.m2ts", "*.M2TS", "*.webm", "*.WEBM", "*.mpg", "*.MPG",
                "*.mpeg", "*.MPEG", "*.h264", "*.H264", "*.264", "*.hevc", "*.HEVC", "*.h265", "*.H265"]


def iter_files(roots: List[Path], globs: List[str], recursive: bool, all_files: bool) -> Iterable[Path]:
    seen = set()
    for root in roots:
        if root.is_file():
            p = root.resolve()
            if p not in seen:
                seen.add(p)
                yield p
            continue
        if not root.exists():
            continue
        if all_files:
            it = root.rglob("*") if recursive else root.glob("*")
            for p in it:
                if p.is_file():
                    rp = p.resolve()
                    if rp not in seen:
                        seen.add(rp)
                        yield rp
        else:
            for g in globs:
                it = root.rglob(g) if recursive else root.glob(g)
                for p in it:
                    if p.is_file():
                        rp = p.resolve()
                        if rp not in seen:
                            seen.add(rp)
                            yield rp


# -----------------------------
# ffprobe
# -----------------------------

FFPROBE_RETRY_INPUT_FORMATS = [
    # raw bitstreams / common containers that "lie" behind .mp4 extension
    "h264", "hevc",
    "mpegts", "matroska", "mov", "avi",
]

KNOWN_BAD_HINTS = [
    "moov atom not found",
    "Invalid data found",
    "could not find codec parameters",
    "error reading header",
    "unknown format",
    "End of file",
]


def run_ffprobe(path: Path,
               deep: bool,
               timeout_s: int,
               probesize: Optional[int],
               analyzeduration: Optional[int],
               input_format: Optional[str] = None) -> ProbeResult:

    ffprobe = which_or_die("ffprobe")
    args = [ffprobe, "-hide_banner"]

    # Keep stderr for diagnostics; json goes to stdout.
    # Use -v error: only error messages
    args += ["-v", "error"]

    # AVOptions for probing (if provided)
    if probesize is not None:
        args += ["-probesize", str(probesize)]
    if analyzeduration is not None:
        args += ["-analyzeduration", str(analyzeduration)]

    # Force demuxer/format (useful if extension lies or file is raw)
    if input_format:
        args += ["-f", input_format]

    # Machine-readable output
    args += ["-of", "json"]

    # What to show
    args += ["-show_format", "-show_streams", "-show_error"]

    if deep:
        # Counts frames per stream; can be slow on long videos.
        args += ["-count_frames"]

    args += [str(path)]

    try:
        cp = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(
            path=str(path),
            ok=False,
            used_input_format=input_format,
            ffprobe_stdout=None,
            ffprobe_stderr=None,
            data=None,
            error_message=f"timeout after {timeout_s}s",
        )
    except Exception as e:
        return ProbeResult(
            path=str(path),
            ok=False,
            used_input_format=input_format,
            ffprobe_stdout=None,
            ffprobe_stderr=None,
            data=None,
            error_message=f"exception: {e}",
        )

    stdout = cp.stdout.strip() if cp.stdout else ""
    stderr = cp.stderr.strip() if cp.stderr else ""

    if cp.returncode != 0:
        # Sometimes ffprobe still prints partial JSON; try parse.
        parsed = None
        if stdout:
            try:
                parsed = json.loads(stdout)
            except Exception:
                parsed = None
        return ProbeResult(
            path=str(path),
            ok=False,
            used_input_format=input_format,
            ffprobe_stdout=stdout or None,
            ffprobe_stderr=stderr or None,
            data=parsed,
            error_message=f"ffprobe exit code {cp.returncode}",
        )

    try:
        data = json.loads(stdout) if stdout else {}
        return ProbeResult(
            path=str(path),
            ok=True,
            used_input_format=input_format,
            ffprobe_stdout=stdout or None,
            ffprobe_stderr=stderr or None,
            data=data,
            error_message=None,
        )
    except Exception as e:
        return ProbeResult(
            path=str(path),
            ok=False,
            used_input_format=input_format,
            ffprobe_stdout=stdout or None,
            ffprobe_stderr=stderr or None,
            data=None,
            error_message=f"json parse error: {e}",
        )


def probe_with_retries(path: Path,
                       deep: bool,
                       timeout_s: int,
                       probesize: Optional[int],
                       analyzeduration: Optional[int],
                       enable_forced_formats: bool) -> ProbeResult:
    # First try normal probe
    r0 = run_ffprobe(path, deep, timeout_s, probesize, analyzeduration, input_format=None)
    if r0.ok:
        return r0

    # If not enabled, stop
    if not enable_forced_formats:
        return r0

    # Heuristic: only retry if stderr or parsed error hints match
    hint_text = " ".join(filter(None, [r0.ffprobe_stderr, r0.ffprobe_stdout, r0.error_message]))
    if not any(h.lower() in hint_text.lower() for h in KNOWN_BAD_HINTS):
        return r0

    # Retry with forced input formats
    for fmt in FFPROBE_RETRY_INPUT_FORMATS:
        r = run_ffprobe(path, deep, timeout_s, probesize, analyzeduration, input_format=fmt)
        if r.ok:
            return r

    return r0


# -----------------------------
# Normalization / feature extraction
# -----------------------------

def select_main_video_stream(streams: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    videos = [s for s in streams if s.get("codec_type") == "video"]
    if not videos:
        return None

    def score(s: Dict[str, Any]) -> Tuple[int, int, int]:
        w = safe_int(s.get("width")) or 0
        h = safe_int(s.get("height")) or 0
        area = w * h
        # prefer usable streams
        has_dim = 1 if area > 0 else 0
        # prefer more frames if known
        frames = safe_int(s.get("nb_frames")) or safe_int(s.get("nb_read_frames")) or 0
        return (has_dim, area, frames)

    return sorted(videos, key=score, reverse=True)[0]


def select_main_audio_stream(streams: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if not audios:
        return None

    def score(s: Dict[str, Any]) -> Tuple[int, int]:
        ch = safe_int(s.get("channels")) or 0
        sr = safe_int(s.get("sample_rate")) or 0
        return (ch, sr)

    return sorted(audios, key=score, reverse=True)[0]


def normalize_record(path: Path, pr: ProbeResult) -> Dict[str, Any]:
    st = path.stat()
    base: Dict[str, Any] = {
        "path": str(path),
        "name": path.name,
        "ext": path.suffix,
        "size_bytes": st.st_size,
        "mtime": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        "probe_ok": pr.ok,
        "used_input_format": pr.used_input_format,
        "ffprobe_error": pr.error_message,
    }

    data = pr.data or {}
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    err = data.get("error") or {}

    base["format_name"] = fmt.get("format_name")
    base["format_long_name"] = fmt.get("format_long_name")
    base["probe_score"] = safe_int(fmt.get("probe_score"))
    base["duration_s"] = safe_float(fmt.get("duration"))
    base["start_time"] = safe_float(fmt.get("start_time"))
    base["bit_rate"] = safe_int(fmt.get("bit_rate"))
    base["nb_streams"] = safe_int(fmt.get("nb_streams"))
    base["tags"] = fmt.get("tags") or {}

    base["error_string"] = err.get("string") or (pr.ffprobe_stderr or "")
    base["error_code"] = err.get("code")
    base["error_errno"] = err.get("errno")

    v = select_main_video_stream(streams)
    a = select_main_audio_stream(streams)

    # --- video fields
    if v:
        w = safe_int(v.get("width"))
        h = safe_int(v.get("height"))
        base["v_codec"] = v.get("codec_name")
        base["v_codec_long"] = v.get("codec_long_name")
        base["v_profile"] = v.get("profile")
        base["v_level"] = safe_int(v.get("level"))
        base["v_pix_fmt"] = v.get("pix_fmt")
        base["v_width"] = w
        base["v_height"] = h
        base["v_coded_width"] = safe_int(v.get("coded_width"))
        base["v_coded_height"] = safe_int(v.get("coded_height"))
        base["v_field_order"] = v.get("field_order")
        base["v_color_space"] = v.get("color_space")
        base["v_color_transfer"] = v.get("color_transfer")
        base["v_color_primaries"] = v.get("color_primaries")
        base["v_color_range"] = v.get("color_range")
        base["v_chroma_location"] = v.get("chroma_location")
        base["v_time_base"] = v.get("time_base")
        base["v_r_frame_rate"] = v.get("r_frame_rate")
        base["v_avg_frame_rate"] = v.get("avg_frame_rate")
        base["v_fps"] = rat_to_float(v.get("avg_frame_rate")) or rat_to_float(v.get("r_frame_rate"))
        base["v_nb_frames"] = safe_int(v.get("nb_frames"))
        base["v_nb_read_frames"] = safe_int(v.get("nb_read_frames"))  # only when -count_frames
        base["v_bit_rate"] = safe_int(v.get("bit_rate"))
        base["v_duration_s"] = safe_float(v.get("duration"))
        base["v_start_time"] = safe_float(v.get("start_time"))
        base["v_tags"] = v.get("tags") or {}
        # rotation often in tags
        rot = None
        tags = base["v_tags"]
        if isinstance(tags, dict):
            rot = tags.get("rotate")
        base["v_rotate"] = safe_int(rot)
        if w and h:
            base["v_area"] = int(w) * int(h)
    else:
        base["v_codec"] = None

    # --- audio fields
    if a:
        base["a_codec"] = a.get("codec_name")
        base["a_codec_long"] = a.get("codec_long_name")
        base["a_sample_rate"] = safe_int(a.get("sample_rate"))
        base["a_channels"] = safe_int(a.get("channels"))
        base["a_channel_layout"] = a.get("channel_layout")
        base["a_bit_rate"] = safe_int(a.get("bit_rate"))
        base["a_duration_s"] = safe_float(a.get("duration"))
        base["a_tags"] = a.get("tags") or {}
    else:
        base["a_codec"] = None

    # --- anomalies
    anomalies: List[str] = []
    if not pr.ok:
        anomalies.append("ffprobe_failed")
    if base.get("duration_s") is not None and base["duration_s"] <= 0:
        anomalies.append("duration_non_positive")
    if v is None:
        anomalies.append("no_video_stream")
    if v is not None and (base.get("v_width") in (None, 0) or base.get("v_height") in (None, 0)):
        anomalies.append("video_no_dimensions")
    if base.get("v_fps") is not None and base["v_fps"] <= 0:
        anomalies.append("fps_non_positive")
    if base.get("bit_rate") is not None and base["bit_rate"] <= 0:
        anomalies.append("bitrate_non_positive")
    if isinstance(base.get("error_string"), str) and "moov atom not found" in base["error_string"].lower():
        anomalies.append("moov_atom_not_found")
    base["anomalies"] = anomalies

    return base


# -----------------------------
# Aggregation / reporting
# -----------------------------

def compute_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    stats: Dict[str, Any] = {}
    total = len(rows)
    ok = sum(1 for r in rows if r.get("probe_ok"))
    failed = total - ok

    stats["total_files"] = total
    stats["probe_ok"] = ok
    stats["probe_failed"] = failed

    # Counters
    c_format = Counter(r.get("format_name") or "UNKNOWN" for r in rows)
    c_vcodec = Counter(r.get("v_codec") or "NONE" for r in rows)
    c_acodec = Counter(r.get("a_codec") or "NONE" for r in rows)
    c_res = Counter(f"{r.get('v_width')}x{r.get('v_height')}" if r.get("v_width") and r.get("v_height") else "UNKNOWN" for r in rows)
    c_pix = Counter(r.get("v_pix_fmt") or "UNKNOWN" for r in rows)

    # FPS bucket (rounded)
    def fps_bucket(v: Optional[float]) -> str:
        if v is None:
            return "UNKNOWN"
        # keep common broadcast framerates distinct
        for target in [23.976, 24, 25, 29.97, 30, 50, 59.94, 60]:
            if abs(v - target) < 0.02:
                return str(target)
        return f"{round(v, 2)}"

    c_fps = Counter(fps_bucket(safe_float(r.get("v_fps"))) for r in rows)

    stats["top_formats"] = c_format.most_common(20)
    stats["top_video_codecs"] = c_vcodec.most_common(20)
    stats["top_audio_codecs"] = c_acodec.most_common(20)
    stats["top_resolutions"] = c_res.most_common(20)
    stats["top_pix_fmt"] = c_pix.most_common(20)
    stats["top_fps"] = c_fps.most_common(20)

    # Numeric distributions
    sizes = [float(r["size_bytes"]) for r in rows if isinstance(r.get("size_bytes"), int)]
    durations = [float(r["duration_s"]) for r in rows if isinstance(r.get("duration_s"), (int, float))]
    bitrates = [float(r["bit_rate"]) for r in rows if isinstance(r.get("bit_rate"), int)]
    widths = [float(r["v_width"]) for r in rows if isinstance(r.get("v_width"), int)]
    heights = [float(r["v_height"]) for r in rows if isinstance(r.get("v_height"), int)]
    fpss = [float(r["v_fps"]) for r in rows if isinstance(r.get("v_fps"), (int, float))]

    def summarize_num(vs: List[float]) -> Dict[str, Any]:
        if not vs:
            return {}
        return {
            "count": len(vs),
            "min": min(vs),
            "p50": pct(vs, 0.50),
            "p90": pct(vs, 0.90),
            "p99": pct(vs, 0.99),
            "max": max(vs),
            "mean": sum(vs) / len(vs),
        }

    stats["size_bytes"] = summarize_num(sizes)
    stats["duration_s"] = summarize_num(durations)
    stats["bit_rate"] = summarize_num(bitrates)
    stats["width"] = summarize_num(widths)
    stats["height"] = summarize_num(heights)
    stats["fps"] = summarize_num(fpss)

    # Anomalies
    anomaly_counter = Counter(a for r in rows for a in (r.get("anomalies") or []))
    stats["anomalies"] = anomaly_counter.most_common()

    return stats


def write_outputs(out_dir: Path,
                  rows: List[Dict[str, Any]],
                  stats: Dict[str, Any],
                  args: argparse.Namespace) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSONL: one record per file
    jsonl_path = out_dir / "metadata.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # CSV (flat)
    csv_path = out_dir / "metadata.csv"
    # choose a stable set of columns
    cols = [
        "path", "name", "ext", "size_bytes", "mtime",
        "probe_ok", "used_input_format", "ffprobe_error",
        "format_name", "format_long_name", "probe_score",
        "duration_s", "bit_rate", "nb_streams",
        "v_codec", "v_profile", "v_level", "v_pix_fmt",
        "v_width", "v_height", "v_fps", "v_nb_frames", "v_nb_read_frames", "v_rotate",
        "a_codec", "a_channels", "a_sample_rate", "a_channel_layout",
        "anomalies", "error_string",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            rr = dict(r)
            rr["anomalies"] = ",".join(rr.get("anomalies") or [])
            w.writerow(rr)

    # Summary JSON
    summary_json = out_dir / "summary.json"
    with summary_json.open("w", encoding="utf-8") as f:
        payload = {
            "generated_at": now_iso(),
            "args": vars(args),
            "environment": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
            },
            "stats": stats,
        }
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # Markdown report (human friendly)
    report = out_dir / "report.md"
    with report.open("w", encoding="utf-8") as f:
        f.write(f"# Video Metadata Audit Report\n\n")
        f.write(f"- Generated at: `{now_iso()}`\n")
        f.write(f"- Total files: **{stats.get('total_files', 0)}**\n")
        f.write(f"- Probe OK: **{stats.get('probe_ok', 0)}**\n")
        f.write(f"- Probe Failed: **{stats.get('probe_failed', 0)}**\n\n")

        def write_top(title: str, items: List[Tuple[Any, Any]]) -> None:
            f.write(f"## {title}\n\n")
            f.write("| Item | Count |\n|---|---:|\n")
            for k, v in items:
                f.write(f"| {k} | {v} |\n")
            f.write("\n")

        write_top("Top Container Formats (format_name)", stats.get("top_formats", []))
        write_top("Top Video Codecs", stats.get("top_video_codecs", []))
        write_top("Top Audio Codecs", stats.get("top_audio_codecs", []))
        write_top("Top Resolutions", stats.get("top_resolutions", []))
        write_top("Top Pixel Formats", stats.get("top_pix_fmt", []))
        write_top("Top FPS (bucketed)", stats.get("top_fps", []))

        f.write("## Numeric Summaries\n\n")
        for k in ["size_bytes", "duration_s", "bit_rate", "width", "height", "fps"]:
            s = stats.get(k, {})
            if not s:
                continue
            f.write(f"### {k}\n\n")
            f.write("```json\n")
            f.write(json.dumps(s, indent=2))
            f.write("\n```\n\n")

        f.write("## Anomalies\n\n")
        f.write("| Anomaly | Count |\n|---|---:|\n")
        for k, v in stats.get("anomalies", []):
            f.write(f"| {k} | {v} |\n")
        f.write("\n")

    # Failures file
    failed_txt = out_dir / "failed_files.txt"
    with failed_txt.open("w", encoding="utf-8") as f:
        for r in rows:
            if not r.get("probe_ok"):
                f.write(f"{r.get('path')}\t{r.get('ffprobe_error')}\t{(r.get('error_string') or '').strip()}\n")


# -----------------------------
# Main
# -----------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Batch video metadata audit & statistics (ffprobe-based).")
    ap.add_argument("inputs", nargs="+", help="Video files or directories.")
    ap.add_argument("-o", "--out", default="video_meta_out", help="Output directory.")
    ap.add_argument("--glob", action="append", default=None,
                    help="Glob pattern(s) to include (default: common video extensions). Can be specified multiple times.")
    ap.add_argument("--all-files", action="store_true",
                    help="Scan all files (ignore glob). Use with care if directory is huge.")
    ap.add_argument("--recursive", action="store_true", default=True, help="Recurse into subdirectories (default: true).")
    ap.add_argument("--no-recursive", dest="recursive", action="store_false", help="Disable recursion.")
    ap.add_argument("--workers", type=int, default=max(1, min(32, (os.cpu_count() or 8))),
                    help="Parallel workers (threads). Default: min(32, cpu_count).")
    ap.add_argument("--timeout", type=int, default=60, help="Per-file ffprobe timeout seconds.")
    ap.add_argument("--deep", action="store_true", help="Use ffprobe -count_frames (slower but gets nb_read_frames).")
    ap.add_argument("--enable-forced-formats", action="store_true",
                    help="If probe fails with certain errors, retry with forced input formats (h264/hevc/mpegts/etc).")
    ap.add_argument("--probesize", type=int, default=None,
                    help="ffprobe -probesize (bytes). Increase if format detection fails (may slow probing).")
    ap.add_argument("--analyzeduration", type=int, default=None,
                    help="ffprobe -analyzeduration (microseconds). Increase if format detection fails (may slow probing).")
    ap.add_argument("--max-files", type=int, default=None, help="For quick tests; limit number of processed files.")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    roots = [Path(p) for p in args.inputs]
    globs = args.glob if args.glob else DEFAULT_GLOBS

    files = list(iter_files(roots, globs, args.recursive, args.all_files))
    files.sort(key=lambda p: str(p).lower())

    if args.max_files is not None:
        files = files[: args.max_files]

    if not files:
        print("[WARN] No files found. Check your input paths / patterns.", file=sys.stderr)
        return 2

    print(f"[INFO] Found {len(files)} file(s). workers={args.workers} deep={args.deep} forced_formats={args.enable_forced_formats}")

    rows: List[Dict[str, Any]] = []
    # Probe in parallel
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        fut_map = {
            ex.submit(probe_with_retries, p, args.deep, args.timeout, args.probesize, args.analyzeduration, args.enable_forced_formats): p
            for p in files
        }
        done = 0
        for fut in cf.as_completed(fut_map):
            p = fut_map[fut]
            try:
                pr = fut.result()
            except Exception as e:
                pr = ProbeResult(path=str(p), ok=False, used_input_format=None,
                                 ffprobe_stdout=None, ffprobe_stderr=None, data=None,
                                 error_message=f"worker exception: {e}")
            rows.append(normalize_record(p, pr))
            done += 1
            if done % 50 == 0 or done == len(files):
                print(f"[INFO] {done}/{len(files)} processed...")

    # Stable order in outputs
    rows.sort(key=lambda r: r.get("path", ""))

    stats = compute_stats(rows)

    out_dir = Path(args.out)
    write_outputs(out_dir, rows, stats, args)

    print(f"[DONE] Wrote outputs to: {out_dir.resolve()}")
    print(f" - metadata.jsonl")
    print(f" - metadata.csv")
    print(f" - summary.json")
    print(f" - report.md")
    print(f" - failed_files.txt")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
