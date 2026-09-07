import numpy as np

class SignalParameterExtractor:
    """Extracts Center Frequency (fc), 99% OBW, 3dB Bandwidth, Baud Rate (Rs), and Carrier Offset."""

    @staticmethod
    def extract_all(iq: np.ndarray, sample_rate: float, center_freq_nominal: float = 434.5e6) -> dict:
        N = min(len(iq), 65536)
        x = iq[:N]
        
        # 1. FFT Magnitude
        fft_vals = np.abs(np.fft.fftshift(np.fft.fft(x)))**2
        freqs = np.fft.fftshift(np.fft.fftfreq(N, 1.0 / sample_rate))
        
        # 2. Center Frequency Offset & Centroid
        p_total = np.sum(fft_vals) + 1e-12
        freq_centroid = float(np.sum(freqs * fft_vals) / p_total)
        
        # 3. 99% Occupied Bandwidth (OBW)
        cum_p = np.cumsum(fft_vals) / p_total
        idx_low = np.searchsorted(cum_p, 0.005)
        idx_high = np.searchsorted(cum_p, 0.995)
        bw_99 = float(freqs[min(idx_high, len(freqs)-1)] - freqs[max(0, idx_low)])
        
        # 4. 3-dB Bandwidth
        max_p = np.max(fft_vals)
        above_3db = np.where(fft_vals >= max_p * 0.5)[0]
        if len(above_3db) > 1:
            bw_3db = float(freqs[above_3db[-1]] - freqs[above_3db[0]])
        else:
            bw_3db = bw_99 * 0.8
            
        # 5. Baud Rate Estimation via Non-Linear Squaring & Cyclic Line
        # |x[n]|^2 FFT peak detection
        env_sq = np.abs(x)**2
        env_sq -= np.mean(env_sq)
        env_fft = np.abs(np.fft.fft(env_sq))
        env_freqs = np.fft.fftfreq(N, 1.0 / sample_rate)
        
        # Search in positive frequencies (ignore near DC)
        valid_mask = (env_freqs > sample_rate * 0.01) & (env_freqs < sample_rate * 0.45)
        if np.any(valid_mask):
            peak_idx = np.argmax(env_fft[valid_mask])
            est_baud = float(env_freqs[valid_mask][peak_idx])
        else:
            est_baud = bw_99 / 1.35
            
        # Refine baud rate sanity
        if est_baud < 1000 or est_baud > sample_rate * 0.5:
            est_baud = bw_99 / 1.35

        # 6. Non-Linear Carrier Frequency Offset (CFO)
        # 4th power loop for QPSK, 2nd power for BPSK
        x_sq4 = x**4
        fft_sq4 = np.abs(np.fft.fft(x_sq4))
        f_sq4 = np.fft.fftfreq(N, 1.0 / sample_rate)
        cfo_est = float(f_sq4[np.argmax(fft_sq4)] / 4.0)

        return {
            "center_freq_hz": float(center_freq_nominal + freq_centroid),
            "freq_offset_hz": float(freq_centroid),
            "cfo_estimated_hz": float(cfo_est),
            "occupied_bw_99_hz": abs(bw_99),
            "bandwidth_3db_hz": abs(bw_3db),
            "baud_rate_hz": abs(est_baud),
            "samples_per_symbol": float(sample_rate / max(abs(est_baud), 1e3)),
            "papr_db": float(10.0 * np.log10(np.max(np.abs(x)**2) / (np.mean(np.abs(x)**2) + 1e-12)))
        }
