import numpy as np

class SymbolDemodulator:
    """Converts synchronized complex constellation symbols into hard decision bits and soft LLRs."""

    @staticmethod
    def demodulate(symbols: np.ndarray, mod_type: str = "QPSK") -> dict:
        if len(symbols) == 0:
            return {"bits": [], "soft_llrs": [], "bit_count": 0, "symbol_count": 0}

        sym_norm = symbols / (np.sqrt(np.mean(np.abs(symbols)**2)) + 1e-12)
        
        bits = []
        soft_llrs = []

        if mod_type == "BPSK":
            # Real axis decision
            b0 = (np.real(sym_norm) < 0).astype(np.uint8)
            bits = b0.tolist()
            soft_llrs = (-2.0 * np.real(sym_norm)).tolist()

        elif mod_type == "QPSK":
            # 2 bits per symbol (Gray mapping: 00: (+1,+1), 01: (+1,-1), 10: (-1,+1), 11: (-1,-1))
            b0 = (np.real(sym_norm) < 0).astype(np.uint8)
            b1 = (np.imag(sym_norm) < 0).astype(np.uint8)
            
            interleaved = np.empty(len(b0) * 2, dtype=np.uint8)
            interleaved[0::2] = b0
            interleaved[1::2] = b1
            bits = interleaved.tolist()

            llr0 = -2.0 * np.real(sym_norm)
            llr1 = -2.0 * np.imag(sym_norm)
            llr_inter = np.empty(len(llr0) * 2, dtype=np.float32)
            llr_inter[0::2] = llr0
            llr_inter[1::2] = llr1
            soft_llrs = llr_inter.tolist()

        elif mod_type == "8-PSK":
            # 3 bits per symbol
            phases = np.angle(sym_norm) % (2 * np.pi)
            sector = np.floor((phases + (np.pi / 8.0)) / (np.pi / 4.0)).astype(int) % 8
            
            # Gray code mapping for 8PSK
            gray_map = {
                0: [0, 0, 0],
                1: [0, 0, 1],
                2: [0, 1, 1],
                3: [0, 1, 0],
                4: [1, 1, 0],
                5: [1, 1, 1],
                6: [1, 0, 1],
                7: [1, 0, 0]
            }
            triplets = np.array([gray_map[s] for s in sector], dtype=np.uint8)
            bits = triplets.flatten().tolist()
            
            # Soft LLR approximation
            llr_arr = np.column_stack([
                -2.0 * np.real(sym_norm),
                -2.0 * np.imag(sym_norm),
                -2.0 * (np.abs(np.real(sym_norm)) - np.abs(np.imag(sym_norm)))
            ])
            soft_llrs = llr_arr.flatten().tolist()

        elif mod_type == "16-QAM":
            # 4 bits per symbol
            r = np.real(sym_norm) * np.sqrt(10)
            i = np.imag(sym_norm) * np.sqrt(10)
            
            # Real part bits (b0, b1)
            b0 = (r < 0).astype(np.uint8)
            b1 = (np.abs(r) < 2.0).astype(np.uint8)
            
            # Imag part bits (b2, b3)
            b2 = (i < 0).astype(np.uint8)
            b3 = (np.abs(i) < 2.0).astype(np.uint8)
            
            quads = np.column_stack([b0, b1, b2, b3])
            bits = quads.flatten().tolist()
            
            # Soft LLRs
            llr0 = -2.0 * r
            llr1 = 2.0 - np.abs(r)
            llr2 = -2.0 * i
            llr3 = 2.0 - np.abs(i)
            llr_quads = np.column_stack([llr0, llr1, llr2, llr3])
            soft_llrs = llr_quads.flatten().tolist()

        elif "FSK" in mod_type:
            # Frequency discrimination demodulation
            phases = np.unwrap(np.angle(sym_norm))
            inst_freq = np.diff(phases, prepend=phases[0])
            b0 = (inst_freq < 0).astype(np.uint8)
            bits = b0.tolist()
            soft_llrs = (-5.0 * inst_freq).tolist()

        else:
            b0 = (np.real(sym_norm) < 0).astype(np.uint8)
            bits = b0.tolist()
            soft_llrs = (-2.0 * np.real(sym_norm)).tolist()

        return {
            "bits": bits,
            "soft_llrs": soft_llrs,
            "bit_count": len(bits),
            "symbol_count": len(symbols),
            "bits_per_symbol": len(bits) // max(len(symbols), 1)
        }

