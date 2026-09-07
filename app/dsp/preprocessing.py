import numpy as np
from scipy import signal

class SignalPreprocessor:
    """Provides DC removal, Gram-Schmidt I/Q balance, RMS normalization, PSD, and M2M4 SNR estimation."""

    @staticmethod
    def clean_and_normalize(iq: np.ndarray) -> tuple[np.ndarray, dict]:
        # 1. DC Offset Removal
        i_raw = np.real(iq)
        q_raw = np.imag(iq)
        dc_i = float(np.mean(i_raw))
        dc_q = float(np.mean(q_raw))
        i_clean = i_raw - dc_i
        q_clean = q_raw - dc_q
        
        # 2. Gram-Schmidt I/Q Balance Correction
        sigma_i = float(np.std(i_clean)) + 1e-12
        i_norm = i_clean / sigma_i
        rho = float(np.mean(i_norm * q_clean))
        q_orth = (q_clean - i_norm * rho) / (np.sqrt(max(1.0 - rho**2, 1e-6)) + 1e-12)
        
        # 3. RMS Power Normalization
        s_comp = (i_norm + 1j * q_orth).astype(np.complex64)
        rms = float(np.sqrt(np.mean(np.abs(s_comp)**2))) + 1e-12
        s_norm = (s_comp / rms).astype(np.complex64)
        
        # 4. Blind SNR Estimation via M2M4 Estimator
        m2 = float(np.mean(np.abs(s_norm)**2))
        m4 = float(np.mean(np.abs(s_norm)**4))
        
        discrim = max(0.0, 2.0 * (m2**2) - m4)
        s_est = np.sqrt(discrim)
        n_est = max(1e-6, m2 - s_est)
        snr_lin = s_est / n_est
        snr_db = float(10.0 * np.log10(max(snr_lin, 1e-4)))
        
        stats = {
            "dc_offset_i": dc_i,
            "dc_offset_q": dc_q,
            "iq_phase_imbalance_rad": float(np.arcsin(np.clip(rho, -1.0, 1.0))),
            "rms_level": rms,
            "snr_m2m4_db": snr_db
        }
        return s_norm, stats

    @staticmethod
    def compute_psd(iq: np.ndarray, sample_rate: float, nperseg: int = 2048) -> dict:
        """Calculates Welch's Power Spectral Density for real or complex IQ signals."""
        is_real = np.max(np.abs(np.imag(iq))) < 1e-5
        
        n_seg = min(len(iq), nperseg)
        if is_real:
            f, pxx = signal.welch(np.real(iq), fs=sample_rate, nperseg=n_seg, return_onesided=True, scaling='density')
            pxx_db = 10.0 * np.log10(np.maximum(pxx, 1e-12))
            return {
                "freqs": f.tolist(),
                "psd_db": pxx_db.tolist(),
                "is_onesided": True
            }
        else:
            f, pxx = signal.welch(iq, fs=sample_rate, nperseg=n_seg, return_onesided=False, scaling='density')
            f_shifted = np.fft.fftshift(f)
            pxx_shifted = np.fft.fftshift(pxx)
            pxx_db = 10.0 * np.log10(np.maximum(pxx_shifted, 1e-12))
            return {
                "freqs": f_shifted.tolist(),
                "psd_db": pxx_db.tolist(),
                "is_onesided": False
            }

    @staticmethod
    def compute_spectrogram(iq: np.ndarray, sample_rate: float, nperseg: int = 512, noverlap: int = 384) -> dict:
        """Calculates high-resolution STFT 2D Spectrogram across the entire signal capture."""
        is_real = np.max(np.abs(np.imag(iq))) < 1e-5
        
        # Adaptive segment sizing based on sample rate
        if sample_rate <= 48000:
            n_seg = min(len(iq), 512)
            n_ovr = int(n_seg * 0.75)
        else:
            n_seg = min(len(iq), 1024)
            n_ovr = int(n_seg * 0.75)

        if is_real:
            # High-resolution one-sided spectrogram for audio / demodulated captures
            sig_data = np.real(iq)
            f, t, sxx = signal.spectrogram(sig_data, fs=sample_rate, nperseg=n_seg, noverlap=n_ovr, return_onesided=True, mode='magnitude')
            sxx_db = 20.0 * np.log10(np.maximum(sxx, 1e-6))
            
            # Focus on active audio band (e.g. up to 4000 Hz or full fs/2)
            if sample_rate <= 48000 and f[-1] > 4000:
                f_mask = f <= min(sample_rate / 2, 4500)
                f = f[f_mask]
                sxx_db = sxx_db[f_mask, :]
        else:
            # Centered two-sided spectrogram for raw complex I/Q captures
            f, t, sxx = signal.spectrogram(iq, fs=sample_rate, nperseg=n_seg, noverlap=n_ovr, return_onesided=False, mode='magnitude')
            f = np.fft.fftshift(f)
            sxx_shifted = np.fft.fftshift(sxx, axes=0)
            sxx_db = 20.0 * np.log10(np.maximum(sxx_shifted, 1e-6))

        # Dynamic time-bin subsampling for responsive transport (cap at 400 time columns)
        if len(t) > 400:
            step = int(np.ceil(len(t) / 400))
            t = t[::step]
            sxx_db = sxx_db[:, ::step]

        # Dynamic range contrast stretching for vibrant waterfall colors
        vmin = float(np.percentile(sxx_db, 30))
        vmax = float(np.percentile(sxx_db, 99.8))

        return {
            "time_bins": t.tolist(),
            "freq_bins": f.tolist(),
            "spectrogram_db": sxx_db.tolist(),
            "vmin": vmin,
            "vmax": vmax,
            "is_real": is_real,
            "total_duration_sec": round(float(t[-1]) if len(t) > 0 else 0.0, 2)
        }
