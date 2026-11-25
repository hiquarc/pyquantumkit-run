from pyquantumkit import CircuitIO
from pqk_run import RunError
from pqk_run.result import RunResult, _normalize_counts
from pqk_run.circuit import _convert_circuit
from ._backend import _ProviderBackend

class IQMBackend(_ProviderBackend):
    provider = 'iqm'
    framework = 'qiskit'
    api_key_hint = 'Check that the API key is an IQM Resonance access token.'
    _API_KEY_MARKERS = ('unauthorized', 'authentication', 'invalid token', '401')
    _SERVER_URL = 'https://resonance.iqm.tech/'
    _ALIAS_MARKER = 'Available quantum computers are:'

    @staticmethod
    def _is_simulator(name: str) -> bool:
        lowered = name.lower()
        return any(marker in lowered for marker in ('sim', 'fake', 'mock'))

    def _server_url(self) -> str:
        return self.options.get('url') or self._SERVER_URL

    def _guard(self, action: str, exc: BaseException, hint: bool = False) -> RunError:
        message = getattr(exc, 'message', None)
        text = message if isinstance(message, str) and message else exc
        if self._api_key_failure(exc):
            return self._api_key_error(action, text)
        if hint:
            return RunError(f'{self.provider} could not {action}: {text}. {self.api_key_hint}')
        return RunError(f'{self.provider} could not {action}: {text}')

    def _groups(self, names) -> tuple[str, str]:
        qpus = self._listed(name for name in names if not self._is_simulator(name))
        simulators = self._listed(name for name in names if self._is_simulator(name))
        return qpus, simulators

    @classmethod
    def _aliases_from_message(cls, message: str) -> list[str]:
        if cls._ALIAS_MARKER not in message:
            return []
        listed = message.split(cls._ALIAS_MARKER, 1)[1]
        return [name.strip().strip('.') for name in listed.split(',') if name.strip()]

    def _computers(self) -> list[str]:
        try:
            from iqm.iqm_server_client import IQMServerClient
            from iqm.station_control.client.authentication import (
                ClientAuthenticationError, ClientConfigurationError,
            )
        except ImportError as exc:
            raise RunError(
                "Provider 'iqm' requires iqm-client with the qiskit extra. Install 'pyquantumkit-run[iqm]'."
            ) from exc
        try:
            client = IQMServerClient(
                self._server_url(), quantum_computer=self.backend, token=self.api_key,
            )
        except ClientAuthenticationError as exc:
            raise self._guard('log in', exc, hint=True) from exc
        except ClientConfigurationError as exc:
            names = self._aliases_from_message(str(exc))
            if names or 'does not exist' in str(exc):
                raise self._invalid_backend(*self._groups(names)) from exc
            raise self._guard('list backends', exc, hint=True) from exc
        except Exception as exc:
            raise self._guard('list backends', exc, hint=self._api_key_failure(exc)) from exc
        try:
            computers = client._get_quantum_computers()
        except Exception as exc:
            raise self._guard('list backends', exc, hint=True) from exc
        finally:
            client.close()
        return [computer.alias for computer in computers]

    def _run_local(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        try:
            from qiskit_aer import AerSimulator
        except ImportError as exc:
            raise RunError("Provider 'iqm' local execution requires qiskit-aer. Install 'pyquantumkit-run[qiskit]'.") from exc
        return self._simulator_result(AerSimulator(), circuit, shots, subsdict)

    def _run_cloud(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        names = self._computers()
        qpus, simulators = self._groups(names)
        if self.backend not in names:
            raise self._invalid_backend(qpus, simulators)
        self._announce_cloud(qpus, simulators)
        try:
            from iqm.qiskit_iqm import IQMProvider
            from qiskit import transpile
        except ImportError as exc:
            raise RunError(
                "Provider 'iqm' requires iqm-client with the qiskit extra. Install 'pyquantumkit-run[iqm]'."
            ) from exc
        provider = IQMProvider(self._server_url(), quantum_computer=self.backend, token=self.api_key)
        cloud_backend = None
        try:
            cloud_backend = provider.get_backend()
            converted = _convert_circuit(circuit, self.framework, subsdict)
            transpiled = transpile(converted, backend=cloud_backend)
            job = cloud_backend.run(
                transpiled, shots=shots, use_timeslot=bool(self.options.get('use_timeslot', False)),
            )
            result = job.result()
        except Exception as exc:
            raise self._guard(f"run backend '{self.backend}'", exc) from exc
        finally:
            client = getattr(cloud_backend, 'client', None)
            if client is not None:
                client.close()
        counts = result.get_counts()
        if not counts:
            raise RunError(f"IQM backend '{self.backend}' returned no measurement results.")
        task_id = job.job_id() if callable(job.job_id) else str(job.job_id)
        return self._result(_normalize_counts(counts, circuit.get_ncbits()), str(task_id))
    