from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_installer():
    path = Path(__file__).parents[2] / "install.py"
    spec = importlib.util.spec_from_file_location("asmb_installer", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installer_copies_package_without_requiring_maya(tmp_path):
    installer = _load_installer()

    installed = installer.install(destination=tmp_path, create_shelf=False)

    assert installed == tmp_path / "as_mixamo_bridge"
    assert (installed / "ui.py").is_file()
    assert (installed / "profiles" / "as_belato01_v1.json").is_file()
