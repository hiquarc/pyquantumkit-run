# pyquantumkit-run
A cross-platform executor for quantum circuits and programs written by PyQuantumKit, supporting mainstream quantum cloud platforms.

## 一次编写，到处运行

pyquantumkit-run提供了统一的`run()`方法。运行时会读取命令行中的`-provider`、`-backend`和`-shots`等参数，因此切换本地模拟器或量子真机不需要修改程序：

```python
import pyquantumkit as PQK
from pqk_run import run

circuit = PQK.CircuitIO(2, 2)
PQK.apply_gate(circuit, 'H', [0])
PQK.apply_gate(circuit, 'CX', [0, 1])
PQK.apply_measure(circuit, [0, 1], [0, 1])

result = run(circuit)
print(result.counts)
```

使用Qiskit或Quafu本地模拟器运行：

```sh
python test.py -provider qiskit -backend local -shots 1024
python test.py -provider quafu -backend local -shots 1024
```

使用本源量子或Quafu云平台时，先设置`PK_API_KEY`，再指定提供商和量子真机名称：

```sh
export PK_API_KEY=xxx
python test.py -provider originq -backend WK_C180
python test.py -provider quafu -backend Shenglian
```

也可以通过`-api-key-file <路径>`读取密钥文件。提交云端任务前，程序会调用相应平台的API查询当前可用设备；如果`-backend`指定的名称不存在，会报告错误并列出可用名称，不会提交任务。

执行`python test.py -h`可以查看所有运行参数，也可以在代码中显式传入`provider`、`backend`、`shots`、`api_key`和`api_key_file`；显式参数优先于命令行参数。
