from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from importlib import import_module

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


MODULES = ["torch", "ultralytics", "cv2", "yaml", "pandas", "matplotlib", "seaborn"]


def import_status() -> dict[str, str]:
    results: dict[str, str] = {}
    for name in MODULES:
        try:
            module = import_module(name)
            version = getattr(module, "__version__", "unknown")
            results[name] = f"ok ({version})"
        except Exception as exc:  # pragma: no cover - diagnostic path
            results[name] = f"failed ({exc})"
    return results


def get_nvidia_smi_output() -> str:
    binary = shutil.which("nvidia-smi")
    if not binary:
        return "nvidia-smi not found"

    try:
        completed = subprocess.run(
            [binary],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:  # pragma: no cover - diagnostic path
        return f"nvidia-smi failed to run: {exc}"

    output = (completed.stdout or completed.stderr).strip()
    if completed.returncode != 0:
        return f"nvidia-smi exited with code {completed.returncode}: {output}"
    return output or "nvidia-smi returned no output"


def get_torch_cuda_info() -> dict[str, str]:
    try:
        import torch
    except Exception as exc:  # pragma: no cover - diagnostic path
        return {"torch_error": str(exc)}

    info = {
        "torch_version": torch.__version__,
        "cuda_available": str(torch.cuda.is_available()),
        "torch_cuda_version": str(torch.version.cuda),
        "device_count": str(torch.cuda.device_count()),
    }

    if torch.cuda.is_available() and torch.cuda.device_count() > 0:
        device_name = torch.cuda.get_device_name(0)
        memory_bytes = torch.cuda.get_device_properties(0).total_memory
        info["device_0_name"] = device_name
        info["device_0_total_memory_gb"] = f"{memory_bytes / (1024 ** 3):.2f}"
    else:
        info["device_0_name"] = "unavailable"
        info["device_0_total_memory_gb"] = "unavailable"

    return info


def main() -> None:
    print("== System ==")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Platform: {platform.platform()}")
    print()

    print("== Imports ==")
    for module_name, status in import_status().items():
        print(f"{module_name}: {status}")
    print()

    print("== Torch / CUDA ==")
    for key, value in get_torch_cuda_info().items():
        print(f"{key}: {value}")
    print()

    print("== nvidia-smi ==")
    print(get_nvidia_smi_output())
    print()
    print("Note:")
    print("If this script is run inside a restricted tool or sandbox, GPU access may differ")
    print("from your interactive terminal. Prefer the interactive terminal result for training.")


if __name__ == "__main__":
    main()
