"""Phase 4 gate: supports, loads and interactive analysis.

The headline criterion from the plan: draw T2 from scratch through the GUI, click Analyze, and
read 12.5 kN compression / 7.5 kN tension off the result - the same numbers the CLI and the
hand calculation give.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="GUI tests are optional; pip install -e '.[gui]'")

pytestmark = pytest.mark.gui

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QGraphicsSceneMouseEvent  # noqa: E402

from structura.core import examples  # noqa: E402
from structura.core.model import MemberState, NodalLoad, SupportType  # noqa: E402
from structura.gui.commands import SetNodalLoadCommand, SetSupportCommand  # noqa: E402
from structura.gui.controllers import AnalysisController  # noqa: E402
from structura.gui.document import Document  # noqa: E402
from structura.gui.scene import coords  # noqa: E402
from structura.gui.scene.canvas_scene import CanvasScene  # noqa: E402
from structura.gui.tools import LoadTool, MemberTool, SupportTool  # noqa: E402

KN = 1.0e3


def press_at(model_x: float, model_y: float) -> QGraphicsSceneMouseEvent:
    event = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMousePress)
    event.setScenePos(QPointF(*coords.to_scene(model_x, model_y)))
    event.setButton(Qt.MouseButton.LeftButton)
    event.setModifiers(Qt.KeyboardModifier.NoModifier)
    return event


@pytest.fixture
def canvas(qtbot):  # type: ignore[no-untyped-def]
    document = Document()
    scene = CanvasScene(document)
    return document, scene


# ---------------------------------------------------------------- supports


def test_support_tool_applies_and_toggles(canvas) -> None:  # type: ignore[no-untyped-def]
    document, scene = canvas
    document.reset(examples.t2_triangular_truss())
    tool = SupportTool(SupportType.FIXED)
    scene.tool = tool

    tool.mouse_press(scene, press_at(3.0, 4.0))
    assert document.structure.supports[3].type is SupportType.FIXED

    tool.mouse_press(scene, press_at(3.0, 4.0))
    assert 3 not in document.structure.supports, "clicking the same support again removes it"


def test_support_tool_replaces_a_different_support(canvas) -> None:  # type: ignore[no-untyped-def]
    document, scene = canvas
    document.reset(examples.t2_triangular_truss())
    scene.tool = tool = SupportTool(SupportType.FIXED)

    tool.mouse_press(scene, press_at(0.0, 0.0))  # node 1 is currently a pin
    assert document.structure.supports[1].type is SupportType.FIXED


def test_support_tool_ignores_empty_space(canvas) -> None:  # type: ignore[no-untyped-def]
    """Creating a joint here would attach a support the user never asked for."""
    document, scene = canvas
    document.reset(examples.t2_triangular_truss())
    scene.tool = tool = SupportTool()

    before = len(document.structure.nodes)
    tool.mouse_press(scene, press_at(1.5, 2.5))

    assert len(document.structure.nodes) == before
    assert len(document.structure.supports) == 2


def test_support_command_undoes(canvas) -> None:  # type: ignore[no-untyped-def]
    document, _scene = canvas
    document.reset(examples.t2_triangular_truss())
    before = document.structure.content_hash()

    from structura.core.model import Support

    document.push(SetSupportCommand(document, 3, Support.fixed(3)))
    assert 3 in document.structure.supports

    document.undo_stack.undo()
    assert document.structure.content_hash() == before


# ---------------------------------------------------------------- loads


def test_load_tool_applies_the_default_load(canvas) -> None:  # type: ignore[no-untyped-def]
    document, scene = canvas
    document.reset(examples.t2_triangular_truss())
    scene.tool = tool = LoadTool()

    tool.mouse_press(scene, press_at(0.0, 0.0))
    loads = {load.node_id: load.fy for load in document.structure.active_load_case.nodal}
    assert loads[1] == pytest.approx(-10 * KN), "default is a downward force"


def test_load_tool_uses_the_injected_prompt(canvas) -> None:  # type: ignore[no-untyped-def]
    """The dialog lives in the main window so the tool stays testable."""
    document, scene = canvas
    document.reset(examples.t2_triangular_truss())

    def prompt(current: NodalLoad) -> NodalLoad:
        return NodalLoad(current.node_id, fx=3 * KN, fy=-7 * KN)

    scene.tool = tool = LoadTool(prompt=prompt)
    tool.mouse_press(scene, press_at(0.0, 0.0))

    load = next(x for x in document.structure.active_load_case.nodal if x.node_id == 1)
    assert (load.fx, load.fy) == pytest.approx((3 * KN, -7 * KN))


def test_load_tool_cancel_changes_nothing(canvas) -> None:  # type: ignore[no-untyped-def]
    document, scene = canvas
    document.reset(examples.t2_triangular_truss())
    before = document.structure.content_hash()

    scene.tool = tool = LoadTool(prompt=lambda _current: None)
    tool.mouse_press(scene, press_at(0.0, 0.0))

    assert document.structure.content_hash() == before


def test_setting_a_load_replaces_rather_than_stacks(canvas) -> None:  # type: ignore[no-untyped-def]
    """Two loads at one joint would make the properties panel disagree with the solver."""
    document, _scene = canvas
    document.reset(examples.t2_triangular_truss())

    document.push(SetNodalLoadCommand(document, 3, fy=-5 * KN))
    document.push(SetNodalLoadCommand(document, 3, fy=-8 * KN))

    at_node_3 = [x for x in document.structure.active_load_case.nodal if x.node_id == 3]
    assert len(at_node_3) == 1
    assert at_node_3[0].fy == pytest.approx(-8 * KN)


def test_a_zero_load_is_removed_not_stored(canvas) -> None:  # type: ignore[no-untyped-def]
    document, _scene = canvas
    document.reset(examples.t2_triangular_truss())

    document.push(SetNodalLoadCommand(document, 3, fy=0.0))
    assert not [x for x in document.structure.active_load_case.nodal if x.node_id == 3]


def test_load_command_undoes_to_the_previous_value(canvas) -> None:  # type: ignore[no-untyped-def]
    document, _scene = canvas
    document.reset(examples.t2_triangular_truss())
    before = document.structure.content_hash()

    document.push(SetNodalLoadCommand(document, 3, fy=-99 * KN))
    document.undo_stack.undo()

    assert document.structure.content_hash() == before


# ---------------------------------------------------------------- analysis


def test_analyze_reproduces_the_textbook_answer(canvas) -> None:  # type: ignore[no-untyped-def]
    document, _scene = canvas
    document.reset(examples.t2_triangular_truss())
    controller = AnalysisController(document)

    result = controller.run()
    assert result is not None

    assert result.member(1).axial == pytest.approx(-12.5 * KN, rel=1e-9)
    assert result.member(1).state is MemberState.COMPRESSION
    assert result.member(3).axial == pytest.approx(7.5 * KN, rel=1e-9)
    assert result.member(3).state is MemberState.TENSION
    assert result.reactions[1].fy == pytest.approx(10 * KN, rel=1e-9)
    assert result.equilibrium is not None and result.equilibrium.passed


def test_drawing_t2_from_scratch_then_analyzing(canvas) -> None:  # type: ignore[no-untyped-def]
    """The Phase 4 headline: geometry, supports and loads all placed through the tools."""
    document, scene = canvas
    controller = AnalysisController(document)

    member_tool = MemberTool()
    scene.tool = member_tool
    for point in [(0.0, 0.0), (6.0, 0.0), (3.0, 4.0), (0.0, 0.0)]:
        member_tool.mouse_press(scene, press_at(*point))
    member_tool.cancel(scene)

    pin = SupportTool(SupportType.PIN)
    scene.tool = pin
    pin.mouse_press(scene, press_at(0.0, 0.0))
    roller = SupportTool(SupportType.ROLLER_X)
    scene.tool = roller
    roller.mouse_press(scene, press_at(6.0, 0.0))

    load = LoadTool(prompt=lambda current: NodalLoad(current.node_id, fy=-20 * KN))
    scene.tool = load
    load.mouse_press(scene, press_at(3.0, 4.0))

    structure = document.structure
    assert len(structure.nodes) == 3
    assert len(structure.members) == 3
    assert len(structure.supports) == 2

    result = controller.run()
    assert result is not None

    forces = sorted(round(m.axial / KN, 4) for m in result.members.values())
    assert forces == pytest.approx([-12.5, -12.5, 7.5]), (
        "a truss drawn entirely through the GUI must give the hand-calculated answer"
    )
    assert result.equilibrium is not None and result.equilibrium.passed


def test_results_go_stale_when_the_model_is_edited(canvas) -> None:  # type: ignore[no-untyped-def]
    """Numbers describing a drawing the user has since changed are worse than none."""
    document, _scene = canvas
    document.reset(examples.t2_triangular_truss())
    controller = AnalysisController(document)

    changes: list[bool] = []
    controller.stalenessChanged.connect(changes.append)

    controller.run()
    assert not controller.is_stale

    document.push(SetNodalLoadCommand(document, 3, fy=-40 * KN))
    assert controller.is_stale
    assert changes[-1] is True

    controller.run()
    assert not controller.is_stale
    assert changes[-1] is False


def test_moving_a_joint_also_makes_results_stale(canvas) -> None:  # type: ignore[no-untyped-def]
    from structura.gui.commands import MoveNodesCommand

    document, _scene = canvas
    document.reset(examples.t2_triangular_truss())
    controller = AnalysisController(document)
    controller.run()

    document.push(MoveNodesCommand(document, {3: ((3.0, 4.0), (3.0, 5.0))}))
    assert controller.is_stale


def test_unstable_structure_reports_named_diagnostics(canvas) -> None:  # type: ignore[no-untyped-def]
    document, _scene = canvas
    document.reset(examples.e5_collinear_members())
    controller = AnalysisController(document)

    failures: list[tuple[str, list]] = []
    controller.failed.connect(lambda message, diagnostics: failures.append((message, diagnostics)))

    assert controller.run() is None
    assert not controller.has_result

    _message, diagnostics = failures[0]
    mechanisms = [d for d in diagnostics if d.code == "MECHANISM"]
    assert mechanisms, "the mechanism must be reported"
    assert 2 in mechanisms[0].node_ids, "and it must name the offending joint"


def test_missing_supports_are_reported_not_crashed(canvas) -> None:  # type: ignore[no-untyped-def]
    document, _scene = canvas
    structure = examples.t2_triangular_truss()
    structure.supports.clear()
    document.reset(structure)
    controller = AnalysisController(document)

    failures: list[list] = []
    controller.failed.connect(lambda _m, diagnostics: failures.append(diagnostics))

    assert controller.run() is None
    assert any(d.code == "NO_SUPPORTS" for d in failures[0])


def test_clear_discards_results(canvas) -> None:  # type: ignore[no-untyped-def]
    document, _scene = canvas
    document.reset(examples.t2_triangular_truss())
    controller = AnalysisController(document)
    controller.run()
    assert controller.has_result

    controller.clear()
    assert not controller.has_result
    assert not controller.is_stale
