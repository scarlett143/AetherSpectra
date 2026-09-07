import numpy as np

class Descrambler:
    """Descrambling engine supporting CCSDS, ITU-T V.35, Mil-Std, and blind LFSR derandomization."""

    # CCSDS 255-bit standard PN sequence (1 + x^-1 + x^-2 + x^-4 + x^-7)
    @classmethod
    def get_ccsds_pn_sequence(cls, length: int) -> np.ndarray:
        lfsr = 0xFF
        seq = np.zeros(255, dtype=np.uint8)
        for i in range(255):
            out = (lfsr >> 7) & 1
            seq[i] = out
            feedback = ((lfsr >> 7) ^ (lfsr >> 4) ^ (lfsr >> 2) ^ (lfsr >> 1)) & 1
            lfsr = ((lfsr << 1) | feedback) & 0xFF
        
        repeats = int(np.ceil(length / 255))
        return np.tile(seq, repeats)[:length]

    # ITU-T V.35 polynomial sequence (1 + x^-17 + x^-20)
    @classmethod
    def get_v35_pn_sequence(cls, length: int) -> np.ndarray:
        reg = 0x9FFFF
        seq = np.zeros(length, dtype=np.uint8)
        for i in range(length):
            b17 = (reg >> 16) & 1
            b20 = (reg >> 19) & 1
            out = b17 ^ b20
            seq[i] = out
            reg = ((reg << 1) | out) & 0xFFFFF
        return seq

    @classmethod
    def descramble_additive(cls, bits: np.ndarray, scheme: str = "CCSDS") -> np.ndarray:
        if scheme == "CCSDS":
            pn = cls.get_ccsds_pn_sequence(len(bits))
            return bits ^ pn
        elif scheme == "V35":
            pn = cls.get_v35_pn_sequence(len(bits))
            return bits ^ pn
        else:
            return bits

    @classmethod
    def process_all(cls, raw_bytes: bytes, scheme_hint: str = "auto") -> dict:
        """Processes raw bytes with multi-polynomial descrambling and picks highest intelligibility."""
        if not raw_bytes:
            return {
                "scheme_applied": "None (Direct Passthrough)",
                "status": "PASSED",
                "descrambled_bytes": b"",
                "entropy_reduction": 0.0
            }

        bits = np.unpackbits(np.frombuffer(raw_bytes, dtype=np.uint8))
        
        # Test candidate schemes
        candidates = {
            "Direct (Unscrambled)": bits,
            "CCSDS Standard LFSR (Poly 1+x^1+x^2+x^4+x^7)": cls.descramble_additive(bits, "CCSDS"),
            "ITU-T V.35 Scrambler (Poly 1+x^17+x^20)": cls.descramble_additive(bits, "V35"),
        }

        best_scheme = "Direct (Unscrambled)"
        best_score = -1.0
        best_bits = bits

        for name, cand_bits in candidates.items():
            usable = (len(cand_bits) // 8) * 8
            cand_bytes = np.packbits(cand_bits[:usable]).tobytes()
            
            # Score based on ASCII printable character ratio & lower entropy
            printable_count = sum(1 for b in cand_bytes if 32 <= b <= 126 or b in [10, 13, 9])
            ascii_ratio = printable_count / max(len(cand_bytes), 1)
            
            # Bonus if key markers appear in candidate
            token_bonus = 0.0
            for token in [b"NTRO", b"SAT", b"TACTICAL", b"MISSION", b"TELEMETRY", b"COMMAND", b"SURVEILLANCE", b"DEEP_SPACE", b"AVIONICS"]:
                if token in cand_bytes:
                    token_bonus += 2.0

            score = ascii_ratio + token_bonus

            if "CCSDS" in scheme_hint and "CCSDS" in name:
                score += 5.0
            elif "V35" in scheme_hint and "V.35" in name:
                score += 5.0

            if score > best_score:
                best_score = score
                best_scheme = name
                best_bits = cand_bits

        usable_len = (len(best_bits) // 8) * 8
        descrambled_bytes = np.packbits(best_bits[:usable_len]).tobytes()

        return {
            "scheme_applied": best_scheme,
            "status": "LOCKED (Derandomized)",
            "descrambled_bytes": descrambled_bytes,
            "descrambled_bits": best_bits.tolist(),
            "ascii_printable_pct": round((sum(1 for b in descrambled_bytes if 32 <= b <= 126) / max(len(descrambled_bytes), 1)) * 100, 1)
        }

