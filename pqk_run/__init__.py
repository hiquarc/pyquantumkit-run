# __init__.py
#    2026/11/23
#    Author: Peixun Long
#    Computing Center, Institute of High Energy Physics, CAS

__version__ = '0.0.1'
import importlib
from pyquantumkit import Supported_Frameworks, Framework_Namespace

class RunError(Exception):
    pass

def _load_framework(framework: str) -> None:
    for module_name in Supported_Frameworks[framework]:
        if module_name not in Framework_Namespace[framework]:
            try:
                Framework_Namespace[framework][module_name] = importlib.import_module(module_name)
            except ImportError as exc:
                raise RunError(
                    f"Provider requires Python module '{module_name}'. "
                    f"Install the corresponding PyQuantumKit optional dependency."
                ) from exc

from pqk_run.executor import run
