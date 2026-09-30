"""Runs Piper's ONNX export with the TorchScript based exporter.

Recent PyTorch defaults ``torch.onnx.export`` to the dynamo exporter, which needs onnxscript and
does not handle the VITS graph of Piper; the upstream script does not pick an exporter itself.
"""
from __future__ import annotations

import functools

import torch


def main() -> None:
    torch.onnx.export = functools.partial(torch.onnx.export, dynamo=False)
    from piper.train import export_onnx

    export_onnx.main()


if __name__ == "__main__":
    main()
