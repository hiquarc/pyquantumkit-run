import json
from pyquantumkit import CircuitIO
from pqk_run import RunError
from pqk_run.result import RunResult
from pqk_run.circuit import _convert_circuit
from ._backend import _ProviderBackend

class TianYanBackend(_ProviderBackend):
    provider = 'tianyan'
    framework = 'cqlib'
    api_key_hint = 'Check that the API key is a TianYan login key.'
    _API_KEY_MARKERS = ('unauthorized', 'login failed')
    _AVAILABLE_STATUS = {'running'}
    _SIMULATOR_NAMES = {
        'tianyan_sw', 'tianyan_sa', 'tianyan_s', 'tianyan_tn', 'tianyan_tnn', 'tianyan_swn',
    }
    _ROW_STATUS = _AVAILABLE_STATUS | {'calibration', 'under maintenance', 'off-line', 'unknown'}
    _ROW_IGNORE = _ROW_STATUS | {'free', 'paid', '未知状态'}

    @classmethod
    def _is_simulator(cls, name: str) -> bool:
        lowered = name.lower()
        prefix, separator, suffix = lowered.rpartition('_')
        return lowered in cls._SIMULATOR_NAMES or 'sim' in lowered or (
            separator == '_' and prefix.startswith('tianyan') and suffix.isalpha()
        )

    @classmethod
    def _computer(cls, row) -> tuple[str, str]:
        if isinstance(row, dict):
            name = row.get('machineName') or row.get('code') or row.get('name') or ''
            status = str(row.get('status', '')).lower()
            return str(name), status
        values = [str(item) for item in row]
        status = next((item.lower() for item in values if item.lower() in cls._ROW_STATUS), '')
        names = [item for item in values if item.lower() not in cls._ROW_IGNORE and not item.isdigit()]
        return (names[-1] if names else ''), status

    @staticmethod
    def _measure_cbits(circuit: CircuitIO) -> list[int]:
        cbits = []
        for name, _qubits, targets in circuit.get_gate_list():
            if name == 'M':
                cbits.extend(targets)
        return cbits

    @classmethod
    def _counts_from_shots(cls, shots, cbits: list[int], ncbits: int) -> dict[str, int]:
        counts = {}
        for shot in shots:
            outcomes = [str(bit) for bit in shot]
            if len(outcomes) != len(cbits):
                raise RunError('TianYan returned a measurement whose width does not match the circuit.')
            chars = ['0'] * ncbits
            for outcome, cbit in zip(outcomes, cbits):
                if outcome not in {'0', '1'}:
                    raise RunError(f'Invalid TianYan measurement bit: {outcome!r}')
                chars[cbit] = outcome
            bit = ''.join(chars)
            counts[bit] = counts.get(bit, 0) + 1
        return counts

    @classmethod
    def _counts_from_bitstrings(cls, values: dict, cbits: list[int], ncbits: int,
                                shots: int, probabilities: bool) -> dict[str, int]:
        """Place little-endian measurement strings onto classical-bit positions."""
        expanded = {}
        for raw_bit, raw_count in values.items():
            text = str(raw_bit).strip().replace(' ', '')
            if text.lower().startswith('0b'):
                text = text[2:]
            if len(text) != len(cbits) or set(text) - {'0', '1'}:
                raise RunError(f'Invalid TianYan measurement result: {raw_bit!r}')
            chars = ['0'] * ncbits
            for outcome, cbit in zip(reversed(text), cbits):
                chars[cbit] = outcome
            bit = ''.join(chars)
            count = round(raw_count * shots) if probabilities else int(raw_count)
            if count:
                expanded[bit] = expanded.get(bit, 0) + count
        return expanded

    def _counts(self, result: dict, circuit: CircuitIO, shots: int) -> dict[str, int]:
        cbits = self._measure_cbits(circuit)
        if not cbits:
            raise RunError('The circuit has no measurements to submit to TianYan.')
        status = result.get('resultStatus')
        if isinstance(status, str):
            status = json.loads(status)
        if status:
            return self._counts_from_shots(status[1:], cbits, circuit.get_ncbits())
        probability = result.get('probability')
        if isinstance(probability, str):
            probability = json.loads(probability)
        if isinstance(probability, dict) and probability:
            return self._counts_from_bitstrings(
                probability, cbits, circuit.get_ncbits(), shots, True
            )
        raise RunError(f"TianYan job {result.get('experimentTaskId', '')} returned no measurement results.")

    @staticmethod
    def _error_text(exc: BaseException):
        message = getattr(exc, 'message', None)
        return message if isinstance(message, str) and message else exc

    def _guard(self, action: str, exc: BaseException, hint: bool = False) -> RunError:
        text = self._error_text(exc)
        if self._api_key_failure(exc):
            return self._api_key_error(action, text)
        if hint:
            return RunError(f'{self.provider} could not {action}: {text}. {self.api_key_hint}')
        return RunError(f'{self.provider} could not {action}: {text}')

    def _platform(self):
        try:
            from cqlib import TianYanPlatform
        except ImportError as exc:
            raise RunError("Provider 'tianyan' requires cqlib. Please install Python package 'cqlib'.") from exc
        try:
            return TianYanPlatform(login_key=self.api_key)
        except Exception as exc:
            raise self._guard('log in', exc, hint=True) from exc

    def _machines(self, platform) -> list[tuple[str, str]]:
        try:
            rows = platform.query_quantum_computer_list()
        except Exception as exc:
            raise self._guard('list backends', exc, hint=True) from exc
        return [self._computer(row) for row in rows]

    def _run_local(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        try:
            from cqlib.simulator import StatevectorSimulator
        except ImportError as exc:
            raise RunError("Provider 'tianyan' requires cqlib. Please install Python package 'cqlib'.") from exc
        converted = _convert_circuit(circuit, self.framework, subsdict)
        cbits = self._measure_cbits(circuit)
        if not cbits:
            raise RunError('The circuit has no measurements.')
        try:
            raw = StatevectorSimulator(converted).sample(shots=shots)
        except Exception as exc:
            raise RunError(f'tianyan local simulator failed: {exc}') from exc
        counts = self._counts_from_bitstrings(raw, cbits, circuit.get_ncbits(), shots, False)
        return self._result(counts)

    def _map_qcis(self, platform, qcis: str) -> str:
        if self._is_simulator(self.backend) or self.options.get('transpile') is False:
            return qcis
        from cqlib.mapping import transpile_qcis
        try:
            mapped, _initial_layout, _swap_mapping, _final_layout = transpile_qcis(
                qcis,
                platform,
                initial_layout=self.options.get('initial_layout'),
                objective=self.options.get('mapping_objective', 'size'),
            )
        except Exception as exc:
            raise self._guard(f"map backend '{self.backend}'", exc) from exc
        return mapped.qcis

    def _run_cloud(self, circuit: CircuitIO, shots: int, subsdict: dict = None) -> RunResult:
        from cqlib import QuantumLanguage
        platform = self._platform()
        machines = self._machines(platform)
        available = [(name, status) for name, status in machines if name and status in self._AVAILABLE_STATUS]
        qpus = self._listed(name for name, _status in available if not self._is_simulator(name))
        simulators = self._listed(name for name, _status in available if self._is_simulator(name))
        if self.backend not in {name for name, _status in available}:
            raise self._invalid_backend(qpus, simulators)
        self._announce_cloud(qpus, simulators)
        converted = _convert_circuit(circuit, self.framework, subsdict)
        platform.set_machine(self.backend)
        qcis = self._map_qcis(platform, converted.qcis)
        try:
            query_ids = platform.submit_experiment(
                circuit=qcis,
                language=QuantumLanguage.QCIS,
                num_shots=shots,
                machine_name=self.backend,
                name='pyquantumkit',
            )
        except Exception as exc:
            raise self._guard(f"submit backend '{self.backend}'", exc) from exc
        if not query_ids:
            raise RunError(f"TianYan backend '{self.backend}' did not return a task id.")
        task_id = str(query_ids[0] if isinstance(query_ids, (list, tuple)) else query_ids)
        try:
            results = platform.query_experiment(
                task_id,
                max_wait_time=self.options.get('max_wait_time', 3600),
                sleep_time=self.options.get('sleep_time', 5),
            )
        except Exception as exc:
            raise self._guard(f"query job '{task_id}'", exc) from exc
        if not results:
            raise RunError(f'TianYan job {task_id} returned no measurement results.')
        counts = self._counts(results[0], circuit, shots)
        reported_id = results[0].get('experimentTaskId')
        return self._result(counts, str(reported_id or task_id))
    