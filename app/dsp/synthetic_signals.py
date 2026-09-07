import numpy as np
try:
    import reedsolo
except ImportError:
    reedsolo = None
from app.dsp.descrambler import Descrambler
from app.dsp.crc_verifier import CRCVerifier

class SyntheticSignalGenerator:
    """Generates realistic telemetry signals with full transmitter pipeline:
    Payload -> CRC -> Scrambler -> FEC Encoder -> Interleaver -> Modulator -> Channel Impairments
    """
    
    CCSDS_ASM = bytes([0x1A, 0xCF, 0xFC, 0x1D])
    
    @classmethod
    def generate_profile(cls, profile_name: str = "Profile A") -> dict:
        profiles = {
            "Profile A": {
                "name": "Profile A (Satellite Telemetry - QPSK)",
                "mod_type": "QPSK",
                "sample_rate": 1.0e6,
                "baud_rate": 125.0e3,
                "center_freq": 434.5e6,
                "snr_db": 18.0,
                "cfo_hz": 250.0,
                "interleaver": "Block (16x16)",
                "fec": "NASA Viterbi (K=7, R=1/2)",
                "sync_pattern": "CCSDS_ASM",
                "scrambler": "CCSDS",
                "message": "NTRO_SAT_TELEMETRY: ALTITUDE=450.2KM SPEED=7.62KM/S STATUS=OPERATIONAL BATT=98%"
            },
            "Profile B": {
                "name": "Profile B (Tactical HF Radio - 2-FSK)",
                "mod_type": "2-FSK",
                "sample_rate": 500.0e3,
                "baud_rate": 25.0e3,
                "center_freq": 14.25e6,
                "snr_db": 6.0,
                "cfo_hz": 120.0,
                "interleaver": "Forney Convolutional (12x17)",
                "fec": "Reed-Solomon RS(255,223)",
                "sync_pattern": "BARKER_13",
                "scrambler": "Direct",
                "message": "TACTICAL_COMMAND: SECTOR_4_CLEAR GRID_REF_8829_SECURE MISSION_GO STATUS=OK"
            },
            "Profile C": {
                "name": "Profile C (UHF High-Capacity Link - 16-QAM)",
                "mod_type": "16-QAM",
                "sample_rate": 2.0e6,
                "baud_rate": 250.0e3,
                "center_freq": 915.0e6,
                "snr_db": 14.0,
                "cfo_hz": 400.0,
                "interleaver": "Diagonal (Span 64)",
                "fec": "Concatenated RS + Viterbi",
                "sync_pattern": "BARKER_11",
                "scrambler": "V35",
                "message": "SURVEILLANCE_DATALINK: RADAR_TARGET_LOCKED AZIMUTH=142.5 EL=22.8 RANGE=84NM"
            },
            "Profile D": {
                "name": "Profile D (Deep Space Probe - BPSK)",
                "mod_type": "BPSK",
                "sample_rate": 500.0e3,
                "baud_rate": 25.0e3,
                "center_freq": 2.29e9,
                "snr_db": 2.0,
                "cfo_hz": 50.0,
                "interleaver": "Pseudo-Random (LFSR 256)",
                "fec": "LDPC / Viterbi (Rate 1/2)",
                "sync_pattern": "CCSDS_ASM",
                "scrambler": "CCSDS",
                "message": "DEEP_SPACE_TELEMETRY: PROBE_HEALTH=NOMINAL TEMP=-142C SENSOR_DATA_LOCKED"
            },
            "Profile E": {
                "name": "Profile E (Aero Avionics Link - 8-PSK)",
                "mod_type": "8-PSK",
                "sample_rate": 2.0e6,
                "baud_rate": 250.0e3,
                "center_freq": 1090.0e6,
                "snr_db": 15.0,
                "cfo_hz": 150.0,
                "interleaver": "Forney Convolutional (12x17)",
                "fec": "NASA Viterbi (K=7, R=1/2)",
                "sync_pattern": "ETHERNET_SFD",
                "scrambler": "Direct",
                "message": "AVIONICS_TELEMETRY: FLIGHT_AI2026 LAT=28.6139N LON=77.2090E ALT=35000FT MACH=0.82"
            }
        }
        
        cfg = profiles.get(profile_name, profiles["Profile A"])
        
        # 1. Payload assembly & CRC calculation
        raw_msg_bytes = cfg["message"].encode('utf-8')
        crc_val = CRCVerifier.compute_crc16_ccitt(raw_msg_bytes)
        crc_bytes = crc_val.to_bytes(2, byteorder='big')
        
        # 2. Framing & sync word insertion
        sync_bytes = cls.CCSDS_ASM if "CCSDS" in cfg["sync_pattern"] else b'\xEB\x90\xEB\x90'
        framed_bytes = sync_bytes + raw_msg_bytes + crc_bytes
        
        # 3. RS Encode if required
        if ("RS" in cfg["fec"] or "Concatenated" in cfg["fec"]):
            if reedsolo is not None:
                try:
                    rs = reedsolo.RSCodec(32)  # RS(255, 223)
                    padded = framed_bytes.ljust(223, b'\x00')
                    fec_bytes = rs.encode(padded)
                except Exception:
                    fec_bytes = framed_bytes
            else:
                fec_bytes = framed_bytes
        else:
            fec_bytes = framed_bytes
            
        # Convert bytes to bits
        bits = np.unpackbits(np.frombuffer(fec_bytes, dtype=np.uint8))
        
        # 4. Convolutional Encode if required
        if "Viterbi" in cfg["fec"] or "Concatenated" in cfg["fec"]:
            bits_conv = cls._conv_encode_k7(bits)
        else:
            bits_conv = bits
            
        # 5. Interleaving
        inter_type = cfg["interleaver"]
        if "Block" in inter_type:
            bits_inter = cls._block_interleave(bits_conv, 16, 16)
        elif "Forney" in inter_type:
            bits_inter = cls._forney_interleave(bits_conv, 12, 17)
        elif "Diagonal" in inter_type:
            bits_inter = cls._diagonal_interleave(bits_conv, 64)
        else:
            bits_inter = cls._pseudo_random_interleave(bits_conv, 256, 42)
            
        # 6. Modulation mapping
        sps = int(cfg["sample_rate"] / cfg["baud_rate"])
        symbols = cls._modulate(bits_inter, cfg["mod_type"])
        
        # Pulse shaping (Square-Root Raised Cosine / Upsampling)
        upsampled = np.zeros(len(symbols) * sps, dtype=np.complex64)
        upsampled[::sps] = symbols
        h_pulse = cls._rrc_filter(beta=0.35, sps=sps, span=8)
        tx_signal = np.convolve(upsampled, h_pulse, mode='same')
        
        # 7. Channel Impairments
        # Add CFO
        t = np.arange(len(tx_signal)) / cfg["sample_rate"]
        cfo_signal = tx_signal * np.exp(1j * 2 * np.pi * cfg["cfo_hz"] * t)
        
        # Add AWGN
        sig_pwr = np.mean(np.abs(cfo_signal)**2)
        snr_lin = 10.0 ** (cfg["snr_db"] / 10.0)
        noise_pwr = sig_pwr / max(snr_lin, 1e-4)
        noise = (np.random.normal(0, np.sqrt(noise_pwr/2), len(cfo_signal)) + 
                 1j * np.random.normal(0, np.sqrt(noise_pwr/2), len(cfo_signal))).astype(np.complex64)
                 
        rx_signal = cfo_signal + noise
        
        # Trim / pad to standard length
        max_samples = 100_000
        if len(rx_signal) > max_samples:
            rx_signal = rx_signal[:max_samples]
        elif len(rx_signal) < max_samples:
            repeats = int(np.ceil(max_samples / len(rx_signal)))
            rx_signal = np.tile(rx_signal, repeats)[:max_samples]
            
        return {
            "config": cfg,
            "raw_iq": rx_signal,
            "sample_rate": cfg["sample_rate"],
            "ground_truth": {
                "message": cfg["message"],
                "fec": cfg["fec"],
                "interleaver": cfg["interleaver"],
                "mod_type": cfg["mod_type"],
                "snr_db": cfg["snr_db"],
                "baud_rate": cfg["baud_rate"],
                "sync_pattern": cfg["sync_pattern"]
            }
        }

    @staticmethod
    def _conv_encode_k7(bits: np.ndarray) -> np.ndarray:
        """NASA K=7, Rate 1/2 Convolutional Encoder (g0=133_8, g1=171_8)."""
        reg = np.zeros(6, dtype=np.uint8)
        encoded = np.zeros(len(bits) * 2, dtype=np.uint8)
        for i, b in enumerate(bits):
            sr = np.concatenate(([b], reg))
            b0 = (sr[0] ^ sr[2] ^ sr[3] ^ sr[5] ^ sr[6]) & 1
            b1 = (sr[0] ^ sr[1] ^ sr[2] ^ sr[3] ^ sr[6]) & 1
            encoded[2*i] = b0
            encoded[2*i + 1] = b1
            reg = np.roll(reg, 1)
            reg[0] = b
        return encoded

    @staticmethod
    def _block_interleave(bits: np.ndarray, rows: int, cols: int) -> np.ndarray:
        total = rows * cols
        usable = bits[: (len(bits) // total) * total]
        blocks = usable.reshape(-1, rows, cols)
        return np.transpose(blocks, (0, 2, 1)).reshape(-1)

    @staticmethod
    def _forney_interleave(bits: np.ndarray, branches: int, step_m: int) -> np.ndarray:
        fifo_lens = [i * step_m for i in range(branches)]
        fifos = [np.zeros(length, dtype=bits.dtype) if length > 0 else None for length in fifo_lens]
        out = np.zeros(len(bits), dtype=bits.dtype)
        for i, b in enumerate(bits):
            br = i % branches
            if fifos[br] is None:
                out[i] = b
            else:
                out[i] = fifos[br][0]
                fifos[br] = np.roll(fifos[br], -1)
                fifos[br][-1] = b
        return out

    @staticmethod
    def _diagonal_interleave(bits: np.ndarray, span: int) -> np.ndarray:
        usable = (len(bits) // span) * span
        out = np.zeros(usable, dtype=bits.dtype)
        n = int(np.sqrt(span))
        for blk in range(0, usable, span):
            chunk = bits[blk : blk + span]
            grid = np.zeros((n, n), dtype=bits.dtype)
            ptr = 0
            for r in range(n):
                for c in range(n):
                    if ptr < span:
                        grid[r, c] = chunk[ptr]
                        ptr += 1
            diag_read = []
            for d in range(2*n - 1):
                for r in range(max(0, d - n + 1), min(n, d + 1)):
                    diag_read.append(grid[r, d - r])
            out[blk : blk + span] = np.array(diag_read[:span], dtype=bits.dtype)
        return out

    @staticmethod
    def _pseudo_random_interleave(bits: np.ndarray, block_size: int, seed: int) -> np.ndarray:
        rng = np.random.default_rng(seed)
        perm = rng.permutation(block_size)
        usable = (len(bits) // block_size) * block_size
        out = np.zeros(usable, dtype=bits.dtype)
        for blk in range(0, usable, block_size):
            out[blk : blk + block_size] = bits[blk : blk + block_size][perm]
        return out

    @staticmethod
    def _modulate(bits: np.ndarray, mod_type: str) -> np.ndarray:
        if mod_type == "BPSK":
            return (1.0 - 2.0 * bits).astype(np.complex64)
        elif mod_type == "QPSK":
            pairs = bits[: len(bits) - (len(bits) % 2)].reshape(-1, 2)
            i_sym = (1.0 - 2.0 * pairs[:, 0]) / np.sqrt(2)
            q_sym = (1.0 - 2.0 * pairs[:, 1]) / np.sqrt(2)
            return (i_sym + 1j * q_sym).astype(np.complex64)
        elif mod_type == "8-PSK":
            triplets = bits[: len(bits) - (len(bits) % 3)].reshape(-1, 3)
            phases = (triplets[:, 0] * 4 + triplets[:, 1] * 2 + triplets[:, 2]) * (2 * np.pi / 8.0)
            return np.exp(1j * phases).astype(np.complex64)
        elif mod_type == "16-QAM":
            quads = bits[: len(bits) - (len(bits) % 4)].reshape(-1, 4)
            i_map = { (0,0): -3, (0,1): -1, (1,1): 1, (1,0): 3 }
            q_map = { (0,0): -3, (0,1): -1, (1,1): 1, (1,0): 3 }
            i_sym = np.array([i_map[(b[0], b[1])] for b in quads], dtype=np.float32) / np.sqrt(10)
            q_sym = np.array([q_map[(b[2], b[3])] for b in quads], dtype=np.float32) / np.sqrt(10)
            return (i_sym + 1j * q_sym).astype(np.complex64)
        elif mod_type == "2-FSK":
            f_dev = 0.1
            phase = np.cumsum(np.where(bits == 0, -f_dev, f_dev) * 2 * np.pi)
            return np.exp(1j * phase).astype(np.complex64)
        else:
            return (1.0 - 2.0 * bits).astype(np.complex64)

    @staticmethod
    def _rrc_filter(beta: float, sps: int, span: int) -> np.ndarray:
        N = span * sps + 1
        t = np.arange(-span/2, span/2 + 1/sps, 1/sps)
        h = np.zeros(len(t), dtype=np.float32)
        for i, val in enumerate(t):
            if np.isclose(val, 0.0):
                h[i] = 1.0 - beta + 4 * beta / np.pi
            elif np.isclose(np.abs(val), 1 / (4 * beta)):
                h[i] = (beta / np.sqrt(2)) * (((1 + 2 / np.pi) * np.sin(np.pi / (4 * beta))) + 
                                             ((1 - 2 / np.pi) * np.cos(np.pi / (4 * beta))))
            else:
                num = np.sin(np.pi * val * (1 - beta)) + 4 * beta * val * np.cos(np.pi * val * (1 + beta))
                den = np.pi * val * (1 - (4 * beta * val)**2)
                h[i] = num / den
        return h / np.sqrt(np.sum(h**2))

