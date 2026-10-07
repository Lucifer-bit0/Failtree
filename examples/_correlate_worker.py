"""Demo worker - version 2 (after): injected bug comment + same failure."""

def process(key: str) -> None:
    # injected bug: stricter validation
    raise ValueError(f"bad record {key}")
