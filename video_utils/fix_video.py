import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass
import json

# 需要下
#   1、下载好的Bento4（直接解压即可）
#   2、在系统安装ffmpeg（包含ffprobe）

@dataclass
class ProbeResult:
    path: str
    ok: bool
    used_input_format: Optional[str]
    ffprobe_stdout: Optional[str]
    ffprobe_stderr: Optional[str]
    data: Optional[Dict[str, Any]]
    error_message: Optional[str]

def which_or_die(exe: str) -> str:
    p = shutil.which(exe)
    if not p:
        raise SystemExit(f"[FATAL] '{exe}' not found in PATH. Please install FFmpeg (ffprobe).")
    return p

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

FFPROBE_RETRY_INPUT_FORMATS = [
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


def probe_with_retries(path: Path,
                       deep: bool,
                       timeout_s: int,
                       probesize: Optional[int],
                       analyzeduration: Optional[int],
                       enable_forced_formats: bool) -> ProbeResult:
    r0 = run_ffprobe(path, deep, timeout_s, probesize, analyzeduration, input_format=None)
    if r0.ok:
        return r0
    if not enable_forced_formats:
        return r0

    hint_text = " ".join(filter(None, [r0.ffprobe_stderr, r0.ffprobe_stdout, r0.error_message]))
    if not any(h.lower() in hint_text.lower() for h in KNOWN_BAD_HINTS):
        return r0

    for fmt in FFPROBE_RETRY_INPUT_FORMATS:
        r = run_ffprobe(path, deep, timeout_s, probesize, analyzeduration, input_format=fmt)
        if r.ok:
            return r
    return r0


def is_video_ok(path: Path, timeout_s: int = 30) -> bool:
    pr = run_ffprobe(path, deep=False, timeout_s=timeout_s,
                     probesize=None, analyzeduration=None, input_format=None)
    if not pr.ok or not pr.data:
        return False
    streams = pr.data.get("streams") or []
    return any(s.get("codec_type") == "video" for s in streams)


def repair_video_if_needed(video_path: Path,
                           tool_path: Path,
                           temp_path: Optional[Path] = None,
                           timeout_s: int = 60,
                           probesize: Optional[int] = None,
                           analyzeduration: Optional[int] = None) -> bool:
    """
    如果 ffprobe 需要强制输入格式（used_input_format 非空），则用 mp4mux 修复。
    成功返回 True，失败返回 False。
    """
    pr = probe_with_retries(
        video_path,
        deep=False,
        timeout_s=timeout_s,
        probesize=probesize,
        analyzeduration=analyzeduration,
        enable_forced_formats=True,
    )
    print(f"Probe result before repair: ok={pr.ok}, used_input_format={pr.used_input_format}")

    if pr.used_input_format is None:
        return False

    tool_path = tool_path.resolve()
    if temp_path is None:
        temp_path = Path(str(video_path) + "_tmpforfix")
    temp_path = temp_path.resolve()

    cmd = [
        str(tool_path / "mp4mux"),
        "--track", f"mp4:{video_path}#track=video",
        str(temp_path),
    ]

    cp = subprocess.run(
        cmd,
        cwd=str(tool_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    if cp.returncode != 0:
        raise RuntimeError(f"mp4mux failed: {cp.stderr.strip()}")
        return False

    if not is_video_ok(temp_path, timeout_s=timeout_s):
        return False

    shutil.copy2(temp_path, video_path)
    # 删除临时文件
    temp_path.unlink(missing_ok=True)
    return True


if __name__ == "__main__":
    import sys
    video_file = Path(sys.argv[1])
    # result = run_ffprobe(video_file, deep=True, timeout_s=30,
    #                      probesize=5000000, analyzeduration=10000000)
    # print(result)
    is_ok = is_video_ok(video_file, timeout_s=30)
    print(f"Video OK: {is_ok}")

    # 修复
    if is_ok:
        print("Video is already OK, no repair needed.")
        sys.exit(0)
    repair_video_if_needed(
        video_path=video_file,
        tool_path=Path("/data/chenjuntao/OtherProj/dataManage/Auxiliary/Bento4-SDK-1-6-0-641.x86_64-unknown-linux/bin"),
        temp_path=None,
        timeout_s=60,
        probesize=5000000,
        analyzeduration=10000000,
    )

    is_ok = is_video_ok(video_file, timeout_s=30)
    print(f"Video OK: {is_ok}")

