from __future__ import annotations

import sys
from types import ModuleType

from pipeline.ocr.extract_parts import runtime


def test_engine_label_reports_coreml_when_the_onnx_session_uses_it() -> None:
    class Session:
        @staticmethod
        def get_providers() -> list[str]:
            return ["CoreMLExecutionProvider", "CPUExecutionProvider"]

    class Node:
        session = Session()

    class Engine:
        text_det = Node()
        text_cls = Node()
        text_rec = Node()

    assert runtime.engine_device_label(Engine()) == "CoreML"


def test_rapidocr_inserts_coreml_before_cpu_when_provider_is_available(monkeypatch) -> None:
    class FakeOrtInferSession:
        def __init__(self) -> None:
            self.had_providers = ["CoreMLExecutionProvider", "CPUExecutionProvider"]

        def _get_ep_list(self) -> list[tuple[str, dict[str, str]]]:
            return [("CPUExecutionProvider", {})]

    package = ModuleType("rapidocr_onnxruntime")
    utils = ModuleType("rapidocr_onnxruntime.utils")
    infer_engine = ModuleType("rapidocr_onnxruntime.utils.infer_engine")
    infer_engine.OrtInferSession = FakeOrtInferSession
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", package)
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime.utils", utils)
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime.utils.infer_engine", infer_engine)

    runtime._patch_rapidocr_onnxruntime_ep()

    providers = FakeOrtInferSession()._get_ep_list()
    assert providers[0][0] == "CoreMLExecutionProvider"
    assert providers[1][0] == "CPUExecutionProvider"
