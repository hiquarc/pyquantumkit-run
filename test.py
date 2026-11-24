from pqk_run import run
from pyquantumkit import QProgramBuilder
from pyquantumkit.program.std import *
from pyquantumkit.program.quint import *

def qmain(builder : QProgramBuilder):
    qnum1 = QuInt(3, 'qnum1')
    qnum2 = QuInt(3, 'qnum2')
    builder.declare_qvars(qnum1, qnum2)

    qnum1.create_two_value_superposition(0, 7)
    qnum2.create_two_value_superposition(1, 6)

    builder.measure_all()

prog = QProgramBuilder()
prog.build(qmain)

result = run(prog)
print(result.counts)
print(result.interpreted)
# 解读的结果 (qnum1,qnum2) 应为 (0,1) (0,6) (7,1) (7,6) 四种组合
#   如果出现数字3和4，说明protocol的设定不正确
