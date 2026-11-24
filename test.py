import pyquantumkit as PQK
from pqk_run import run

circuit = PQK.CircuitIO(2, 2)
PQK.apply_gate(circuit, 'H', [0])
PQK.apply_gate(circuit, 'CX', [0, 1])
PQK.apply_measure(circuit, [0, 1], [0, 1])

result = run(circuit)
print(result.counts)
