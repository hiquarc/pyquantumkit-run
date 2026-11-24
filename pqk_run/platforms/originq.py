from pyquantumkit import CircuitIO
from pqk_run import RunError
from pqk_run.circuit import _convert_circuit
from pqk_run.result import _normalize_counts, RunResult
from ._backend import _ProviderBackend

class OriginQBackend(_ProviderBackend):
    provider = 'originq'
    framework = 'pyqpanda3'
    api_key_hint = 'Check that the API key is an OriginQ QCloud key.'

    def _run_local(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        from pyqpanda3.core import CPUQVM
        return self._simulator_result(CPUQVM(), circuit, shots, subsdict)

    @staticmethod
    def _is_simulator(name: str) -> bool:
        return name.endswith('amplitude')

    def _catalog(self, service) -> dict:
        try:
            catalog = service.backends()
        except RuntimeError as exc:
            if self._api_key_failure(exc):
                raise self._api_key_error('list backends', exc) from exc
            raise RunError(
                f'{self.provider} could not list backends: {exc}. {self.api_key_hint}'
            ) from exc
        return dict(catalog)

    def _available_names(self, catalog: dict, simulator: bool) -> str:
        names = (
            name for name, available in catalog.items()
            if available and self._is_simulator(name) == simulator
        )
        return self._listed(names)

    def _run_cloud(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        from pyqpanda3.qcloud import QCloudService
        converted = _convert_circuit(circuit, self.framework, subsdict)
        service = QCloudService(self.api_key)
        catalog = self._catalog(service)
        qpus = self._available_names(catalog, False)
        simulators = self._available_names(catalog, True)
        if self.backend not in catalog:
            raise self._invalid_backend(qpus, simulators)
        try:
            cloud_backend = service.backend(self.backend)
        except RuntimeError as exc:
            if self._api_key_failure(exc):
                raise self._api_key_error(f"open backend '{self.backend}'", exc) from exc
            raise self._invalid_backend(qpus, simulators) from exc
        self._announce_cloud(qpus, simulators)
        try:
            job = cloud_backend.run(converted, shots)
        except RuntimeError as exc:
            if self._api_key_failure(exc):
                raise self._api_key_error(
                    f"run backend '{self.backend}'", exc
                ) from exc
            raise RunError(
                f"OriginQ backend '{self.backend}' rejected the circuit: {exc}"
            ) from exc
        task_id = str(job.job_id())
        probabilities = job.result().get_probs()
        if not probabilities:
            raise RunError(f'OriginQ job {task_id} returned no probabilities.')
        counts = _normalize_counts(probabilities, circuit.get_ncbits(), True, shots)
        return self._result(counts, task_id)
    