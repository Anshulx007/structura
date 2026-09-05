"""Phase 3 gate: the drawing interface.

The plan's exit criteria, as executable tests:

  * draw a 20-node truss comfortably
  * every mutation undoes and redoes correctly
  * save, close, reopen reproduces the drawing exactly
  * zoom from 0.01x to 100x stays usable
  * deleting a joint deletes its members, and undo restores both

Tools are driven with real ``QGraphicsSceneMouseEvent`` objects rather than by poking their
internals, so these exercise the same path a mouse does. Everything runs offscreen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="GUI tests are optional; pip install -e '.[gui]'")

pytestmark = pytest.mark.gui

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QGraphicsSceneMouseEvent  # noqa: E402

from structura.core import examples  # noqa: E402
from structura.gui.commands import DeleteCommand  # noqa: E402
from structura.gui.document import Document  # noqa: E402
from structura.gui.scene import coords  # noqa: E402
from structura.gui.scene.canvas_scene import CanvasScene  # noqa: E402
from structura.gui.scene.canvas_view import MAX_SCALE, MIN_SCALE, CanvasView  # noqa: E402
from structura.gui.tools import MemberTool, NodeTool, SelectTool  # noqa: E402


def press_at(model_x: float, model_y: float, shift: bool = False) -> QGraphicsSceneMouseEvent:
    """A left-button press at a model-space point."""
    event = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMousePress)
    event.setScenePos(QPointF(*coords.to_scene(model_x, model_y)))
    event.setButton(Qt.MouseButton.LeftButton)
    event.setModifiers(
        Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier
    )
    return event


@pytest.fixture
def canvas(qtbot):  # type: ignore[no-untyped-def]
    """An empty document with a scene and a shown view, at a known zoom."""
    document = Document()
    scene = CanvasScene(document)
    view = CanvasView(scene)
    qtbot.addWidget(view)
    view.resize(900, 700)
    view.show()
    qtbot.waitExposed(view)
    view.reset_zoom()
    return document, scene, view


# ---------------------------------------------------------------- drawing


def test_node_tool_places_joints(canvas) -> None:  # type: ignore[no-untyped-def]
    document, scene, _view = canvas
    tool = NodeTool()
    scene.tool = tool

    for x, y in [(0.0, 0.0), (2.0, 0.0), (4.0, 0.0)]:
        tool.mouse_press(scene, press_at(x, y))

    assert len(document.structure.nodes) == 3
    assert len(scene._node_items) == 3


def test_node_tool_will_not_stack_a_joint_on_an_existing_one(canvas) -> None:  # type: ignore[no-untyped-def]
    """A duplicate joint looks identical and transfers no force. It must not be creatable."""
    document, scene, _view = canvas
    tool = NodeTool()
    scene.tool = tool

    tool.mouse_press(scene, press_at(1.0, 1.0))
    tool.mouse_press(scene, press_at(1.0, 1.0))

    assert len(document.structure.nodes) == 1
    assert scene.selected_node_ids() == [1], "the existing joint is selected instead"


def test_member_tool_chains_and_creates_joints(canvas) -> None:  # type: ignore[no-untyped-def]
    document, scene, _view = canvas
    tool = MemberTool()
    scene.tool = tool

    for point in [(0.0, 0.0), (2.0, 0.0), (4.0, 0.0)]:
        tool.mouse_press(scene, press_at(*point))

    structure = document.structure
    assert len(structure.nodes) == 3
    assert len(structure.members) == 2, "the tool chains from the joint just reached"


def test_drawing_a_20_node_truss(canvas) -> None:  # type: ignore[no-untyped-def]
    """The headline gate: a realistic Warren truss drawn entirely through the tools."""
    document, scene, view = canvas
    tool = MemberTool()
    scene.tool = tool

    panels = 9
    span = 1.0
    height = 1.5
    bottom = [(i * span, 0.0) for i in range(panels + 1)]
    top = [(i * span + span / 2.0, height) for i in range(panels)]

    # Bottom chord, drawn as one chained run.
    for point in bottom:
        tool.mouse_press(scene, press_at(*point))
    tool.cancel(scene)

    # Top chord.
    for point in top:
        tool.mouse_press(scene, press_at(*point))
    tool.cancel(scene)

    # Diagonals: each top joint braced back to the two bottom joints beneath it.
    for index, apex in enumerate(top):
        tool.mouse_press(scene, press_at(*bottom[index]))
        tool.mouse_press(scene, press_at(*apex))
        tool.mouse_press(scene, press_at(*bottom[index + 1]))
        tool.cancel(scene)

    structure = document.structure
    assert len(structure.nodes) == 19
    assert len(structure.members) >= 20
    assert len(scene._node_items) == len(structure.nodes)
    assert len(scene._member_items) == len(structure.members)

    # No duplicates and no degenerate members: the drawing is actually analysable.
    from structura.core.validation import errors_only, validate_model

    assert errors_only(validate_model(structure)) == []

    view.fit_to_model()
    assert MIN_SCALE < view.scale_factor < MAX_SCALE


def test_member_tool_refuses_a_self_loop(canvas) -> None:  # type: ignore[no-untyped-def]
    document, scene, _view = canvas
    tool = MemberTool()
    scene.tool = tool

    tool.mouse_press(scene, press_at(1.0, 1.0))
    tool.mouse_press(scene, press_at(1.0, 1.0))

    assert len(document.structure.members) == 0


def test_member_tool_does_not_duplicate_an_existing_member(canvas) -> None:  # type: ignore[no-untyped-def]
    document, scene, _view = canvas
    tool = MemberTool()
    scene.tool = tool

    tool.mouse_press(scene, press_at(0.0, 0.0))
    tool.mouse_press(scene, press_at(2.0, 0.0))
    tool.cancel(scene)
    tool.mouse_press(scene, press_at(0.0, 0.0))
    tool.mouse_press(scene, press_at(2.0, 0.0))

    assert len(document.structure.members) == 1


# ---------------------------------------------------------------- undo / redo


def test_drawing_a_member_undoes_as_one_step_including_its_joints(canvas) -> None:  # type: ignore[no-untyped-def]
    """Undo must not leave the two joints the member tool created behind."""
    document, scene, _view = canvas
    tool = MemberTool()
    scene.tool = tool

    tool.mouse_press(scene, press_at(0.0, 0.0))
    tool.mouse_press(scene, press_at(3.0, 0.0))

    assert len(document.structure.nodes) == 2
    assert len(document.structure.members) == 1

    document.undo_stack.undo()
    assert len(document.structure.nodes) == 0
    assert len(document.structure.members) == 0

    document.undo_stack.redo()
    assert len(document.structure.nodes) == 2
    assert len(document.structure.members) == 1


def test_every_mutation_undoes_and_redoes(canvas) -> None:  # type: ignore[no-untyped-def]
    """Walk the whole stack back to empty and forward again, comparing hashes each way."""
    document, scene, _view = canvas
    member_tool = MemberTool()
    scene.tool = member_tool
    for point in [(0.0, 0.0), (2.0, 0.0), (1.0, 1.5), (0.0, 0.0)]:
        member_tool.mouse_press(scene, press_at(*point))
    member_tool.cancel(scene)

    hashes = [document.structure.content_hash()]
    while document.undo_stack.canUndo():
        document.undo_stack.undo()
        hashes.append(document.structure.content_hash())

    assert len(document.structure.nodes) == 0, "undoing everything must empty the model"

    for expected in reversed(hashes[:-1]):
        document.undo_stack.redo()
        assert document.structure.content_hash() == expected


def test_deleting_a_joint_removes_its_members_and_undo_restores_both(canvas) -> None:  # type: ignore[no-untyped-def]
    document, scene, _view = canvas
    document.reset(examples.t2_triangular_truss())
    before = document.structure.content_hash()

    apex = max(document.structure.nodes)
    assert len(document.structure.members_at_node(apex)) == 2

    document.push(DeleteCommand(document, node_ids=[apex]))
    assert len(document.structure.nodes) == 2
    assert len(document.structure.members) == 1
    assert len(scene._member_items) == 1, "the canvas dropped the members too"

    document.undo_stack.undo()
    assert document.structure.content_hash() == before
    assert len(scene._node_items) == 3
    assert len(scene._member_items) == 3


def test_deleting_a_member_leaves_its_joints(canvas) -> None:  # type: ignore[no-untyped-def]
    document, _scene, _view = canvas
    document.reset(examples.t2_triangular_truss())

    document.push(DeleteCommand(document, member_ids=[3]))
    assert len(document.structure.nodes) == 3
    assert len(document.structure.members) == 2


def test_a_drag_is_exactly_one_undo_step(canvas) -> None:  # type: ignore[no-untyped-def]
    """Dragging emits many move events; the user expects one Ctrl+Z to put it back."""
    document, scene, _view = canvas
    document.reset(examples.t2_triangular_truss())
    document.undo_stack.clear()

    item = scene.node_item(3)
    assert item is not None
    item.setSelected(True)
    scene._capture_drag_start()

    for step in range(1, 6):  # simulate a multi-step drag
        item.setPos(*coords.to_scene(3.0 + 0.1 * step, 4.0))
    scene._commit_drag()

    assert document.undo_stack.count() == 1, "one drag, one undo entry"
    assert document.structure.nodes[3].x == pytest.approx(3.5)

    document.undo_stack.undo()
    assert document.structure.nodes[3].x == pytest.approx(3.0)


def test_a_click_without_movement_is_not_an_undo_step(canvas) -> None:  # type: ignore[no-untyped-def]
    document, scene, _view = canvas
    document.reset(examples.t2_triangular_truss())
    document.undo_stack.clear()

    item = scene.node_item(3)
    assert item is not None
    item.setSelected(True)
    scene._capture_drag_start()
    scene._commit_drag()

    assert document.undo_stack.count() == 0


def test_dragging_moves_attached_members_with_the_joint(canvas) -> None:  # type: ignore[no-untyped-def]
    document, scene, _view = canvas
    document.reset(examples.t2_triangular_truss())

    node_item = scene.node_item(3)
    member_item = scene.member_item(1)
    assert node_item is not None and member_item is not None

    before = member_item.boundingRect()
    node_item.setPos(*coords.to_scene(3.0, 8.0))
    assert member_item.boundingRect() != before, "the member followed the joint"


# ---------------------------------------------------------------- files


def test_save_close_reopen_reproduces_the_drawing(canvas, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    document, scene, _view = canvas
    tool = MemberTool()
    scene.tool = tool
    for point in [(0.0, 0.0), (3.0, 0.0), (1.5, 2.0), (0.0, 0.0)]:
        tool.mouse_press(scene, press_at(*point))
    tool.cancel(scene)

    original = document.structure.content_hash()
    target = document.save(tmp_path / "drawing.stru")
    assert not document.is_modified

    reopened = Document()
    reopened.load(target)
    assert reopened.structure.content_hash() == original
    assert len(reopened.structure.nodes) == len(document.structure.nodes)
    assert len(reopened.structure.members) == len(document.structure.members)


def test_reset_clears_the_undo_stack(canvas) -> None:  # type: ignore[no-untyped-def]
    """Undoing across a file load would leave the drawing and the path disagreeing."""
    document, scene, _view = canvas
    tool = NodeTool()
    scene.tool = tool
    tool.mouse_press(scene, press_at(1.0, 1.0))
    assert document.undo_stack.canUndo()

    document.reset(examples.t2_triangular_truss())
    assert not document.undo_stack.canUndo()
    assert not document.is_modified


def test_modified_flag_tracks_the_undo_stack(canvas, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    document, scene, _view = canvas
    tool = NodeTool()
    scene.tool = tool

    assert not document.is_modified
    tool.mouse_press(scene, press_at(1.0, 1.0))
    assert document.is_modified
    assert document.display_name.endswith("*")

    document.save(tmp_path / "x.stru")
    assert not document.is_modified
    assert document.display_name == "x.stru"


# ---------------------------------------------------------------- view


@pytest.mark.parametrize("target", [0.01, 0.1, 1.0, 10.0, 100.0])
def test_zoom_range_is_usable(canvas, target: float) -> None:  # type: ignore[no-untyped-def]
    """Grid, hit widths and coordinate mapping must all survive the extremes."""
    document, scene, view = canvas
    document.reset(examples.t2_triangular_truss())

    view.reset_zoom()
    view.zoom_by(target)
    assert view.scale_factor == pytest.approx(target, rel=1e-6)
    assert scene.view_scale == pytest.approx(target, rel=1e-6)

    # A model point still maps to the right place and back.
    scene_point = QPointF(*coords.to_scene(3.0, 4.0))
    assert coords.to_model(scene_point.x(), scene_point.y()) == pytest.approx((3.0, 4.0))

    # The member hit band stays a sane on-screen width rather than collapsing.
    member = scene.member_item(1)
    assert member is not None
    assert member.shape().boundingRect().width() > 0.0

    assert scene.grid_step_metres() > 0.0


def test_zoom_is_clamped(canvas) -> None:  # type: ignore[no-untyped-def]
    _document, _scene, view = canvas
    for _ in range(200):
        view.zoom_by(2.0)
    assert view.scale_factor <= MAX_SCALE

    for _ in range(400):
        view.zoom_by(0.5)
    assert view.scale_factor >= MIN_SCALE


def test_fit_to_model_frames_the_structure(canvas) -> None:  # type: ignore[no-untyped-def]
    document, _scene, view = canvas
    document.reset(examples.t2_triangular_truss())
    view.fit_to_model()

    visible = view.mapToScene(view.viewport().rect()).boundingRect()
    for node in document.structure.nodes.values():
        assert visible.contains(QPointF(*coords.to_scene(node.x, node.y))), (
            f"node {node.id} is off screen after fit"
        )


def test_fit_on_an_empty_model_does_not_crash(canvas) -> None:  # type: ignore[no-untyped-def]
    _document, _scene, view = canvas
    view.fit_to_model()
    assert view.scale_factor > 0.0


# ---------------------------------------------------------------- selection


def test_selection_round_trips_through_ids(canvas) -> None:  # type: ignore[no-untyped-def]
    document, scene, _view = canvas
    document.reset(examples.t2_triangular_truss())

    scene.select_ids([1, 3], [2])
    assert scene.selected_node_ids() == [1, 3]
    assert scene.selected_member_ids() == [2]

    scene.select_ids([], [])
    assert scene.selected_node_ids() == []


def test_deleted_items_leave_the_selection(canvas) -> None:  # type: ignore[no-untyped-def]
    document, scene, _view = canvas
    document.reset(examples.t2_triangular_truss())
    scene.select_ids([3], [])

    document.push(DeleteCommand(document, node_ids=[3]))
    assert 3 not in scene.selected_node_ids()


def test_select_tool_consumes_nothing(canvas) -> None:  # type: ignore[no-untyped-def]
    """Qt's own selection behaviour must remain in charge."""
    _document, scene, _view = canvas
    tool = SelectTool()
    event = press_at(0.0, 0.0)

    assert tool.mouse_press(scene, event) is False
    assert tool.mouse_release(scene, event) is False
