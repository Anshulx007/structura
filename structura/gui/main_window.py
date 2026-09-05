"""The application window: menus, toolbar, docks and file handling."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from ..core import examples, io
from ..core.model import AnalysisType
from .commands import DeleteCommand, SetAnalysisTypeCommand
from .document import Document
from .panels import ModelTreeDock, PropertiesDock
from .scene.canvas_scene import CanvasScene
from .scene.canvas_view import CanvasView
from .tools import MemberTool, NodeTool, SelectTool, Tool

FILE_FILTER = "Structura project (*.stru);;All files (*)"


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Structura")
        self.resize(1280, 820)

        self.document = Document(parent=self)
        self.canvas = CanvasScene(self.document)
        self.view = CanvasView(self.canvas)
        self.setCentralWidget(self.view)

        self.properties = PropertiesDock(self.document, self)
        self.model_tree = ModelTreeDock(self.document, self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.properties)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.model_tree)

        self._tools: dict[str, Tool] = {
            "select": SelectTool(),
            "node": NodeTool(),
            "member": MemberTool(),
        }
        self._tool_actions: dict[str, QAction] = {}

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_status_bar()

        self.canvas.selectionChanged.connect(self._on_selection_changed)
        self.canvas.snapHintChanged.connect(self._on_snap_hint)
        self.canvas.viewScaleChanged.connect(self._on_view_scale)
        self.model_tree.selectionRequested.connect(self._on_tree_selection)
        self.document.modelChanged.connect(self._on_model_changed)
        self.document.fileChanged.connect(self._update_title)

        self.set_tool("select")
        self._update_title()
        self._update_counts()

    # ------------------------------------------------------------------ setup

    def _act(
        self,
        text: str,
        slot: object,
        shortcut: QKeySequence | QKeySequence.StandardKey | str | None = None,
        checkable: bool = False,
        tip: str = "",
    ) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.setCheckable(checkable)
        if tip:
            action.setStatusTip(tip)
        action.triggered.connect(slot)  # type: ignore[arg-type]
        return action

    def _build_actions(self) -> None:
        self.action_new = self._act("&New", self.file_new, QKeySequence.StandardKey.New)
        self.action_open = self._act("&Open...", self.file_open, QKeySequence.StandardKey.Open)
        self.action_save = self._act("&Save", self.file_save, QKeySequence.StandardKey.Save)
        self.action_save_as = self._act(
            "Save &As...", self.file_save_as, QKeySequence.StandardKey.SaveAs
        )
        self.action_quit = self._act("E&xit", self.close, QKeySequence.StandardKey.Quit)

        self.action_undo = self.document.undo_stack.createUndoAction(self, "&Undo")
        self.action_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.action_redo = self.document.undo_stack.createRedoAction(self, "&Redo")
        self.action_redo.setShortcut(QKeySequence.StandardKey.Redo)

        self.action_delete = self._act(
            "&Delete", self.delete_selection, QKeySequence.StandardKey.Delete,
            tip="Delete the selection. Deleting a joint also deletes its members.",
        )
        self.action_select_all = self._act(
            "Select &All", self.select_all, QKeySequence.StandardKey.SelectAll
        )
        self.action_deselect = self._act("Deselect", self.deselect_all, "Escape")

        self.action_zoom_in = self._act(
            "Zoom &In", self.view.zoom_in, QKeySequence.StandardKey.ZoomIn
        )
        self.action_zoom_out = self._act(
            "Zoom &Out", self.view.zoom_out, QKeySequence.StandardKey.ZoomOut
        )
        self.action_zoom_fit = self._act("&Fit to model", self.view.fit_to_model, "Ctrl+0")
        self.action_zoom_reset = self._act("&Reset zoom", self.view.reset_zoom, "Ctrl+1")

        self.action_grid = self._act("Show &grid", self.toggle_grid, "G", checkable=True)
        self.action_grid.setChecked(True)
        self.action_snap_nodes = self._act("Snap to &joints", self._sync_snap, checkable=True)
        self.action_snap_nodes.setChecked(True)
        self.action_snap_members = self._act("Snap to &members", self._sync_snap, checkable=True)
        self.action_snap_members.setChecked(True)
        self.action_snap_grid = self._act("Snap to gr&id", self._sync_snap, checkable=True)
        self.action_snap_grid.setChecked(True)

        group = QActionGroup(self)
        group.setExclusive(True)
        for key, label, shortcut in (
            ("select", "&Select", "S"),
            ("node", "Add &joint", "N"),
            ("member", "Add &member", "M"),
        ):
            action = self._act(
                label, lambda _checked=False, k=key: self.set_tool(k), shortcut, checkable=True
            )
            group.addAction(action)
            self._tool_actions[key] = action

        self.action_truss = self._act(
            "&Truss", lambda: self.set_analysis_type(AnalysisType.TRUSS), checkable=True
        )
        self.action_frame = self._act(
            "&Frame", lambda: self.set_analysis_type(AnalysisType.FRAME), checkable=True
        )
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)
        mode_group.addAction(self.action_truss)
        mode_group.addAction(self.action_frame)
        self.action_truss.setChecked(True)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([self.action_new, self.action_open])
        file_menu.addSeparator()
        file_menu.addActions([self.action_save, self.action_save_as])
        file_menu.addSeparator()

        example_menu = file_menu.addMenu("Open &example")
        for key in sorted(examples.EXAMPLES):
            title, _builder = examples.EXAMPLES[key]
            example_menu.addAction(
                self._act(f"{key}  {title}", lambda _c=False, k=key: self.open_example(k))
            )
        file_menu.addSeparator()
        file_menu.addAction(self.action_quit)

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addActions([self.action_undo, self.action_redo])
        edit_menu.addSeparator()
        edit_menu.addActions([self.action_delete, self.action_select_all, self.action_deselect])

        draw_menu = self.menuBar().addMenu("&Draw")
        draw_menu.addActions(list(self._tool_actions.values()))
        draw_menu.addSeparator()
        mode_menu = draw_menu.addMenu("Analysis &type")
        mode_menu.addActions([self.action_truss, self.action_frame])

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addActions(
            [
                self.action_zoom_in,
                self.action_zoom_out,
                self.action_zoom_fit,
                self.action_zoom_reset,
            ]
        )
        view_menu.addSeparator()
        view_menu.addActions(
            [self.action_grid, self.action_snap_nodes, self.action_snap_members,
             self.action_snap_grid]
        )
        view_menu.addSeparator()
        view_menu.addAction(self.properties.toggleViewAction())
        view_menu.addAction(self.model_tree.toggleViewAction())

    def _build_toolbar(self) -> None:
        bar = self.addToolBar("Main")
        bar.setObjectName("MainToolBar")
        bar.setMovable(False)
        bar.addActions([self.action_new, self.action_open, self.action_save])
        bar.addSeparator()
        bar.addActions([self.action_undo, self.action_redo])
        bar.addSeparator()
        bar.addActions(list(self._tool_actions.values()))
        bar.addSeparator()
        bar.addActions([self.action_zoom_fit, self.action_grid])

    def _build_status_bar(self) -> None:
        self._status_hint = QLabel("")
        self._status_counts = QLabel("")
        self._status_zoom = QLabel("")
        bar = self.statusBar()
        bar.addWidget(self._status_hint, 1)
        bar.addPermanentWidget(self._status_counts)
        bar.addPermanentWidget(self._status_zoom)

    # ------------------------------------------------------------------ tools

    def set_tool(self, key: str) -> None:
        """Make one tool current, letting the previous one clean up after itself."""
        previous = self.canvas.tool
        if isinstance(previous, Tool):
            previous.deactivate(self.canvas)

        tool = self._tools[key]
        self.canvas.tool = tool
        tool.activate(self.canvas)

        action = self._tool_actions.get(key)
        if action is not None and not action.isChecked():
            action.setChecked(True)

        # Only the select tool wants Qt's rubber band; the others draw with the left button.
        self.view.setDragMode(
            CanvasView.DragMode.RubberBandDrag if key == "select" else CanvasView.DragMode.NoDrag
        )
        self._status_hint.setText(tool.status_hint)

    def set_analysis_type(self, analysis_type: AnalysisType) -> None:
        if self.document.structure.analysis_type is not analysis_type:
            self.document.push(SetAnalysisTypeCommand(self.document, analysis_type))

    def toggle_grid(self) -> None:
        self.canvas.grid_visible = self.action_grid.isChecked()
        self.canvas.invalidate(
            self.canvas.sceneRect(), CanvasScene.SceneLayer.BackgroundLayer
        )

    def _sync_snap(self) -> None:
        settings = self.canvas.snap_settings
        settings.to_nodes = self.action_snap_nodes.isChecked()
        settings.to_members = self.action_snap_members.isChecked()
        settings.to_grid = self.action_snap_grid.isChecked()

    # ------------------------------------------------------------------ editing

    def delete_selection(self) -> None:
        node_ids = self.canvas.selected_node_ids()
        member_ids = self.canvas.selected_member_ids()
        if node_ids or member_ids:
            self.document.push(DeleteCommand(self.document, node_ids, member_ids))

    def select_all(self) -> None:
        structure = self.document.structure
        self.canvas.select_ids(sorted(structure.nodes), sorted(structure.members))

    def deselect_all(self) -> None:
        tool = self.canvas.tool
        if isinstance(tool, Tool) and tool.cancel(self.canvas):
            return
        self.canvas.clearSelection()

    # ------------------------------------------------------------------ signals

    def _on_selection_changed(self) -> None:
        node_ids = self.canvas.selected_node_ids()
        member_ids = self.canvas.selected_member_ids()
        self.properties.show_selection(node_ids, member_ids)
        self.model_tree.show_selection(node_ids, member_ids)

    def _on_tree_selection(self, node_ids: list[int], member_ids: list[int]) -> None:
        self.canvas.select_ids(node_ids, member_ids)

    def _on_snap_hint(self, text: str) -> None:
        tool = self.canvas.tool
        base = tool.status_hint if isinstance(tool, Tool) else ""
        self._status_hint.setText(f"{base}   [{text}]" if text else base)

    def _on_view_scale(self, scale: float) -> None:
        self._status_zoom.setText(f"zoom {scale:.3g}x")

    def _on_model_changed(self) -> None:
        self._update_counts()
        self._on_selection_changed()

    def _update_counts(self) -> None:
        structure = self.document.structure
        self._status_counts.setText(
            f"{len(structure.nodes)} joints   {len(structure.members)} members"
        )
        self._status_zoom.setText(f"zoom {self.view.scale_factor:.3g}x")

    def _update_title(self) -> None:
        self.setWindowTitle(f"Structura - {self.document.display_name}")

    # ------------------------------------------------------------------ files

    def _confirm_discard(self) -> bool:
        """Ask before throwing away unsaved work. True means it is safe to proceed."""
        if not self.document.is_modified:
            return True
        answer = QMessageBox.warning(
            self,
            "Unsaved changes",
            f"'{self.document.display_name}' has unsaved changes.",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.file_save()
        return answer == QMessageBox.StandardButton.Discard

    def file_new(self) -> None:
        if self._confirm_discard():
            self.document.reset()
            self.view.fit_to_model()

    def file_open(self) -> None:
        if not self._confirm_discard():
            return
        name, _ = QFileDialog.getOpenFileName(self, "Open project", "", FILE_FILTER)
        if name:
            self.load_path(Path(name))

    def load_path(self, path: Path) -> None:
        try:
            self.document.load(path)
        except (io.SchemaError, OSError) as error:
            QMessageBox.critical(self, "Could not open project", str(error))
            return
        self.view.fit_to_model()

    def open_example(self, key: str) -> None:
        if not self._confirm_discard():
            return
        self.document.reset(examples.build(key))
        self.view.fit_to_model()

    def file_save(self) -> bool:
        if self.document.path is None:
            return self.file_save_as()
        return self._write(self.document.path)

    def file_save_as(self) -> bool:
        name, _ = QFileDialog.getSaveFileName(self, "Save project", "", FILE_FILTER)
        return self._write(Path(name)) if name else False

    def _write(self, path: Path) -> bool:
        try:
            self.document.save(path)
        except OSError as error:
            QMessageBox.critical(self, "Could not save project", str(error))
            return False
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
