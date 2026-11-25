import json
import re
from pyquantumkit import CircuitIO
from pqk_run import RunError
from pqk_run.result import RunResult, _normalize_counts
from pqk_run.circuit import _convert_circuit
from ._backend import _ProviderBackend

class WuYueBackend(_ProviderBackend):
    provider = 'wuyue'
    framework = 'qiskit'
    api_key_hint = 'Check that the API key file contains a WuYue access key and secret key.'
    _API_KEY_MARKERS = (
        'unauthorized', 'forbidden', 'signature', 'accesskey', 'access_key',
        '密钥', '鉴权', '认证', '签名',
    )
    _RUNNER_OPTIONS = (
        'mapping_flag', 'is_amend', 'circuit_optimization', 'calculate_type',
        'qubit_mapping', 'gate_decomposition', 'dry_run', 'initial_mapping',
        'noise_type', 'qmachine_type', 'bit_info',
    )
    def _credentials(self) -> tuple[str, str]:
        text = self.api_key.strip()
        access = secret = None
        if text.startswith('{'):
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise RunError(
                    "Provider 'wuyue' requires an access key and a secret key."
                ) from exc
            if isinstance(data, dict):
                access = data.get('access_key') or data.get('accessKey')
                secret = data.get('secret_key') or data.get('secretKey')
        else:
            parts = text.split()
            if len(parts) == 2:
                access, secret = parts
        access = '' if access is None else str(access).strip()
        secret = '' if secret is None else str(secret).strip()
        if not access or not secret:
            raise RunError(
                "Provider 'wuyue' requires an access key and a secret key. "
                "Put them on two lines, as two tokens, or as JSON with access_key and secret_key."
            )
        return access, secret

    @staticmethod
    def _configure():
        try:
            from wuyue.utils import ml_backend
        except ImportError as exc:
            raise RunError(
                "Provider 'wuyue' requires the wuyue package. Install 'pyquantumkit[wuyue]'."
            ) from exc
        if ml_backend.get_xp() is None:
            ml_backend.set_ml_backend('numpy')

    @staticmethod
    def _is_simulator(name: str) -> bool:
        lowered = name.lower()
        return 'sim' in lowered or 'amp' in lowered

    def _selected_groups(self) -> tuple[str, str]:
        # The installed SDK exposes submit and query only, so the banner
        # classifies the device selected for this run.
        if self._is_simulator(self.backend):
            return self._listed([]), self._listed([self.backend])
        return self._listed([self.backend]), self._listed([])

    def _task_name(self) -> str:
        name = str(self.options.get('name', 'pyquantumkit'))
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,22}[A-Za-z0-9]', name):
            raise RunError(
                'wuyue task name must be 5-24 characters, start with a letter, '
                'end with a letter or digit, and contain only letters, digits, and underscores.'
            )
        return name

    def _timeout(self) -> int:
        timeout = self.options.get('timeout', 3600)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3600:
            raise RunError('wuyue timeout must be an integer from 1 to 3600 seconds.')
        return timeout

    def _guard(self, action: str, exc: BaseException) -> RunError:
        text = str(exc)
        if '设备编号不合法' in text:
            return RunError(
                f"Invalid {self.provider} backend '{self.backend}'. "
                'The WuYue platform rejected this device id.'
            )
        if self._api_key_failure(exc):
            return self._api_key_error(action, exc)
        return RunError(f'{self.provider} could not {action}: {text}')

    @staticmethod
    def _measured_counts(values: dict, ncbits: int, shots: int = None,
                         probabilities: bool = False) -> dict[str, int]:
        # Qz-01 and Mq-02 return one bit per chip qubit. The measured bits
        # are the end of that string.
        counts = _normalize_counts(values, ncbits, probabilities, shots)
        if ncbits <= 0:
            return counts
        measured = {}
        for bit, count in counts.items():
            if len(bit) > ncbits:
                bit = bit[-ncbits:]
            if count:
                measured[bit] = measured.get(bit, 0) + count
        return measured

    @staticmethod
    def _line_result(raw):
        # Mq-02 leaves out_counts empty and stores the histogram here.
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        table = parsed.get('lineResult') if isinstance(parsed, dict) else None
        return table if isinstance(table, dict) and table else None

    def _measurement(self, result, circuit: CircuitIO, shots: int) -> dict[str, int]:
        if not result.get_success():
            status = result.get_status()
            raw = result.get_raw_result()
            detail = status if not raw else f'{status}: {str(raw)[:500]}'
            raise RunError(f"WuYue backend '{self.backend}' failed: {detail}")
        ncbits = circuit.get_ncbits()
        counts = result.get_counts() or {}
        if counts:
            return self._measured_counts(counts, ncbits)
        probabilities = result.get_prob() or {}
        if probabilities:
            return self._measured_counts(
                {key: float(value) for key, value in probabilities.items()},
                ncbits, shots, True,
            )
        raw = self._line_result(result.get_raw_result())
        if raw:
            return self._measured_counts(raw, ncbits)
        detail = str(result.get_raw_result() or '')[:500]
        suffix = f': {detail}' if detail else ''
        raise RunError(f"WuYue backend '{self.backend}' returned no measurement results{suffix}")

    def _run_local(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        self._configure()
        try:
            from qiskit import qasm2
            from wuyue.backend import Backend
            from wuyue.circuit.qasm2 import QASM2Importer
        except ImportError as exc:
            raise RunError(
                "Provider 'wuyue' local execution requires wuyue and qiskit. "
                "Install 'pyquantumkit[wuyue]'."
            ) from exc
        converted = _convert_circuit(circuit, self.framework, subsdict)
        try:
            native = QASM2Importer.qasm2circuit(qasm2.dumps(converted))
            simulator = Backend.get_device('Full amplitude')
            simulator.apply(native)
            counts = simulator.run(shots)
        except (TypeError, ValueError) as exc:
            raise RunError(f'wuyue local simulator failed: {exc}') from exc
        return self._result(_normalize_counts(counts, circuit.get_ncbits()))

    def _run_cloud(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        access_key, secret_key = self._credentials()
        self._configure()
        try:
            from wuyue.plugin.runner import Runner
        except ImportError as exc:
            raise RunError(
                "Provider 'wuyue' requires the wuyue package. Install 'pyquantumkit[wuyue]'."
            ) from exc
        converted = _convert_circuit(circuit, self.framework, subsdict)
        timeout = self._timeout()
        task_name = self._task_name()
        runner_options = {
            key: self.options[key] for key in self._RUNNER_OPTIONS if key in self.options
        }
        if self._is_simulator(self.backend) and 'calculate_type' not in runner_options:
            runner_options['calculate_type'] = 1
        self._announce_cloud(*self._selected_groups())
        try:
            runner = Runner(
                access_key=access_key,
                secret_key=secret_key,
                auto_retry=False,
                endpoint=self.options.get('endpoint'),
            )
            result = runner.run(
                qc=converted,
                qubits=circuit.get_nqbits(),
                shots=shots,
                device_id=self.backend,
                task_name=task_name,
                timeout=timeout,
                **runner_options,
            )
        except TimeoutError as exc:
            raise RunError(
                f"WuYue backend '{self.backend}' did not finish within {timeout} seconds. "
                'The task may still be queued; check it in the WuYue console.'
            ) from exc
        except (RuntimeError, ValueError) as exc:
            raise self._guard(f"run backend '{self.backend}'", exc) from exc
        return self._result(self._measurement(result, circuit, shots), str(result.get_task_id()))
