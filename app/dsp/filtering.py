import numpy as np
from scipy import signal

class SignalFilter:
    """Stage 1: Signal Filtering
    Provides anti-aliasing / bandpass filtering, DC offset removal,
    Gram-Schmidt I/Q balance compensation, and RMS power normalization.
    """

    @staticmethod
    def apply_filter(raw_iq: np.ndarray, fs: float, cutoff_hz: float | None = None) -> tuple[np.ndarray, dict]:
        """Applies digital filtering and front-end conditioning on raw IQ samples."""
        # 1. DC Offset Removal
        i_raw = np.real(raw_iq).astype(np.float32)
        q_raw = np.imag(raw_iq).astype(np.float32)
        dc_i = float(np.mean(i_raw))
        dc_q = float(np.mean(q_raw))
        i_dc = i_raw - dc_i
        q_dc = q_raw - dc_q

        # 2. Digital Filtering (Butterworth Bandpass / Lowpass)
        nyq = 0.5 * fs
        if cutoff_hz is None or cutoff_hz >= nyq:
            cutoff_hz = 0.45 * fs

        is_real = np.max(np.abs(q_raw)) < 1e-5
        if is_real:
            norm_cutoff = min(0.95, max(0.01, cutoff_hz / nyq))
            b, a = signal.butter(4, norm_cutoff, btype='low', analog=False)
            i_filt = signal.filtfilt(b, a, i_dc)
            q_filt = np.zeros_like(i_filt)
            used_filter = f'4th-Order Butterworth Lowpass ({cutoff_hz/1e3:.1f} kHz)'
        else:
            norm_cutoff = min(0.95, max(0.01, cutoff_hz / nyq))
            b, a = signal.butter(4, norm_cutoff, btype='low', analog=False)
            i_filt = signal.filtfilt(b, a, i_dc)
            q_filt = signal.filtfilt(b, a, q_dc)
            used_filter = f'4th-Order Butterworth Bandpass ({cutoff_hz/1e3:.1f} kHz)'

        # 3. Gram-Schmidt I/Q Balance Correction
        sigma_i = float(np.std(i_filt)) + 1e-12
        i_norm = i_filt / sigma_i
        rho = float(np.mean(i_norm * q_filt))
        denom = np.sqrt(max(1.0 - rho**2, 1e-6)) + 1e-12
        q_orth = (q_filt - i_norm * rho) / denom

        # 4. RMS Power Normalization
        s_comp = (i_norm + 1j * q_orth).astype(np.complex64)
        rms = float(np.sqrt(np.mean(np.abs(s_comp)**2))) + 1e-12
        filtered_iq = (s_comp / rms).astype(np.complex64)

        stats = {
            'filter_type': used_filter,
            'cutoff_frequency_hz': cutoff_hz,
            'dc_offset_i': dc_i,
            'dc_offset_q': dc_q,
            'iq_phase_imbalance_rad': float(np.arcsin(np.clip(rho, -1.0, 1.0))),
            'rms_level': rms,
            'sample_count': len(filtered_iq)
        }
        return filtered_iq, stats
