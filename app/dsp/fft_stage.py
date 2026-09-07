import numpy as np
from scipy import signal

class FFTAnalyzer:
    """Stage 2: Fast Fourier Transform (FFT) Analysis
    Computes discrete FFT magnitude/phase spectra, peak bins,
    Welch Power Spectral Density (PSD), and 2D Time-Frequency Spectrogram.
    """

    @staticmethod
    def process_fft(iq: np.ndarray, sample_rate: float, n_fft: int = 4096) -> dict:
        """Executes discrete Fast Fourier Transform and spectral feature analysis."""
        n = min(len(iq), n_fft)
        data = iq[:n]
        is_real = np.max(np.abs(np.imag(iq))) < 1e-5

        # 1. Windowed FFT
        window = signal.windows.blackmanharris(n)
        fft_raw = np.fft.fft(data * window)
        
        if is_real:
            freqs = np.fft.rfftfreq(n, d=1.0/sample_rate)
            mag = np.abs(fft_raw[:len(freqs)])
            mag_db = 20.0 * np.log10(np.maximum(mag / (n / 2), 1e-12))
        else:
            freqs = np.fft.fftshift(np.fft.fftfreq(n, d=1.0/sample_rate))
            mag = np.fft.fftshift(np.abs(fft_raw))
            mag_db = 20.0 * np.log10(np.maximum(mag / n, 1e-12))

        # 2. Peak Detection in FFT spectrum
        peak_idx = int(np.argmax(mag_db))
        peak_freq = float(freqs[peak_idx])
        peak_power_db = float(mag_db[peak_idx])

        # 3. Spectral Flatness (Wiener entropy)
        geom_mean = np.exp(np.mean(np.log(np.maximum(mag, 1e-12))))
        arith_mean = np.mean(mag) + 1e-12
        spectral_flatness = float(geom_mean / arith_mean)

        # 4. Welch PSD (computed for persistent display)
        n_seg = min(len(iq), 2048)
        if is_real:
            f_welch, pxx = signal.welch(np.real(iq), fs=sample_rate, nperseg=n_seg, return_onesided=True, scaling='density')
            pxx_db = 10.0 * np.log10(np.maximum(pxx, 1e-12))
            psd_data = {'freqs': f_welch.tolist(), 'psd_db': pxx_db.tolist(), 'is_onesided': True}
        else:
            f_welch, pxx = signal.welch(iq, fs=sample_rate, nperseg=n_seg, return_onesided=False, scaling='density')
            f_welch_sh = np.fft.fftshift(f_welch)
            pxx_sh = np.fft.fftshift(pxx)
            pxx_db = 10.0 * np.log10(np.maximum(pxx_sh, 1e-12))
            psd_data = {'freqs': f_welch_sh.tolist(), 'psd_db': pxx_db.tolist(), 'is_onesided': False}

        # 5. STFT 2D Spectrogram
        if sample_rate <= 48000:
            stft_seg = min(len(iq), 512)
        else:
            stft_seg = min(len(iq), 1024)
        stft_ovr = int(stft_seg * 0.75)

        if is_real:
            f_spec, t_spec, sxx = signal.spectrogram(np.real(iq), fs=sample_rate, nperseg=stft_seg, noverlap=stft_ovr, return_onesided=True, mode='magnitude')
            sxx_db = 20.0 * np.log10(np.maximum(sxx, 1e-6))
            if sample_rate <= 48000 and f_spec[-1] > 4000:
                mask = f_spec <= min(sample_rate / 2, 4500)
                f_spec = f_spec[mask]
                sxx_db = sxx_db[mask, :]
        else:
            f_spec, t_spec, sxx = signal.spectrogram(iq, fs=sample_rate, nperseg=stft_seg, noverlap=stft_ovr, return_onesided=False, mode='magnitude')
            f_spec = np.fft.fftshift(f_spec)
            sxx_sh = np.fft.fftshift(sxx, axes=0)
            sxx_db = 20.0 * np.log10(np.maximum(sxx_sh, 1e-6))

        if len(t_spec) > 400:
            step = int(np.ceil(len(t_spec) / 400))
            t_spec = t_spec[::step]
            sxx_db = sxx_db[:, ::step]

        vmin = float(np.percentile(sxx_db, 30))
        vmax = float(np.percentile(sxx_db, 99.8))

        spec_data = {
            'time_bins': t_spec.tolist(),
            'freq_bins': f_spec.tolist(),
            'spectrogram_db': sxx_db.tolist(),
            'vmin': vmin,
            'vmax': vmax,
            'is_real': is_real,
            'total_duration_sec': round(float(t_spec[-1]) if len(t_spec) > 0 else 0.0, 2)
        }

        return {
            'fft_points': n,
            'peak_frequency_hz': peak_freq,
            'peak_power_db': peak_power_db,
            'spectral_flatness': spectral_flatness,
            'dynamic_range_db': float(peak_power_db - np.min(mag_db)),
            'psd': psd_data,
            'spectrogram': spec_data
        }
