import numpy as np

class NoiseEstimator:
    """Stage 6: Noise & SNR Estimation
    Computes blind Signal-to-Noise Ratio (SNR) via M2M4 and SSME estimators,
    spectral noise floor N0 (dBm/Hz), in-band noise variance, and noise margin.
    """

    @staticmethod
    def estimate_noise(iq: np.ndarray, fs: float, evm_db: float | None = None) -> dict:
        """Estimates noise floor, noise variance, and multi-metric blind SNR."""
        n = min(len(iq), 65536)
        s = iq[:n]

        # 1. Blind M2M4 Moment Estimator
        m2 = float(np.mean(np.abs(s)**2))
        m4 = float(np.mean(np.abs(s)**4))
        
        discrim = max(0.0, 2.0 * (m2**2) - m4)
        s_est = np.sqrt(discrim)
        n_est = max(1e-7, m2 - s_est)
        snr_lin_m2m4 = s_est / n_est
        snr_db_m2m4 = float(10.0 * np.log10(max(snr_lin_m2m4, 1e-4)))

        # 2. Split-Symbol Moments Estimator (SSME)
        half_len = len(s) // 2
        s1 = s[:half_len]
        s2 = s[half_len:2*half_len]
        cross_corr = float(np.abs(np.mean(s1 * np.conj(s2))))
        pwr_total = float(np.mean(np.abs(s)**2))
        noise_var_ssme = max(1e-7, pwr_total - cross_corr)
        snr_db_ssme = float(10.0 * np.log10(max(cross_corr / noise_var_ssme, 1e-4)))

        # 3. Spectral Noise Floor Density N0 (dBm/Hz, assuming 50 ohm impedance)
        noise_pwr_watts = n_est
        noise_density_w_per_hz = max(1e-20, noise_pwr_watts / fs)
        n0_dbm_hz = float(10.0 * np.log10(noise_density_w_per_hz * 1000.0))

        # 4. EVM-derived SNR benchmark (if EVM available)
        if evm_db is not None and not np.isnan(evm_db) and evm_db != 0:
            snr_evm = float(-evm_db)
        else:
            snr_evm = snr_db_m2m4

        # Composite Consensus SNR
        composite_snr_db = round(float(0.6 * snr_db_m2m4 + 0.4 * min(snr_db_ssme, 45.0)), 2)

        return {
            'snr_db': composite_snr_db,
            'snr_m2m4_db': round(snr_db_m2m4, 2),
            'snr_ssme_db': round(snr_db_ssme, 2),
            'snr_evm_db': round(snr_evm, 2),
            'noise_variance': float(n_est),
            'noise_floor_n0_dbm_hz': round(n0_dbm_hz, 1),
            'signal_power_watts': float(s_est),
            'noise_margin_db': round(max(0.0, composite_snr_db - 3.0), 2)
        }
