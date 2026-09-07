import os
import io
import numpy as np
from scipy.io import wavfile

class SignalLoader:
    """High-performance streaming file loader for captured signal files (from disk or memory bytes)."""

    @staticmethod
    def load_from_bytes(file_bytes: bytes, filename: str = "signal.raw", default_fs: float = 2.0e6, max_samples: int = 2_000_000) -> tuple[np.ndarray, float, str]:
        ext = os.path.splitext(filename)[1].lower() if filename else ".raw"
        file_size = len(file_bytes)

        if ext == ".wav":
            bio = io.BytesIO(file_bytes)
            fs, data = wavfile.read(bio)
            if data.ndim == 2:
                # Check if stereo is I/Q or dual-mono audio
                i_raw = data[:, 0].astype(np.float32)
                q_raw = data[:, 1].astype(np.float32)
                diff = np.max(np.abs(i_raw - q_raw))
                if diff > 1e-4:
                    iq = i_raw + 1j * q_raw
                    fmt_desc = f"Stereo I/Q WAV ({fs/1e3:.1f} kHz, {data.dtype})"
                else:
                    iq = i_raw.astype(np.complex64)
                    fmt_desc = f"Dual-Mono Audio WAV ({fs/1e3:.1f} kHz, {data.dtype})"
            else:
                iq = data.astype(np.float32) + 0j
                fmt_desc = f"Mono Audio WAV ({fs/1e3:.1f} kHz, {data.dtype})"

            # Normalize integer formats to [-1.0, 1.0]
            if np.issubdtype(data.dtype, np.integer):
                max_val = float(np.iinfo(data.dtype).max)
                iq /= max_val

            return iq[:max_samples], float(fs), fmt_desc

        else:
            # Try parsing as Complex64 (Float32 I + Float32 Q)
            header_bytes = file_bytes[:min(file_size, max_samples * 8)]

            # Auto-detection heuristic between float32, int16, and uint8
            raw_f32 = np.frombuffer(header_bytes, dtype=np.float32)
            
            # Check if float32 values are reasonably bounded in magnitude
            is_valid_float = False
            if len(raw_f32) >= 2:
                magnitudes = np.abs(raw_f32[:min(len(raw_f32), 1000)])
                if not np.any(np.isnan(magnitudes)) and not np.any(np.isinf(magnitudes)):
                    mean_mag = np.mean(magnitudes)
                    if 1e-4 <= mean_mag <= 1e4:
                        is_valid_float = True

            if is_valid_float and len(raw_f32) % 2 == 0:
                iq = (raw_f32[0::2] + 1j * raw_f32[1::2]).astype(np.complex64)
                fmt_desc = "Complex Float32 (cf32) I/Q"
            else:
                # Fallback to Interleaved Int16 (ci16)
                raw_i16 = np.frombuffer(header_bytes, dtype=np.int16)
                if len(raw_i16) % 2 == 0 and len(raw_i16) > 0:
                    iq = (raw_i16[0::2] + 1j * raw_i16[1::2]).astype(np.complex64) / 32768.0
                    fmt_desc = "Signed Int16 (ci16) I/Q"
                else:
                    # Fallback to UInt8 RTL-SDR raw
                    raw_u8 = np.frombuffer(header_bytes, dtype=np.uint8)
                    i_u8 = (raw_u8[0::2].astype(np.float32) - 127.5) / 127.5
                    q_u8 = (raw_u8[1::2].astype(np.float32) - 127.5) / 127.5
                    iq = (i_u8 + 1j * q_u8).astype(np.complex64)
                    fmt_desc = "Unsigned Int8 (cu8) RTL-SDR"

            return iq[:max_samples], float(default_fs), fmt_desc

    @staticmethod
    def load_from_disk(file_path: str, default_fs: float = 2.0e6, max_samples: int = 2_000_000) -> tuple[np.ndarray, float, str]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Signal file not found: {file_path}")

        with open(file_path, "rb") as f:
            file_bytes = f.read()

        return SignalLoader.load_from_bytes(file_bytes, filename=file_path, default_fs=default_fs, max_samples=max_samples)
