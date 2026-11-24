import importlib
import importlib.metadata
from pyquantumkit import CircuitIO, framework_interpret_protocol
from pqk_run import RunError, Supported_Frameworks
from pqk_run.circuit import _convert_circuit
from pqk_run.result import _normalize_counts, RunResult
from ._backend import _ProviderBackend

class QuafuBackend(_ProviderBackend):
    provider = 'quafu'
    framework = 'pyquafu'
    _AVAILABLE_STATUS = {'online', 'starting'}

    @staticmethod
    def _is_simulator(device: dict) -> bool:
        kind = device.get('kind')
        if kind == 'sim':
            return True
        if kind == 'real':
            return False
        name = str(device.get('name', ''))
        return name == 'sim' or name.endswith('-sim') or '-sim-' in name

    @classmethod
    def _is_available(cls, device: dict) -> bool:
        status = device.get('status')
        return status is None or str(status).lower() in cls._AVAILABLE_STATUS

    def _available_groups(self, devices) -> tuple[str, str]:
        qpus = []
        simulators = []
        for device in devices:
            if not isinstance(device, dict) or not device.get('name') or not self._is_available(device):
                continue
            (simulators if self._is_simulator(device) else qpus).append(device['name'])
        return self._listed(qpus), self._listed(simulators)

    def _run_local(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        import quafu
        if not hasattr(quafu, 'simulate'):
            raise RunError("Quafu local execution requires pyquafu. Please install Python package 'quafu'.")
        converted = _convert_circuit(circuit, self.framework, subsdict)
        result = quafu.simulate(converted, shots=shots)
        return self._result(_normalize_counts(result.counts, circuit.get_ncbits()))

    def _run_cloud(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        try:
            import quafu
        except ImportError as exc:
            raise RunError("Provider 'quafu' requires pyquafu. Please install Python package 'quafu'.") from exc
        client_class = getattr(quafu, 'Client', None)
        if client_class is None:
            try:
                from quafu.client import Client as client_class
                quafu.__version__ = importlib.metadata.version('quafu-sdk')
            except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
                raise RunError(
                    "Quafu cloud execution requires quafu-sdk. Please install Python package 'quafu-sdk'."
                ) from exc
        client = client_class(api_key=self.api_key, base_url=self.options.get('base_url'))
        devices = list(client.devices())
        available_backends = {
            device['name'] for device in devices
            if isinstance(device, dict) and device.get('name') and self._is_available(device)
        }
        qpus, simulators = self._available_groups(devices)
        if self.backend not in available_backends:
            raise self._invalid_backend(qpus, simulators)
        self._announce_cloud(qpus, simulators)
        compiler = self.options.get('compiler', 'qiskit')
        qasm = circuit.export_standalone_code('OpenQASM2.0', 'qs', subsdict=subsdict)
        job = client.submit(qasm, target=self.backend, shots=shots, compiler=compiler)
        result = job.result()
        if result.counts is None:
            raise RunError(f'Quafu job {job.id} returned no measurement results.')
        counts = _normalize_counts(result.counts, circuit.get_ncbits())
        protocol = framework_interpret_protocol(compiler) if compiler in Supported_Frameworks else 'r'
        return self._result(counts, str(job.id), protocol)
    