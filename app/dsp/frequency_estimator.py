import numpy as np
from scipy import signal

class FrequencyEstimator:
    """Stage 3: Carrier Frequency & Bandwidth Estimation
    Calculates coarse/fine carrier frequency, Carrier Frequency Offset (CFO),
    99% Occupied Bandwidth (OBW), -3dB Bandwidth, and Symbol/Baud Rate.
    """

    @staticmethod
    def estimate(iq: np.ndarray, fs: float, center_freq: float = 0.0) -> dict:
        """Extracts precise carrier frequency, bandwidth, CFO, and symbol parameters."""
        n = min(len(iq), 32768)
        s = iq[:n]
        is_real = np.max(np.abs(np.imag(iq))) < 1e-5

        # 1. Welch PSD for Bandwidth Integration
        if is_real:
            f, pxx = signal.welch(np.real(s), fs=fs, nperseg=min(len(s), 2048), return_onesided=True)
        else:
            f, pxx = signal.welch(s, fs=fs, nperseg=min(len(s), 2048), return_onesided=False)
            f = np.fft.fftshift(f)
            pxx = np.fft.fftshift(pxx)

        # 2. Coarse Carrier Frequency (Peak of PSD)
        peak_idx = np.argmax(pxx)
        f_coarse = f[peak_idx]

        # Fine Carrier Tuning via Parabolic/Quadratic Interpolation
        if 0 < peak_idx < len(pxx) - 1:
            alpha = 10 * np.log10(max(pxx[peak_idx - 1], 1e-12))
            beta = 10 * np.log10(max(pxx[peak_idx], 1e-12))
            gamma = 10 * np.log10(max(pxx[peak_idx + 1], 1e-12))
            delta = 0.5 * (alpha - gamma) / (alpha - 2 * beta + gamma + 1e-12)
            df = f[1] - f[0]
            f_fine = f_coarse + delta * df
        else:
            f_fine = f_coarse

        # 3. 99% Occupied Bandwidth (OBW)
        total_pwr = np.sum(pxx)
        cum_pwr = np.cumsum(pxx) / (total_pwr + 1e-12)
        idx_low = np.where(cum_pwr >= 0.005)[0][0]
        idx_high = np.where(cum_pwr <= 0.995)[0][-1]
        obw_99_hz = float(abs(f[idx_high] - f[idx_low]))

        # -3dB Bandwidth
        peak_pwr = pxx[peak_idx]
        half_pwr = peak_pwr * 0.5
        above_half = np.where(pxx >= half_pwr)[0]
        bw_3db_hz = float(abs(f[above_half[-1]] - f[above_half[0]])) if len(above_half) > 1 else obw_99_hz * 0.5

        # 4. Carrier Frequency Offset (CFO) via 4th-power non-linearity for PSK/QAM
        s_4th = s**4
        fft_4th = np.fft.fftshift(np.fft.fft(s_4th))
        freqs_4th = np.fft.fftshift(np.fft.fftfreq(len(s_4th), 1.0/fs))
        cfo_hz = float(freqs_4th[np.argmax(np.abs(fft_4th))] / 4.0)

        # 5. Symbol Rate / Baud Estimation via Nonlinear Filter & Delay
        diff_sig = np.abs(np.diff(s))**2
        if len(diff_sig) > 0:
            f_sym, pxx_sym = signal.welch(diff_sig - np.mean(diff_sig), fs=fs, nperseg=min(len(diff_sig), 4096), return_onesided=True)
            # Find peak in positive frequency range excluding DC
            valid_mask = f_sym > (0.01 * fs)
            if np.any(valid_mask):
                f_sym_sub = f_sym[valid_mask]
                pxx_sym_sub = pxx_sym[valid_mask]
                est_symbol_rate = float(f_sym_sub[np.argmax(pxx_sym_sub)])
            else:
                est_symbol_rate = obw_99_hz * 0.5
        else:
            est_symbol_rate = obw_99_hz * 0.5

        sps = float(np.clip(fs / max(est_symbol_rate, 1e-3), 2.0, 64.0))

        return {
            'carrier_freq_hz': float(center_freq + f_fine),
            'carrier_offset_hz': float(f_fine),
            'cfo_residual_hz': cfo_hz,
            'occupied_bandwidth_99_hz': obw_99_hz,
            'bandwidth_3db_hz': bw_3db_hz,
            'symbol_rate_baud': est_symbol_rate,
            'samples_per_symbol': sps
        }
