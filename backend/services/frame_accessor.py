import io
import os
import re
import subprocess
from typing import Dict, List, Optional, Tuple
from io import BytesIO
from PIL import Image
from imageio_ffmpeg import get_ffmpeg_exe


class FFmpegAccessor:
    """
    Random-access video frame extractor using the bundled ffmpeg binary from imageio_ffmpeg.
    - No system-level ffmpeg/ffprobe required.
    - Supports robust fallbacks for raw bitstreams (h264/hevc) with assumed fps when needed.
    """

    KNOWN_RAW_FORMATS = [
        ("h264", 25),
        ("hevc", 25),
        ("mpegts", 25),
        ("matroska", 25),
        ("mov", 25),
        ("avi", 25),
    ]

    def __init__(self):
        self.ffmpeg_path = get_ffmpeg_exe()

    def _run(self, args: List[str], binary_stdout: bool = False, timeout_sec: Optional[int] = None) -> Tuple[int, bytes | str, str]:
        """
        Run ffmpeg with either text stdout (default) or binary stdout (for image2pipe).
        Returns (code, stdout, stderr_text). When binary_stdout=True, stdout is bytes.
        """
        if binary_stdout:
            try:
                cp = subprocess.run(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,
                    timeout=timeout_sec,
                )
                # stderr is bytes; decode for logs
                stderr_text = cp.stderr.decode("utf-8", "ignore") if cp.stderr else ""
                return cp.returncode, cp.stdout or b"", stderr_text
            except subprocess.TimeoutExpired:
                return -9, b"", "timeout"
        else:
            try:
                cp = subprocess.run(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=timeout_sec,
                )
                return cp.returncode, cp.stdout or "", cp.stderr or ""
            except subprocess.TimeoutExpired:
                return -9, "", "timeout"

    def probe_time_base_and_fps(
        self,
        video_path: str,
        forced_format: Optional[str] = None,
        forced_fps: Optional[int] = None,
    ) -> Tuple[Optional[int], Optional[int], Optional[float]]:
        """
        Parse stream time base (as num/den) and fps from ffmpeg stderr (no ffprobe).
        Returns (tb_num, tb_den, fps).
        """
        args = [
            self.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "debug",  # verbose to reveal tbn and time_base
        ]
        if forced_format:
            args += ["-f", forced_format, "-r", str(forced_fps or 25)]
            # robust decode flags
            if forced_format in ("h264", "hevc", "mpegts"):
                args += [
                    "-probesize", "50M",
                    "-analyzeduration", "100M",
                    "-fflags", "+genpts",
                    "-err_detect", "ignore_err",
                ]
        args += [
            "-i",
            video_path,
            "-map",
            "0:v:0",
            "-f",
            "null",
            "-",
        ]
        code, _out, err = self._run(args)

        # time_base pattern (debug log lines often contain "time_base: 1/90000")
        tb_num, tb_den = None, None
        m_tb = re.search(r"time_base:\s*(\d+)\s*/\s*(\d+)", err)
        if m_tb:
            tb_num = int(m_tb.group(1))
            tb_den = int(m_tb.group(2))

        # Fallback: parse "tbr", "tbn" hint line like "30 tbr, 90k tbn"
        # fps pattern e.g. "fps, 29.97 tbr" or "30 fps"
        fps = None
        m_fps = re.search(r"(\d+(?:\.\d+)?)\s*fps", err)
        if m_fps:
            try:
                fps = float(m_fps.group(1))
            except Exception:
                fps = None

        # tbn (time base denominator) may appear like "90k tbn" or "90000 tbn"
        if tb_num is None or tb_den is None:
            m_tbn = re.search(r"(\d+)(k)?\s*tbn", err)
            if m_tbn:
                den = int(m_tbn.group(1))
                if m_tbn.group(2) == "k":
                    den *= 1000
                tb_num, tb_den = 1, den

        return tb_num, tb_den, fps

    def robust_probe_time_base_and_fps(self, video_path: str) -> Tuple[int, int, float]:
        tb_num, tb_den, fps = self.probe_time_base_and_fps(video_path)
        if tb_num and tb_den and fps:
            return tb_num, tb_den, fps

        # Retry with forced formats (raw bitstreams)
        for fmt, assumed_fps in self.KNOWN_RAW_FORMATS:
            tb_n, tb_d, f = self.probe_time_base_and_fps(video_path, forced_format=fmt, forced_fps=assumed_fps)
            if tb_n and tb_d:
                return tb_n, tb_d, f or float(assumed_fps)

        # Final fallback
        return 1, 1000, fps or 25.0

    def extract_frame_bytes_by_sec(
        self,
        video_path: str,
        t_sec: float,
        forced_format: Optional[str] = None,
        forced_fps: Optional[int] = None,
        quality: int = 85,
    ) -> bytes:
        """
        Accurate single-frame extraction using -ss seek, returning JPEG bytes.
        """
        args = [
            self.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
        ]
        if forced_format:
            args += ["-f", forced_format, "-r", str(forced_fps or 25)]
        args += [
            "-ss",
            f"{t_sec:.6f}",
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-q:v",
            str(max(2, min(31, int(31 - (quality / 3))))),  # map 1..95 -> ~2..31
            "-probesize", "50M",
            "-analyzeduration", "100M",
            "-fflags", "+genpts",
            "-err_detect", "ignore_err",
            "-f",
            "image2pipe",
            "pipe:1",
        ]
        code, out, err = self._run(args, binary_stdout=True, timeout_sec=10)
        if code == 0 and out:
            return out  # bytes
        # Try robust fallbacks for raw formats
        for fmt, fps in self.KNOWN_RAW_FORMATS:
            args2 = [
                self.ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-f",
                fmt,
                "-r",
                str(fps),
                "-ss",
                f"{t_sec:.6f}",
                "-i",
                video_path,
                "-probesize", "50M",
                "-analyzeduration", "100M",
                "-fflags", "+genpts",
                "-err_detect", "ignore_err",
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-f",
                "image2pipe",
                "pipe:1",
            ]
            # insert AUD for raw bitstreams to improve parsing
            if fmt == "h264":
                args2 = args2[:args2.index("-frames:v")] + ["-bsf:v", "h264_metadata=aud=insert"] + args2[args2.index("-frames:v"):]
            elif fmt == "hevc":
                args2 = args2[:args2.index("-frames:v")] + ["-bsf:v", "hevc_metadata=aud=insert"] + args2[args2.index("-frames:v"):]
            code2, out2, err2 = self._run(args2, binary_stdout=True, timeout_sec=12)
            if code2 == 0 and out2:
                return out2  # bytes
        raise RuntimeError(f"ffmpeg single-frame extraction failed: {err.strip() or 'timeout'}")

    # ----------------------------
    # H.264 parameter set helpers
    # ----------------------------
    @staticmethod
    def _iter_annexb_nals(byts: bytes):
        i = 0
        n = len(byts)
        start_codes = [b"\x00\x00\x01", b"\x00\x00\x00\x01"]
        while i < n:
            # find next start code
            sc_pos = -1
            sc_len = 0
            for sc in start_codes:
                p = byts.find(sc, i)
                if p != -1 and (sc_pos == -1 or p < sc_pos):
                    sc_pos = p
                    sc_len = len(sc)
            if sc_pos == -1:
                break
            # find following start code to delimit nal
            j = sc_pos + sc_len
            next_pos = -1
            next_len = 0
            for sc in start_codes:
                p2 = byts.find(sc, j)
                if p2 != -1 and (next_pos == -1 or p2 < next_pos):
                    next_pos = p2
                    next_len = len(sc)
            if next_pos == -1:
                nal = byts[j:]
                i = n
            else:
                nal = byts[j:next_pos]
                i = next_pos
            yield nal

    def extract_h264_paramsets_from_video(self, sample_path: str) -> Tuple[Optional[bytes], Optional[bytes]]:
        """
        Use ffmpeg to convert to Annex B and parse SPS/PPS.
        Returns (sps_bytes, pps_bytes) without start codes.
        """
        args = [
            self.ffmpeg_path,
            "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", sample_path,
            "-c:v", "copy",
            "-bsf:v", "h264_mp4toannexb",
            "-f", "h264",
            "pipe:1",
        ]
        code, out, err = self._run(args, binary_stdout=True, timeout_sec=8)
        if code != 0 or not out:
            # try short decode to Annex B by re-encoding small segment if copy+bsf failed
            args2 = [
                self.ffmpeg_path,
                "-hide_banner", "-loglevel", "error", "-nostdin",
                "-ss", "0",
                "-t", "0.2",
                "-i", sample_path,
                "-c:v", "copy",
                "-bsf:v", "h264_mp4toannexb",
                "-f", "h264",
                "pipe:1",
            ]
            code2, out2, err2 = self._run(args2, binary_stdout=True, timeout_sec=8)
            if code2 != 0 or not out2:
                return None, None
            out = out2
        sps = None
        pps = None
        for nal in self._iter_annexb_nals(out):
            if not nal:
                continue
            nal_type = nal[0] & 0x1F
            if nal_type == 7 and sps is None:
                sps = nal
            elif nal_type == 8 and pps is None:
                pps = nal
            if sps is not None and pps is not None:
                break
        return sps, pps

    def extract_frame_bytes_by_sec_with_seed(
        self,
        broken_video_path: str,
        t_sec: float,
        seed_video_path: str,
        assumed_fps: int = 25,
        quality: int = 85,
    ) -> bytes:
        """
        Try to repair a raw H.264 chunk lacking SPS/PPS by prepending parameter sets
        extracted from a seed video (same camera/profile).
        Note: uses pipe input so -ss is after input (decodes from start).
        """
        sps, pps = self.extract_h264_paramsets_from_video(seed_video_path)
        if not sps or not pps:
            raise RuntimeError("failed to extract SPS/PPS from seed video")
        try:
            with open(broken_video_path, "rb") as rf:
                broken = rf.read()
        except Exception as e:
            raise RuntimeError(f"failed to read broken video: {e}")
        start_code = b"\x00\x00\x00\x01"
        stream = start_code + sps + start_code + pps + broken

        args = [
            self.ffmpeg_path,
            "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "h264",
            "-r", str(assumed_fps),
            "-i", "pipe:0",
            "-probesize", "50M",
            "-analyzeduration", "100M",
            "-fflags", "+genpts",
            "-err_detect", "ignore_err",
            "-ss", f"{t_sec:.6f}",
            "-frames:v", "1",
            "-q:v", str(max(2, min(31, int(31 - (quality / 3))))),
            "-f", "image2pipe",
            "pipe:1",
        ]
        code, out, err = self._run(args, binary_stdout=True)
        if code == 0 and out:
            return out
        raise RuntimeError(f"seed-repair extraction failed: {err.strip()}")

    def extract_frames_to_dir_with_pts(
        self,
        video_path: str,
        out_dir: str,
        sample_interval: int = 1,
        forced_format: Optional[str] = None,
        forced_fps: Optional[int] = None,
        quality: int = 2,
    ) -> int:
        """
        Extract frames to out_dir using -frame_pts 1 so filenames encode PTS: frame_<PTS>.jpg
        Returns number of frames extracted.
        """
        os.makedirs(out_dir, exist_ok=True)
        output_pattern = os.path.join(out_dir, "frame_%d.jpg")

        vf = None
        if sample_interval and sample_interval > 1:
            vf = f"select='not(mod(n\\,{sample_interval}))',setpts=N/FRAME_RATE/TB"

        args = [
            self.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
        ]
        if forced_format:
            args += ["-f", forced_format, "-r", str(forced_fps or 25)]
        args += [
            "-i",
            video_path,
            "-vsync",
            "vfr",
            "-frame_pts",
            "1",
            "-probesize", "50M",
            "-analyzeduration", "100M",
            "-fflags", "+genpts",
            "-err_detect", "ignore_err",
        ]
        if vf:
            args += ["-vf", vf]
        args += ["-q:v", str(quality), "-start_number", "0", output_pattern]

        code, _out, err = self._run(args)
        if code != 0:
            # Raw format fallbacks
            for fmt, fps in self.KNOWN_RAW_FORMATS:
                args2 = [
                    self.ffmpeg_path,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-f",
                    fmt,
                    "-r",
                    str(fps),
                    "-i",
                    video_path,
                    "-vsync",
                    "vfr",
                    "-frame_pts",
                    "1",
                    "-probesize", "50M",
                    "-analyzeduration", "100M",
                    "-fflags", "+genpts",
                    "-err_detect", "ignore_err",
                ]
                if vf:
                    args2 += ["-vf", vf]
                # insert AUD where helpful
                if fmt == "h264":
                    args2 += ["-bsf:v", "h264_metadata=aud=insert"]
                elif fmt == "hevc":
                    args2 += ["-bsf:v", "hevc_metadata=aud=insert"]
                args2 += ["-q:v", "2", "-start_number", "0", output_pattern]
                code2, _out2, err2 = self._run(args2)
                if code2 == 0:
                    break
            else:
                raise RuntimeError(f"ffmpeg extract failed: {err.strip()}")

        # Count files
        files = [f for f in os.listdir(out_dir) if f.startswith("frame_") and f.endswith(".jpg")]
        return len(files)

    @staticmethod
    def parse_pts_from_filename(filename: str) -> Optional[int]:
        """
        Given 'frame_<number>.jpg', return <number> as int (PTS).
        """
        m = re.match(r"frame_(\d+)\.jpg$", filename)
        if not m:
            return None
        try:
            return int(m.group(1))
        except Exception:
            return None


