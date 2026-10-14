from __future__ import annotations

import traceback
from typing import Any, Callable, Sequence

from PySide6 import QtCore, QtWidgets

from .commands import BridgeController, MayaBridgeServices
from .models import TimingMode, ValidationReport


SelectionProvider = Callable[[], Sequence[str]]
FrameNavigator = Callable[[float], None]


class BridgeWindow(QtWidgets.QDialog):
    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        *,
        controller: Any | None = None,
        selection_provider: SelectionProvider | None = None,
        frame_navigator: FrameNavigator | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller or BridgeController(MayaBridgeServices())
        self.selection_provider = selection_provider or self._maya_selection
        self.frame_navigator = frame_navigator or self._maya_set_frame
        self.setObjectName("asMixamoBridgeWindow")
        self.setWindowTitle("AS–Mixamo Bridge")
        self.setMinimumWidth(390)
        self.setWindowFlag(QtCore.Qt.WindowType.Tool, True)
        self._build_ui()
        self.refresh_selection()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        self.status_label = QtWidgets.QLabel("Select an AdvancedSkeleton character")
        self.status_label.setObjectName("characterStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.work_button = self._button("Mixamo Work Mode", "workModeButton")
        self.apply_button = self._button("Apply Mixamo Animation…", "applyButton")
        self.bake_button = self._button("Bake to AS", "bakeButton")
        self.restore_button = self._button(
            "Restore Pre-Conversion State", "restoreButton"
        )
        for button in (
            self.work_button,
            self.apply_button,
            self.bake_button,
            self.restore_button,
        ):
            layout.addWidget(button)

        self.work_button.clicked.connect(self._enter_work_mode)
        self.apply_button.clicked.connect(self._apply_animation)
        self.bake_button.clicked.connect(self._bake)
        self.restore_button.clicked.connect(self._restore)

        self.validation_label = QtWidgets.QLabel("Validation: not run")
        self.validation_label.setObjectName("validationStatus")
        layout.addWidget(self.validation_label)
        self.validation_tree = QtWidgets.QTreeWidget()
        self.validation_tree.setObjectName("validationTree")
        self.validation_tree.setHeaderLabels(
            ["Frame", "Part", "Check", "Measured", "Limit"]
        )
        self.validation_tree.setVisible(False)
        self.validation_tree.itemDoubleClicked.connect(
            lambda *_: self.navigate_to_selected_issue()
        )
        layout.addWidget(self.validation_tree)

        advanced = QtWidgets.QGroupBox("Advanced timing / FPS")
        advanced.setObjectName("advancedGroup")
        advanced.setCheckable(True)
        advanced.setChecked(False)
        advanced_layout = QtWidgets.QFormLayout(advanced)
        self.advanced_body = QtWidgets.QWidget()
        body_layout = QtWidgets.QFormLayout(self.advanced_body)
        self.timing_combo = QtWidgets.QComboBox()
        self.timing_combo.setObjectName("timingModeCombo")
        self.timing_combo.addItem("Preserve source frame numbers", "preserve_frame_numbers")
        self.timing_combo.addItem("Preserve playback duration", "preserve_playback_duration")
        self.source_fps_label = QtWidgets.QLabel("Detected when animation is loaded")
        self.target_fps_label = QtWidgets.QLabel(self._current_fps_text())
        self.change_fps_check = QtWidgets.QCheckBox(
            "Change scene FPS explicitly (confirmation required)"
        )
        self.change_fps_check.setObjectName("changeSceneFpsCheck")
        body_layout.addRow("Timing", self.timing_combo)
        body_layout.addRow("Source FPS", self.source_fps_label)
        body_layout.addRow("Scene FPS", self.target_fps_label)
        body_layout.addRow(self.change_fps_check)
        advanced_layout.addRow(self.advanced_body)
        self.advanced_body.setVisible(False)
        advanced.toggled.connect(self.advanced_body.setVisible)
        layout.addWidget(advanced)

        refresh = QtWidgets.QPushButton("Refresh Selection")
        refresh.clicked.connect(self.refresh_selection)
        layout.addWidget(refresh)

    @staticmethod
    def _button(label: str, object_name: str) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(label)
        button.setObjectName(object_name)
        return button

    @staticmethod
    def _maya_selection() -> Sequence[str]:
        import maya.cmds as cmds

        return cmds.ls(selection=True, long=True) or []

    @staticmethod
    def _maya_set_frame(frame: float) -> None:
        import maya.cmds as cmds

        cmds.currentTime(frame, edit=True)

    @staticmethod
    def _current_fps_text() -> str:
        try:
            import maya.cmds as cmds

            return str(cmds.currentUnit(query=True, time=True))
        except Exception:
            return "Unavailable"

    def _selected(self) -> str:
        selection = list(self.selection_provider())
        return selection[0] if selection else ""

    @QtCore.Slot()
    def refresh_selection(self) -> None:
        selected = self._selected()
        enabled = bool(selected)
        for button in (
            self.work_button,
            self.apply_button,
            self.bake_button,
            self.restore_button,
        ):
            button.setEnabled(enabled)
        self.status_label.setText(
            f"Selected: {selected}" if selected else "Select an AdvancedSkeleton character"
        )

    def _run(self, operation: Callable[[], Any], success: str) -> Any | None:
        try:
            result = operation()
            self.status_label.setText(success)
            return result
        except Exception as exc:
            traceback.print_exc()
            self.status_label.setText(f"Error: {exc}")
            QtWidgets.QMessageBox.critical(self, "AS–Mixamo Bridge", str(exc))
            return None

    @QtCore.Slot()
    def _enter_work_mode(self) -> None:
        self._run(
            lambda: self.controller.enter_work_mode(self._selected()),
            "Mixamo Work Mode is active",
        )

    @QtCore.Slot()
    def _apply_animation(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose Mixamo animation or studio rig",
            "",
            "Animation (*.fbx *.mb *.ma);;All files (*)",
        )
        if not path:
            return
        services = getattr(self.controller, "services", None)
        if services is not None and hasattr(services, "timing_mode"):
            services.timing_mode = TimingMode(self.timing_combo.currentData())
        if services is not None and hasattr(services, "change_scene_fps_to_source"):
            change_fps = False
            if self.change_fps_check.isChecked():
                answer = QtWidgets.QMessageBox.question(
                    self,
                    "Change scene FPS?",
                    "After detecting the source FPS, change the Maya scene FPS before transferring keys? Key frame numbers will stay unchanged.",
                )
                change_fps = answer == QtWidgets.QMessageBox.StandardButton.Yes
            services.change_scene_fps_to_source = change_fps
        result = self._run(
            lambda: self.controller.apply_mixamo_animation(path, self._selected()),
            "Mixamo animation applied; inspect the adapter before baking",
        )
        if result is None or services is None:
            return
        source_fps = getattr(services, "last_source_fps", None)
        if source_fps is not None:
            self.source_fps_label.setText(f"{source_fps:g} fps")
        source_unit = getattr(services, "last_source_time_unit", None)
        if (
            source_unit
            and getattr(services, "change_scene_fps_to_source", False)
        ):
            self.target_fps_label.setText(str(source_unit))

    @QtCore.Slot()
    def _bake(self) -> None:
        result = self._run(
            lambda: self.controller.bake_to_as(self._selected()),
            "AS bake finished",
        )
        if result is not None:
            self.show_validation(result.validation)

    @QtCore.Slot()
    def _restore(self) -> None:
        result = self._run(
            lambda: self.controller.restore_pre_conversion(self._selected()),
            "Pre-conversion state restored",
        )
        if result is not None:
            self.validation_tree.clear()
            self.validation_tree.setVisible(False)
            self.validation_label.setText("Validation: restored")

    def show_validation(self, report: ValidationReport) -> None:
        self.validation_tree.clear()
        if report.passed:
            self.validation_label.setText("Validation: PASSED")
            self.validation_tree.setVisible(False)
            return
        self.validation_label.setText(
            f"Validation: FAILED ({len(report.issues)} issue(s))"
        )
        for issue in report.issues:
            item = QtWidgets.QTreeWidgetItem(
                [
                    f"{issue.frame:g}", issue.body_part, issue.category,
                    f"{issue.measured:.6g}", f"{issue.tolerance:.6g}",
                ]
            )
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, float(issue.frame))
            item.setToolTip(0, issue.message)
            self.validation_tree.addTopLevelItem(item)
        self.validation_tree.setVisible(True)

    @QtCore.Slot()
    def navigate_to_selected_issue(self) -> None:
        item = self.validation_tree.currentItem()
        if item is None:
            return
        frame = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if frame is not None:
            self.frame_navigator(float(frame))


_window: BridgeWindow | None = None


def show() -> BridgeWindow:
    global _window
    if _window is not None:
        _window.close()
        _window.deleteLater()
    _window = BridgeWindow()
    _window.show()
    _window.raise_()
    _window.activateWindow()
    return _window
