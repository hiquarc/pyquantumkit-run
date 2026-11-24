import json
from pyquantumkit import CircuitIO
from pqk_run import RunError
from pqk_run.result import RunResult, _normalize_counts
from ._backend import _ProviderBackend

class OpenQuantumBackend(_ProviderBackend):
    provider = 'openquantum'
    framework = 'OpenQASM2.0'
    api_key_hint = (
        'Check that the API key file contains an OpenQuantum SDK client id and client secret.'
    )
    _API_KEY_MARKERS = ('unauthorized', 'authentication', 'invalid_client', 'invalid client', '401')
    _SIMULATOR_TYPES = {'simulator', 'sim'}
    _QPU_TYPES = {'qpu', 'hardware'}
    _SIMULATOR_SUFFIXES = {'sim', 'qiskit', 'cirq', 'pennylane'}

    def _guard(self, action: str, exc: BaseException, hint: bool = False) -> RunError:
        message = getattr(exc, 'message', None)
        text = message if isinstance(message, str) and message else exc
        if self._api_key_failure(exc):
            return self._api_key_error(action, text)
        if hint:
            return RunError(f'{self.provider} could not {action}: {text}. {self.api_key_hint}')
        return RunError(f'{self.provider} could not {action}: {text}')

    def _credentials(self):
        try:
            from openquantum_sdk.auth import ClientCredentials, ClientCredentialsAuth
        except ImportError as exc:
            raise RunError(
                "Provider 'openquantum' requires openquantum-sdk. Install 'pyquantumkit[openquantum]'."
            ) from exc
        text = self.api_key.strip()
        try:
            if text.startswith('{'):
                data = json.loads(text)
                creds = ClientCredentials(
                    client_id=str(data['client_id']).strip(),
                    client_secret=str(data['client_secret']).strip(),
                )
                return ClientCredentialsAuth(creds=creds), None
            parts = text.split()
            if len(parts) >= 2:
                creds = ClientCredentials(client_id=parts[0], client_secret=parts[1])
                return ClientCredentialsAuth(creds=creds), None
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise self._guard('read the API key', exc, hint=True) from exc
        return None, text

    def _clients(self):
        try:
            from openquantum_sdk.clients import ManagementClient, SchedulerClient
        except ImportError as exc:
            raise RunError(
                "Provider 'openquantum' requires openquantum-sdk. Install 'pyquantumkit[openquantum]'."
            ) from exc
        auth, token = self._credentials()
        if auth is not None:
            return SchedulerClient(auth=auth), ManagementClient(auth=auth)
        return SchedulerClient(token=token), ManagementClient(token=token)

    @classmethod
    def _is_simulator(cls, backend) -> bool:
        kind = str(getattr(backend, 'type', '') or '').strip().lower()
        if kind in cls._SIMULATOR_TYPES:
            return True
        code = str(getattr(backend, 'short_code', '') or '').strip().lower()
        suffix = code.rsplit(':', 1)[-1]
        if 'sim' in suffix or suffix in cls._SIMULATOR_SUFFIXES:
            return True
        return kind not in cls._QPU_TYPES and kind.endswith('simulator')

    def _groups(self, backends) -> tuple[str, str]:
        qpus = []
        simulators = []
        for backend in backends:
            code = str(getattr(backend, 'short_code', '') or '').strip()
            if not code or not getattr(backend, 'accepting_jobs', False):
                continue
            (simulators if self._is_simulator(backend) else qpus).append(code)
        return self._listed(qpus), self._listed(simulators)

    def _backend_classes(self, management) -> list:
        found = []
        cursor = None
        while True:
            page = management.list_backend_classes(limit=100, cursor=cursor)
            found.extend(page.backend_classes)
            cursor = getattr(page.pagination, 'next_cursor', None)
            if not cursor:
                return found

    @staticmethod
    def _measurement_counts(output) -> dict:
        if isinstance(output, dict) and isinstance(output.get('counts'), dict):
            return output['counts']
        if isinstance(output, dict):
            return output
        raise RunError('OpenQuantum returned measurement results that are not a count dictionary.')

    def _configuration_data(self, scheduler) -> dict:
        user = {
            key: value for key, value in dict(self.options.get('configuration') or {}).items()
            if key != 'shots'
        }
        data = {}
        for option in scheduler.configuration_options(self.backend):
            key = getattr(option, 'key', None)
            if not key or key == 'shots' or key in user or not getattr(option, 'required', False):
                continue
            if getattr(option, 'visible_when', None):
                continue
            default = getattr(option, 'default', None)
            if default is not None:
                data[key] = default
        data.update(user)
        return data

    def _run_local(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        raise RunError(
            "Provider 'openquantum' runs on remote backends such as 'ibm:qiskit' and 'google:cirq'."
        )

    def _run_cloud(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        try:
            from openquantum_sdk.clients import JobSubmissionConfig
        except ImportError as exc:
            raise RunError(
                "Provider 'openquantum' requires openquantum-sdk. Install 'pyquantumkit[openquantum]'."
            ) from exc
        scheduler, management = self._clients()
        try:
            try:
                backends = self._backend_classes(management)
            except Exception as exc:
                raise self._guard('list backends', exc, hint=True) from exc
            qpus, simulators = self._groups(backends)
            available = {
                str(getattr(backend, 'short_code', '') or '').strip()
                for backend in backends
                if getattr(backend, 'accepting_jobs', False)
            }
            if self.backend not in available:
                raise self._invalid_backend(qpus, simulators)
            self._announce_cloud(qpus, simulators)
            qasm = circuit.export_standalone_code('OpenQASM2.0', 'qs', subsdict=subsdict)
            try:
                configuration = self._configuration_data(scheduler)
            except Exception as exc:
                raise self._guard(f"configure backend '{self.backend}'", exc) from exc
            config = JobSubmissionConfig(
                backend_class_id=self.backend,
                name=self.options.get('name', 'pyquantumkit'),
                job_subcategory_id=self.options.get('job_subcategory', 'phys:hds'),
                shots=shots,
                configuration_data=configuration,
                execution_plan=self.options.get('execution_plan', 'public'),
                queue_priority=self.options.get('queue_priority', 'standard'),
                auto_approve_quote=True,
                verbose=bool(self.options.get('verbose', False)),
                job_timeout_seconds=int(self.options.get('job_timeout_seconds', 86400)),
                input_format='qasm',
                submitted_with='pyquantumkit',
            )
            try:
                job = scheduler.submit_job(config, file_content=qasm.encode())
                output = scheduler.download_job_output(job)
            except Exception as exc:
                raise self._guard(f"run backend '{self.backend}'", exc) from exc
        finally:
            for client in (scheduler, management):
                close = getattr(client, 'close', None)
                if close is not None:
                    try:
                        close()
                    except Exception:
                        pass
        counts = self._measurement_counts(output)
        if not counts:
            raise RunError(f"OpenQuantum backend '{self.backend}' returned no measurement results.")
        return self._result(_normalize_counts(counts, circuit.get_ncbits()), str(job.id), 'r')
