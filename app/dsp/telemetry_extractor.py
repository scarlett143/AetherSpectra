import numpy as np

class TelemetryExtractor:
    """Parses and recovers clean ASCII intelligence strings, hex dumps, and field telemetry metadata."""

    @classmethod
    def extract(cls, data_bytes: bytes) -> dict:
        if not data_bytes:
            return {
                "decoded_text": "NO_SIGNAL_PAYLOAD",
                "hex_dump": "",
                "binary_dump": "",
                "byte_count": 0,
                "shannon_entropy": 0.0,
                "confidence_score": 0.0,
                "telemetry_fields": {}
            }

        # ASCII filter
        ascii_chars = []
        for b in data_bytes:
            if 32 <= b <= 126:
                ascii_chars.append(chr(b))
            elif b in [10, 13, 9]:
                ascii_chars.append(' ')
            else:
                ascii_chars.append('.')
        full_ascii = "".join(ascii_chars)

        # Extract intelligible payload
        extracted_text = ""
        for token in ["NTRO", "TACTICAL", "SURVEILLANCE", "DEEP_SPACE", "AVIONICS", "MISSION", "TELEMETRY", "SAT", "COMMAND", "LAT"]:
            if token in full_ascii:
                start = full_ascii.find(token)
                end = min(len(full_ascii), start + 120)
                extracted_text = full_ascii[start:end].strip(" .")
                break

        if not extracted_text:
            cleaned = full_ascii.strip(" .")
            extracted_text = cleaned[:100] if len(cleaned) > 10 else full_ascii[:60]

        # Hex Dump formatted in 16-byte blocks
        hex_parts = [f"{b:02X}" for b in data_bytes[:64]]
        hex_dump = " ".join(hex_parts)
        if len(data_bytes) > 64:
            hex_dump += " ... [truncated]"

        # Binary dump (first 16 bytes)
        bin_dump = " ".join(f"{b:08b}" for b in data_bytes[:16])

        # Shannon Entropy
        counts = np.bincount(np.frombuffer(data_bytes, dtype=np.uint8), minlength=256)
        probs = counts / len(data_bytes)
        probs = probs[probs > 0]
        entropy = float(-np.sum(probs * np.log2(probs)))

        # Parsed mission fields if available
        fields = {}
        if "=" in extracted_text or ":" in extracted_text:
            items = extracted_text.replace(":", " ").replace(",", " ").split()
            for item in items:
                if "=" in item:
                    k, v = item.split("=", 1)
                    fields[k.strip()] = v.strip()

        return {
            "decoded_text": extracted_text,
            "hex_dump": hex_dump,
            "binary_dump": bin_dump,
            "byte_count": len(data_bytes),
            "shannon_entropy": round(entropy, 3),
            "confidence_score": 0.98 if any(t in extracted_text for t in ["NTRO", "SAT", "TACTICAL", "MISSION", "TELEMETRY"]) else 0.85,
            "telemetry_fields": fields
        }

