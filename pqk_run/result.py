from dataclasses import dataclass
from pqk_run import RunError

@dataclass
class RunResult:
    counts: dict[str, int]
    provider: str
    backend: str
    task_id: str = None
    protocol: str = 'r'
    interpreted: list = None

def _normalize_counts(values: dict, ncbits: int, probabilities: bool = False,
                      shots: int = None) -> dict[str, int]:
    counts = {}
    for raw_bit, raw_count in values.items():
        if isinstance(raw_bit, int):
            bit = format(raw_bit, f'0{ncbits}b')
        else:
            bit = str(raw_bit).strip().replace(' ', '')
            if bit.lower().startswith('0x'):
                bit = format(int(bit, 16), f'0{ncbits}b')
        if not bit or set(bit) - {'0', '1'}:
            raise RunError(f'Invalid measurement result: {raw_bit!r}')
        count = round(raw_count * shots) if probabilities else int(raw_count)
        if count < 0:
            raise RunError(f'Invalid measurement count: {raw_count!r}')
        if count:
            counts[bit] = counts.get(bit, 0) + count
    return counts
