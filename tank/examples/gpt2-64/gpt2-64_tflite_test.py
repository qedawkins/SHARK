import numpy as np
from shark.shark_downloader import download_tflite_model
from shark.shark_inference import SharkInference
import pytest
import unittest
from shark.parser import shark_args


# model_path = "https://s3.amazonaws.com/models.huggingface.co/bert/gpt2-64.tflite"


def generate_inputs(input_details):
    args = []
    args.append(
        np.random.randint(
            low=0,
            high=256,
            size=input_details[0]["shape"],
            dtype=input_details[0]["dtype"],
        )
    )
    return args


def compare_results(mlir_results, tflite_results):
    print("Compare mlir_results VS tflite_results: ")
    assert len(mlir_results) == len(
        tflite_results
    ), "Number of results do not match"
    for i in range(len(mlir_results)):
        mlir_result = mlir_results[i]
        tflite_result = tflite_results[i]
        mlir_result = mlir_result.astype(np.single)
        tflite_result = tflite_result.astype(np.single)
        # mlir_result = np.expand_dims(mlir_result, axis=0)
        print("mlir_result.shape", mlir_result.shape)
        print("tflite_result.shape", tflite_result.shape)
        assert mlir_result.shape == tflite_result.shape, "shape doesnot match"
        max_error = np.max(np.abs(mlir_result - tflite_result))
        print("Max error (%d): %f", i, max_error)


class GptTfliteModuleTester:
    def __init__(
        self,
        dynamic=False,
        device="cpu",
        save_mlir=False,
        save_vmfb=False,
    ):
        self.dynamic = dynamic
        self.device = device
        self.save_mlir = save_mlir
        self.save_vmfb = save_vmfb

    def create_and_check_module(self):
        shark_args.save_mlir = self.save_mlir
        shark_args.save_vmfb = self.save_vmfb

        # Preprocess to get SharkImporter input args
        mlir_model, func_name, inputs, tflite_results = download_tflite_model(
            model_name="gpt2-64"
        )
        shark_module = SharkInference(
            mlir_module=mlir_model,
            function_name="main",
            device=self.device,
            mlir_dialect="tflite",
        )

        # Case1: Use shark_importer default generate inputs
        shark_module.compile()
        mlir_results = shark_module.forward(inputs)
        compare_results(mlir_results, tflite_results)

        # Case2: Use manually set inputs
        input_details = [
            {
                "shape": [1, 64],
                "dtype": np.int32,
            }
        ]
        inputs = generate_inputs(input_details)  # new inputs

        shark_module = SharkInference(
            mlir_module=mlir_model,
            function_name="main",
            device=self.device,
            mlir_dialect="tflite",
        )
        shark_module.compile()
        mlir_results = shark_module.forward(inputs)
        compare_results(mlir_results, tflite_results)
        # print(mlir_results)


class GptTfliteModuleTest(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def configure(self, pytestconfig):
        self.save_mlir = pytestconfig.getoption("save_mlir")
        self.save_vmfb = pytestconfig.getoption("save_vmfb")

    def setUp(self):
        self.module_tester = GptTfliteModuleTester(self)
        self.module_tester.save_mlir = self.save_mlir

    def test_module_static_cpu(self):
        self.module_tester.dynamic = False
        self.module_tester.device = "cpu"
        self.module_tester.create_and_check_module()


if __name__ == "__main__":
    # module_tester = GptTfliteModuleTester()
    # module_tester.save_mlir = True
    # module_tester.save_vmfb = True
    # module_tester.create_and_check_module()

    unittest.main()
