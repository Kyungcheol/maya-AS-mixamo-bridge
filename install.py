from __future__ import annotations

import shutil
from pathlib import Path


def install(
    destination: str | Path | None = None, *, create_shelf: bool = True
) -> Path:
    """Install the package into Maya's user scripts directory."""
    source = Path(__file__).resolve().parent / "src" / "as_mixamo_bridge"
    if destination is None:
        try:
            import maya.cmds as cmds
        except ImportError as exc:
            raise RuntimeError(
                "Run install.py inside Maya, or pass an explicit destination"
            ) from exc
        destination_path = Path(cmds.internalVar(userScriptDir=True))
    else:
        destination_path = Path(destination)
    target = destination_path / "as_mixamo_bridge"
    destination_path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    if create_shelf:
        _create_shelf_button()
    return target


def _create_shelf_button() -> None:
    import maya.cmds as cmds
    import maya.mel as mel

    shelf = mel.eval("$tmp=$gShelfTopLevel")
    current = cmds.tabLayout(shelf, query=True, selectTab=True)
    command = "import as_mixamo_bridge.ui as ui; ui.show()"
    existing = cmds.shelfLayout(current, query=True, childArray=True) or []
    for item in existing:
        if cmds.shelfButton(item, query=True, exists=True):
            if cmds.shelfButton(item, query=True, command=True) == command:
                return
    cmds.shelfButton(
        parent=current,
        label="AS Mixamo",
        annotation="Open AS–Mixamo Bridge",
        image1="commandButton.png",
        command=command,
        sourceType="python",
    )


if __name__ == "__main__":
    print(f"Installed AS–Mixamo Bridge to {install()}")
