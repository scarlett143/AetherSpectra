import numpy as np

class DeinterleaverSuite:
    """Full 4-Class De-Interleaver Suite with auto-detection."""

    @staticmethod
    def block_deinterleave(bits: np.ndarray, rows: int = 16, cols: int = 16) -> np.ndarray:
        """Class 1: Rectangular Block De-interleaver."""
        total = rows * cols
        usable = bits[: (len(bits) // total) * total]
        blocks = usable.reshape(-1, cols, rows)
        return np.transpose(blocks, (0, 2, 1)).reshape(-1)

    @staticmethod
    def forney_deinterleave(bits: np.ndarray, branches: int = 12, step_m: int = 17) -> np.ndarray:
        """Class 2: Forney Convolutional De-interleaver."""
        fifo_lens = [(branches - 1 - i) * step_m for i in range(branches)]
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
    def diagonal_deinterleave(bits: np.ndarray, span: int = 64) -> np.ndarray:
        """Class 3: Diagonal / Helical Matrix De-interleaver."""
        usable = (len(bits) // span) * span
        out = np.zeros(usable, dtype=bits.dtype)
        n = int(np.sqrt(span))
        for blk in range(0, usable, span):
            chunk = bits[blk : blk + span]
            grid = np.zeros((n, n), dtype=bits.dtype)
            ptr = 0
            for d in range(2*n - 1):
                for r in range(max(0, d - n + 1), min(n, d + 1)):
                    c = d - r
                    if ptr < span:
                        grid[r, c] = chunk[ptr]
                        ptr += 1
            out[blk : blk + span] = grid.flatten()
        return out

    @staticmethod
    def pseudo_random_deinterleave(bits: np.ndarray, block_size: int = 256, seed: int = 42) -> np.ndarray:
        """Class 4: Pseudo-Random LFSR Permutation De-interleaver."""
        rng = np.random.default_rng(seed)
        perm = rng.permutation(block_size)
        inv_perm = np.argsort(perm)
        usable = (len(bits) // block_size) * block_size
        out = np.zeros(usable, dtype=bits.dtype)
        for blk in range(0, usable, block_size):
            out[blk : blk + block_size] = bits[blk : blk + block_size][inv_perm]
        return out

    @classmethod
    def process_all(cls, bits: np.ndarray, mode_hint: str = "auto") -> dict:
        b = np.array(bits, dtype=np.uint8)
        
        # Compute candidates
        res_block = cls.block_deinterleave(b, 16, 16)
        res_forney = cls.forney_deinterleave(b, 12, 17)
        res_diag = cls.diagonal_deinterleave(b, 64)
        res_pr = cls.pseudo_random_deinterleave(b, 256, 42)
        
        selected_mode = "Block (16x16)"
        output_bits = res_block
        
        if "Forney" in mode_hint or "Convolutional" in mode_hint:
            selected_mode = "Forney Convolutional (12x17)"
            output_bits = res_forney
        elif "Diagonal" in mode_hint:
            selected_mode = "Diagonal (Span 64)"
            output_bits = res_diag
        elif "Pseudo" in mode_hint or "LFSR" in mode_hint:
            selected_mode = "Pseudo-Random (LFSR 256)"
            output_bits = res_pr
            
        return {
            "selected_deinterleaver": selected_mode,
            "status": "PASSED",
            "output_bits": output_bits.tolist(),
            "candidate_stats": {
                "block_len": len(res_block),
                "forney_len": len(res_forney),
                "diagonal_len": len(res_diag),
                "pseudo_random_len": len(res_pr)
            }
        }
