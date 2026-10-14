from __future__ import annotations

import pytest

from as_mixamo_bridge.commands import (
    BakeResult,
    BridgeController,
    ControlPolicy,
    UserCancelled,
)
from as_mixamo_bridge.models import CharacterContext, RestoreReport, ValidationIssue, ValidationReport


class FakeTransaction:
    def __init__(self):
        self.restored = False

    def restore(self):
        self.restored = True
        return RestoreReport(True)


class FakeServices:
    def __init__(self):
        self.calls = []
        self.cancel = False
        self.validation = ValidationReport()
        self.transactions = []
        self.apply_error = None
        self.bake_error = None

    def detect(self, selected):
        self.calls.append(("detect", selected))
        return CharacterContext("|Character", "as_belato01_v1")

    def begin(self, context):
        tx = FakeTransaction()
        self.transactions.append(tx)
        return tx

    def create_adapter(self, context, transaction):
        self.calls.append(("adapter", context.root))
        if self.cancel:
            raise UserCancelled("cancelled")
        return {"root": "ASMB_Adapter"}

    def apply_animation(self, session, source_path, policy):
        self.calls.append(("apply", source_path, policy))
        if self.apply_error:
            raise self.apply_error
        return "studio" if source_path is None else "raw_fbx"

    def bake(self, session):
        self.calls.append(("bake", session.context.root))
        if self.bake_error:
            raise self.bake_error
        return BakeResult("ASMB_Output", self.validation)


def test_enter_work_mode_creates_one_active_session():
    """Catches duplicate live adapters for one AS character."""
    services = FakeServices()
    controller = BridgeController(services)
    first = controller.enter_work_mode("|Character|mesh")
    second = controller.enter_work_mode("|Character|mesh")
    assert first is second
    assert services.calls.count(("adapter", "|Character")) == 1


def test_cancel_restores_transaction_and_leaves_no_session():
    """Catches cancellation leaving temporary adapter data behind."""
    services = FakeServices()
    services.cancel = True
    controller = BridgeController(services)
    with pytest.raises(UserCancelled):
        controller.enter_work_mode("mesh")
    assert services.transactions[0].restored
    assert not controller.sessions


def test_raw_fbx_uses_declared_leg_ik_arm_fk_default():
    """Catches inventing switch semantics not present in a joint-only FBX."""
    services = FakeServices()
    controller = BridgeController(services)
    controller.enter_work_mode("mesh")
    result = controller.apply_mixamo_animation("walk.fbx", "mesh")
    assert result.source_kind == "raw_fbx"
    assert services.calls[-1] == (
        "apply", "walk.fbx", ControlPolicy(arms="fk", legs="ik")
    )


def test_studio_source_preserves_explicit_control_semantics():
    """Catches applying raw-FBX defaults to a studio control rig with authored switches."""
    services = FakeServices()
    controller = BridgeController(services)
    controller.enter_work_mode("mesh")
    result = controller.apply_mixamo_animation(None, "mesh")
    assert result.source_kind == "studio"
    assert services.calls[-1][2] is None


def test_failed_validation_keeps_session_and_never_claims_success():
    """Catches cleanup or success reporting after a failed deformation comparison."""
    services = FakeServices()
    services.validation = ValidationReport(
        (ValidationIssue("position", "left_foot", 10, 1.0, 0.1, "bad foot"),)
    )
    controller = BridgeController(services)
    controller.enter_work_mode("mesh")
    result = controller.bake_to_as("mesh")
    assert not result.validation.passed
    assert "|Character" in controller.sessions


def test_restore_removes_session_and_allows_clean_retry():
    """Catches stale in-memory session state blocking a second conversion."""
    services = FakeServices()
    controller = BridgeController(services)
    first = controller.enter_work_mode("mesh")
    report = controller.restore_pre_conversion("mesh")
    second = controller.enter_work_mode("mesh")
    assert report.restored
    assert first is not second
    assert len(services.transactions) == 2


def test_successful_bake_remains_explicitly_restorable():
    """Catches a successful bake discarding the user's Restore checkpoint."""
    services = FakeServices()
    controller = BridgeController(services)
    controller.enter_work_mode("mesh")

    result = controller.bake_to_as("mesh")

    assert result.validation.passed
    assert "|Character" in controller.sessions
    assert controller.restore_pre_conversion("mesh").restored


def test_failed_source_application_restores_and_removes_session():
    """Catches an FBX import error leaving a live adapter or stale controller state."""
    services = FakeServices()
    services.apply_error = RuntimeError("bad FBX")
    controller = BridgeController(services)

    with pytest.raises(RuntimeError, match="bad FBX"):
        controller.apply_mixamo_animation("bad.fbx", "mesh")

    assert services.transactions[0].restored
    assert not controller.sessions


def test_bake_exception_restores_and_removes_session():
    """Catches a Maya bake error leaving a live transaction and stale adapter."""
    services = FakeServices()
    services.bake_error = RuntimeError("bake failed")
    controller = BridgeController(services)
    controller.enter_work_mode("mesh")

    with pytest.raises(RuntimeError, match="bake failed"):
        controller.bake_to_as("mesh")

    assert services.transactions[0].restored
    assert not controller.sessions
