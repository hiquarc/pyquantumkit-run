import importlib
from pyquantumkit import CircuitIO, new_circuit, new_mixed_circuit
from pqk_run import RunError, _load_framework

# Convert CircuitIO object into circuit object on the concrete framework
def _convert_circuit(circuit: CircuitIO, framework: str, subsdict: dict = None):
    if not circuit.check_nqbits():
        raise RunError('The circuit uses more qubits than declared.')
    if not circuit.check_ncbits():
        raise RunError('The circuit uses more classical bits than declared.')
    _load_framework(framework)
    if circuit.get_ncbits() > 0:
        converted = new_mixed_circuit(framework, circuit.get_nqbits(), circuit.get_ncbits())
    else:
        converted = new_circuit(framework, circuit.get_nqbits())
    circuit.append_into_actual_circuit(converted, subsdict)
    return converted
