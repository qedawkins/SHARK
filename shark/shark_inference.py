# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from shark.iree_utils.compile_utils import (
    export_iree_module_to_vmfb,
    load_flatbuffer,
)
import os
from shark.shark_runner import SharkRunner
from shark.parser import shark_args
import numpy as np


dtype_to_np_dtype = {
    "f32": np.float32,
    "f64": np.float64,
    "i32": np.int32,
    "i64": np.int64,
    "i1": np.bool_,
}


class SharkInference:
    """
    Runs prediction or inference on mlir_module.

    ...

    Attributes
    ----------
    mlir_module : str
        mlir_module represented in string.
    function_name : str
        function to execute in the given mlir_module.
    device : str
        device to execute the mlir_module on.
        currently supports cpu, cuda, vulkan, and metal backends.
    mlir_dialect: str
        The dialect in which the given mlir_module is in.
        Refer to {https://mlir.llvm.org/docs/Dialects/}
    is_benchmark: bool
        Whether this SharkInference module should be benchmark-enabled.

    Methods
    -------
    run(inputs=None):
        Runs the mlir_module with the given inputs, if the inputs are not
        given it autogenerates the inputs. Also, the inputs should be a
        numpy array.
    input_info():
        Gives the information about the inputs required by the `function_name`.
        This can be expensive as it does string matching to do so.

    """

    def __init__(
        self,
        mlir_module: str,
        function_name: str = "forward",
        device: str = "none",
        mlir_dialect: str = "linalg",
        is_benchmark: bool = False,
    ):
        self.mlir_module = mlir_module
        self.function_name = function_name
        self.device = shark_args.device if device == "none" else device
        self.mlir_dialect = mlir_dialect
        self.is_benchmark = is_benchmark

        self.shark_runner = None

    def compile(self):

        if self.is_benchmark == True:
            from shark.shark_benchmark_runner import SharkBenchmarkRunner

            self.shark_runner = SharkBenchmarkRunner(
                self.mlir_module,
                self.function_name,
                self.device,
                self.mlir_dialect,
            )

        else:
            self.shark_runner = SharkRunner(
                self.mlir_module,
                self.function_name,
                self.device,
                self.mlir_dialect,
            )

    # inputs are considered to be tuple of np.array.
    def forward(self, inputs: tuple):
        return self.shark_runner.run(inputs)

    # Captures the static input information from the mlir_module.
    # TODO(pashu123): Generate the input information for dynamic shapes.
    def _input_info(self):
        # func_key to get the line which contains the function.
        func_key = "func.func @" + self.function_name
        func_header = None
        for line in str(self.mlir_module).splitlines():
            if func_key in line:
                func_header = line
                break
        if func_header is None:
            print(f"Function: {self.function_name} not found")

        import re

        inputs = re.findall("\(.*?\)", func_header)[0].split(",")
        shapes = []
        dtype = []
        for inp in inputs:
            shape_dtype = re.findall(r"<[^>]*>", inp)[0].split("x")
            shape_dtype[0], shape_dtype[-1] = (
                shape_dtype[0][1:],
                shape_dtype[-1][:-1],
            )
            shapes.append(tuple([int(x) for x in shape_dtype[:-1]]))
            dtype.append(shape_dtype[-1])

        return shapes, dtype

    # Generates random input to be feed into the graph.
    def generate_random_inputs(self, low=0, high=1):
        shapes, dtype = self._input_info()
        inputs = []
        for i, j in zip(shapes, dtype):
            inputs.append(
                np.random.uniform(low, high, size=i).astype(
                    dtype_to_np_dtype[j]
                )
            )
        return tuple(inputs)

    # TODO: Instead of passing directory and having names decided by the module
    # , user may want to save the module with manual names.
    def save_module(self, dir=os.getcwd()):
        return export_iree_module_to_vmfb(
            self.mlir_module,
            self.device,
            dir,
            self.mlir_dialect,
            self.function_name,
        )

    # load and return the module.
    def load_module(self, path):
        self.shark_runner = SharkRunner(
            function_name=self.function_name,
            device=self.device,
            compile_vmfb=False,
        )
        (
            self.shark_runner.iree_compilation_module,
            self.shark_runner.iree_config,
        ) = load_flatbuffer(
            path,
            self.device,
            self.function_name,
        )
        return
