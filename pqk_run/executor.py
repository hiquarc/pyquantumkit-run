import argparse
import os
import sys
from pyquantumkit import CircuitIO, QProgramBuilder
from pqk_run import RunError
from pqk_run.result import RunResult

from pqk_run.platforms.originq import OriginQBackend
from pqk_run.platforms.qiskit import QiskitBackend
from pqk_run.platforms.quafu import QuafuBackend
from pqk_run.platforms.tianyan import TianYanBackend

def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='PyQuantumKit quantum circuit execution options.',
        allow_abbrev=False,
    )
    parser.add_argument('-provider', '--provider', default='qiskit',
                        help='execution provider: qiskit, originq, quafu, or tianyan (default: qiskit)')
    parser.add_argument('-backend', '--backend', default=None,
                        help='local simulator or cloud device name; cloud names are validated by the provider API')
    parser.add_argument('-shots', '--shots', type=int, default=1024,
                        help='number of measurement repetitions (default: 1024)')
    parser.add_argument('-api-key-file', '--api-key-file', default=None,
                        help='read the cloud API key from this file when PK_API_KEY is not set')
    return parser


def _cli_options() -> argparse.Namespace:
    args, _ = _argument_parser().parse_known_args(sys.argv[1:])
    return args

_BACKEND_CLASSES = {
    'qiskit': QiskitBackend,
    'originq': OriginQBackend,
    'quafu': QuafuBackend,
    'tianyan': TianYanBackend,
}


# Peixun: 我对run函数进行了修改
#   第一个参数名改为runnable，表示量子线路或量子程序
def run(runnable: CircuitIO|QProgramBuilder,
        provider: str = None, backend: str = None, shots: int = None,
        api_key: str = None, api_key_file: str = None, subsdict: dict = None,
        options: dict = None) -> RunResult:
    """Run a CircuitIO or QProgramBuilder on the selected local or cloud backend."""

    # CircuitIO对象：运行返回结果
    if isinstance(runnable, CircuitIO):
        args = _cli_options()
        provider = (provider or args.provider).lower()
        if provider not in _BACKEND_CLASSES:
            supported = ', '.join(_BACKEND_CLASSES)
            raise RunError(f"Unsupported provider '{provider}'. Available providers: {supported}.")
        backend = backend if backend is not None else args.backend
        shots = shots if shots is not None else args.shots
        if isinstance(shots, bool) or not isinstance(shots, int) or shots <= 0:
            raise RunError('shots must be a positive integer.')
        api_key_file = api_key_file or args.api_key_file
        if api_key_file is not None:
            options = dict(options or {})
            options['api_key_file'] = api_key_file
        backend_impl = _BACKEND_CLASSES[provider](backend, api_key, options)
        return backend_impl.run(runnable, shots, subsdict)

    # QProgramBuilder对象：提取出其中的量子线路运行，再解读运行的结果返回
    if isinstance(runnable, QProgramBuilder):
        result = run(runnable.get_built_circuit(),
            provider, backend, shots, api_key, api_key_file, subsdict, options
        )
        result.interpreted = runnable.interpret_result_dict(result.counts, result.protocol)
        return result
    
    else:
        raise TypeError('run() expects a CircuitIO or QProgramBuilder object.')

    