from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("maya.cmds")
pytest.importorskip("PySide6")

from PySide6 import QtWidgets

from as_mixamo_bridge.models import ValidationIssue, ValidationReport
from as_mixamo_bridge.ui import BridgeWindow


class FakeController:
    def enter_work_mode(self, selected):
        return None

    def apply_mixamo_animation(self, source_path, selected):
        return None

    def bake_to_as(self, selected):
        return None

    def restore_pre_conversion(self, selected):
        return None


class FakeServices:
    def __init__(self):
        self.timing_mode = None
        self.change_scene_fps_to_source = False
        self.last_source_fps = 24.0
        self.last_source_time_unit = "film"


class TimingController(FakeController):
    def __init__(self):
        self.services = FakeServices()
        self.change_flag_during_apply = None

    def apply_mixamo_animation(self, source_path, selected):
        self.change_flag_during_apply = self.services.change_scene_fps_to_source
        return object()


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_window_has_primary_actions_collapsed_advanced_and_safe_disabled_state(app):
    window = BridgeWindow(
        controller=FakeController(), selection_provider=lambda: []
    )

    assert window.findChild(QtWidgets.QLabel, "characterStatus") is not None
    for name in ("workModeButton", "applyButton", "bakeButton", "restoreButton"):
        button = window.findChild(QtWidgets.QPushButton, name)
        assert button is not None
        assert not button.isEnabled()
    advanced = window.findChild(QtWidgets.QGroupBox, "advancedGroup")
    assert advanced is not None
    assert advanced.isCheckable()
    assert not advanced.isChecked()
    assert window.findChild(QtWidgets.QComboBox, "timingModeCombo") is not None
    assert window.findChild(QtWidgets.QCheckBox, "changeSceneFpsCheck") is not None
    window.close()


def test_failed_validation_lists_issues_and_navigates_to_frame(app):
    visited = []
    window = BridgeWindow(
        controller=FakeController(),
        selection_provider=lambda: ["|Character|RootX_M"],
        frame_navigator=visited.append,
    )
    issue = ValidationIssue(
        "position", "left_foot", 1042.0, 0.25, 0.1, "left foot drift"
    )

    window.show_validation(ValidationReport((issue,)))

    tree = window.findChild(QtWidgets.QTreeWidget, "validationTree")
    assert tree is not None and tree.topLevelItemCount() == 1
    tree.setCurrentItem(tree.topLevelItem(0))
    window.navigate_to_selected_issue()
    assert visited == [1042.0]
    assert "FAILED" in window.validation_label.text()
    window.close()


def test_explicit_fps_change_is_confirmed_before_animation_apply(app, monkeypatch):
    controller = TimingController()
    window = BridgeWindow(
        controller=controller,
        selection_provider=lambda: ["|Character|RootX_M"],
    )
    window.change_fps_check.setChecked(True)
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("C:/animation.fbx", "Animation"),
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: QtWidgets.QMessageBox.StandardButton.Yes,
    )

    window._apply_animation()

    assert controller.change_flag_during_apply is True
    window.close()
