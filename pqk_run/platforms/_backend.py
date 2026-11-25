import os

from pqk_run import RunError
from pqk_run.result import RunResult, _normalize_counts
from pqk_run.circuit import _convert_circuit
from pyquantumkit import CircuitIO, run_and_get_counts, framework_interpret_protocol

def _api_key(provider: str, api_key: str = None, api_key_file: str = None) -> str:
    key = api_key if api_key is not None else os.environ.get('PK_API_KEY')
    if key is None and api_key_file is not None:
        try:
            with open(api_key_file, 'r', encoding='utf-8') as stream:
                key = stream.read()
        except OSError as exc:
            raise RunError(f'Cannot read API key file: {api_key_file}') from exc
    if key is None or not key.strip():
        raise RunError(
            f"Provider '{provider}' requires an API key. Set PK_API_KEY, "
            "pass api_key, or use --api-key-file."
        )
    return key.strip()

def _print_run_info(provider: str, backend: str, available: str = None,
                    qpus: str = None, simulators: str = None) -> None:
    lines = [f'provider: {provider}']
    if qpus is not None or simulators is not None:
        lines.append(f'available QPU backends: {qpus or "(none)"}')
        lines.append(f'available remote simulator backends: {simulators or "(none)"}')
    else:
        lines.append(f'available backends: {available}')
    lines.append(f'running on backend: {backend}')
    rows = [f'  {line}' for line in lines[:-1]]
    rows.append(f'▶ {lines[-1]}')
    title = ' PyQuantumKit '
    width = max(max(len(row) for row in rows), len(title) + 2)
    print('┌' + title + '─' * (width - len(title)) + '┐')
    for row in rows:
        print('│' + row.ljust(width) + '│')
    print('└' + '─' * width + '┘')

class _ProviderBackend:
    provider: str
    framework: str
    api_key_hint = 'Check the API key.'
    _API_KEY_MARKERS = ('unauthorized',)
    default_backend = 'local'
    local_only = False

    def __init__(self, backend: str = None, api_key: str = None, options: dict = None):
        self.backend = backend or self.default_backend
        self.options = options or {}
        self.api_key = None
        if self.backend == 'local':
            return
        if self.local_only:
            raise RunError(
                f"Provider '{self.provider}' currently supports only backend 'local'."
            )
        self.api_key = _api_key(self.provider, api_key, self.options.get('api_key_file'))

    def _result(self, counts: dict[str, int], task_id: str = None,
                protocol: str = None) -> RunResult:
        if protocol is None:
            protocol = framework_interpret_protocol(self.framework)
        return RunResult(counts, self.provider, self.backend, task_id, protocol)

    def _simulator_result(self, qvm, circuit: CircuitIO, shots: int,
                          subsdict: dict = None) -> RunResult:
        converted = _convert_circuit(circuit, self.framework, subsdict)
        counts = run_and_get_counts(qvm, converted, shots)
        return self._result(_normalize_counts(counts, circuit.get_ncbits()))

    def run(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        if self.backend == 'local':
            _print_run_info(self.provider, self.backend, available='local')
            return self._run_local(circuit, shots, subsdict)
        return self._run_cloud(circuit, shots, subsdict)

    def _run_local(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        raise NotImplementedError

    def _run_cloud(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        raise NotImplementedError

    @classmethod
    def _api_key_failure(cls, exc: BaseException) -> bool:
        text = str(exc).lower()
        return any(marker in text for marker in cls._API_KEY_MARKERS)

    def _api_key_error(self, action: str, exc: BaseException) -> RunError:
        return RunError(f'{self.provider} could not {action}: {exc}. {self.api_key_hint}')

    def _invalid_backend(self, qpus: str, simulators: str) -> RunError:
        return RunError(
            f"Invalid {self.provider} backend '{self.backend}'. "
            f"Available QPU backends: {qpus}. "
            f"Available remote simulator backends: {simulators}."
        )

    def _announce_cloud(self, qpus: str, simulators: str) -> None:
        _print_run_info(self.provider, self.backend, qpus=qpus, simulators=simulators)

    @staticmethod
    def _listed(names) -> str:
        names = sorted(names)
        return ', '.join(names) if names else '(none)'
