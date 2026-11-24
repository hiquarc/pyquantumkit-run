from pyquantumkit import CircuitIO
from ._backend import _ProviderBackend
from pqk_run.result import RunResult
from pqk_run import RunError

class QiskitBackend(_ProviderBackend):
    provider = 'qiskit'
    framework = 'qiskit'
    local_only = True

    def _run_local(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        try:
            from qiskit_aer import AerSimulator
        except ImportError as exc:
            raise RunError("Provider 'qiskit' requires qiskit-aer. Please install Python package 'qiskit-aer'.") from exc
        return self._simulator_result(AerSimulator(), circuit, shots, subsdict)
    