"""
Main application window for the PySolve Eggs GUI.

Integrates all widgets and connects to the solver backend.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, Slot, QThread, QObject
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QGroupBox,
    QMessageBox,
    QStatusBar,
    QMenuBar,
    QMenu,
    QFileDialog,
    QApplication,
)

from ..config import (
    UserConfig,
    EpicResearch,
    Constraints,
    load_config,
    save_config,
    DEFAULT_CONFIG_PATH,
    SHIP_METADATA,
)
from ..mission_solver import SolverResult, solve
from .widgets import (
    ShipConfigWidget,
    EpicResearchWidget,
    ConstraintsWidget,
    ResultsWidget,
)


class SolverWorker(QObject):
    """
    Worker object to run the solver in a background thread.
    
    Signals:
        finished(SolverResult): Emitted when solver completes
        error(str): Emitted on solver error
    """
    
    finished = Signal(object)  # SolverResult
    error = Signal(str)
    
    def __init__(self, config: UserConfig, num_ships: int):
        super().__init__()
        self._config = config
        self._num_ships = num_ships
    
    @Slot()
    def run(self) -> None:
        """Execute the solver."""
        try:
            result = solve(self._config, num_ships=self._num_ships, verbose=False)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """
    Main application window.
    
    Layout:
    - Left panel: Ship configuration, Epic research, Constraints
    - Right panel: Results display
    - Bottom: Solve button, status bar
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        super().__init__()
        
        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._config = load_config(self._config_path)
        self._num_ships = 3
        self._solver_thread: Optional[QThread] = None
        self._dirty = False  # Track unsaved changes
        
        self._setup_ui()
        self._setup_menu()
        self._connect_signals()
        
        self.setWindowTitle("PySolve Eggs - Mission Optimizer")
        self.resize(1200, 800)
    
    def _setup_ui(self) -> None:
        """Build the main UI layout."""
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        
        # Main splitter: left config, right results
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel - configuration
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        
        # Ship configuration
        ship_group = QGroupBox("Ships")
        ship_layout = QVBoxLayout(ship_group)
        self._ship_widget = ShipConfigWidget(self._config)
        ship_layout.addWidget(self._ship_widget)
        left_layout.addWidget(ship_group, stretch=3)
        
        # Epic research
        research_group = QGroupBox("Epic Research")
        research_layout = QVBoxLayout(research_group)
        self._research_widget = EpicResearchWidget(self._config)
        research_layout.addWidget(self._research_widget)
        left_layout.addWidget(research_group, stretch=1)
        
        # Constraints
        constraints_group = QGroupBox("Constraints")
        constraints_layout = QVBoxLayout(constraints_group)
        self._constraints_widget = ConstraintsWidget(self._config, self._num_ships)
        constraints_layout.addWidget(self._constraints_widget)
        left_layout.addWidget(constraints_group, stretch=1)
        
        splitter.addWidget(left_panel)
        
        # Right panel - results
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        results_group = QGroupBox("Results")
        results_layout = QVBoxLayout(results_group)
        self._results_widget = ResultsWidget()
        results_layout.addWidget(self._results_widget)
        right_layout.addWidget(results_group)
        
        splitter.addWidget(right_panel)
        
        # Set splitter proportions
        splitter.setSizes([400, 800])
        main_layout.addWidget(splitter, stretch=1)
        
        # Bottom button row
        button_row = QHBoxLayout()
        button_row.setSpacing(12)
        
        self._solve_btn = QPushButton("Solve")
        self._solve_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                font-weight: bold;
                padding: 10px 30px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        self._solve_btn.clicked.connect(self._on_solve)
        button_row.addWidget(self._solve_btn)
        
        self._save_btn = QPushButton("Save Config")
        self._save_btn.clicked.connect(self._on_save_config)
        button_row.addWidget(self._save_btn)
        
        button_row.addStretch()
        main_layout.addLayout(button_row)
        
        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")
    
    def _setup_menu(self) -> None:
        """Build the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        load_action = file_menu.addAction("&Load Config...")
        load_action.triggered.connect(self._on_load_config)
        
        save_action = file_menu.addAction("&Save Config")
        save_action.triggered.connect(self._on_save_config)
        
        save_as_action = file_menu.addAction("Save Config &As...")
        save_as_action.triggered.connect(self._on_save_config_as)
        
        file_menu.addSeparator()
        
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(self._on_about)
    
    def _connect_signals(self) -> None:
        """Connect widget signals."""
        self._ship_widget.config_changed.connect(self._on_config_changed)
        self._research_widget.config_changed.connect(self._on_config_changed)
        self._constraints_widget.config_changed.connect(self._on_constraints_changed)
    
    def _on_config_changed(self, *args) -> None:
        """Handle any configuration change."""
        self._dirty = True
        self._update_window_title()
    
    def _on_constraints_changed(self, constraints: Constraints, num_ships: int) -> None:
        """Handle constraints change."""
        self._num_ships = num_ships
        self._dirty = True
        self._update_window_title()
    
    def _update_window_title(self) -> None:
        """Update window title to show dirty state."""
        title = "PySolve Eggs - Mission Optimizer"
        if self._dirty:
            title += " *"
        self.setWindowTitle(title)
    
    def _build_config_from_widgets(self) -> UserConfig:
        """Build a UserConfig from current widget states."""
        # Get ship missions (excluding ships with level -1)
        missions_dict = self._ship_widget.get_missions_dict()
        missions = {
            ship: level for ship, level in missions_dict.items()
            if level >= 0
        }
        
        # Epic research
        epic_researches = self._research_widget.get_epic_researches()
        
        # Constraints
        constraints = self._constraints_widget.get_constraints()
        
        return UserConfig(
            missions=missions,
            epic_researches=epic_researches,
            constraints=constraints,
            cost_weights=self._config.cost_weights,
            crafted_artifact_weights=self._config.crafted_artifact_weights,
            mission_artifact_weights=self._config.mission_artifact_weights,
        )
    
    @Slot()
    def _on_solve(self) -> None:
        """Run the solver."""
        if self._solver_thread is not None and self._solver_thread.isRunning():
            return  # Already running
        
        # Build config from widgets
        config = self._build_config_from_widgets()
        
        # Show running state
        self._solve_btn.setEnabled(False)
        self._results_widget.set_running()
        self._status_bar.showMessage("Solving...")
        
        # Create worker and thread
        self._solver_thread = QThread()
        self._solver_worker = SolverWorker(config, self._num_ships)
        self._solver_worker.moveToThread(self._solver_thread)
        
        # Connect signals
        self._solver_thread.started.connect(self._solver_worker.run)
        self._solver_worker.finished.connect(self._on_solve_finished)
        self._solver_worker.error.connect(self._on_solve_error)
        self._solver_worker.finished.connect(self._solver_thread.quit)
        self._solver_worker.error.connect(self._solver_thread.quit)
        
        # Start
        self._solver_thread.start()
    
    @Slot(object)
    def _on_solve_finished(self, result: SolverResult) -> None:
        """Handle solver completion."""
        self._solve_btn.setEnabled(True)
        
        fuel_capacity = self._constraints_widget.get_constraints().fuel_tank_capacity
        self._results_widget.set_result(result, fuel_capacity)
        
        self._status_bar.showMessage(
            f"Solved: {result.status}, {len(result.selected_missions)} missions, "
            f"{result.total_time_hours:.1f} hours"
        )
    
    @Slot(str)
    def _on_solve_error(self, error_msg: str) -> None:
        """Handle solver error."""
        self._solve_btn.setEnabled(True)
        self._results_widget.clear()
        
        self._status_bar.showMessage(f"Error: {error_msg}")
        QMessageBox.critical(self, "Solver Error", f"Failed to solve:\n{error_msg}")
    
    @Slot()
    def _on_save_config(self) -> None:
        """Save configuration to current path."""
        config = self._build_config_from_widgets()
        try:
            save_config(config, self._config_path)
            self._config = config
            self._dirty = False
            self._update_window_title()
            self._status_bar.showMessage(f"Saved to {self._config_path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save:\n{e}")
    
    @Slot()
    def _on_save_config_as(self) -> None:
        """Save configuration to a new path."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Configuration",
            str(self._config_path.parent),
            "YAML Files (*.yaml);;All Files (*)",
        )
        if path:
            self._config_path = Path(path)
            self._on_save_config()
    
    @Slot()
    def _on_load_config(self) -> None:
        """Load configuration from file."""
        if self._dirty:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Load anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Configuration",
            str(self._config_path.parent),
            "YAML Files (*.yaml);;All Files (*)",
        )
        if path:
            try:
                self._config_path = Path(path)
                self._config = load_config(self._config_path)
                
                # Update widgets
                self._ship_widget.update_from_user_config(self._config)
                self._research_widget.update_from_user_config(self._config)
                self._constraints_widget.update_from_user_config(self._config, self._num_ships)
                
                self._dirty = False
                self._update_window_title()
                self._status_bar.showMessage(f"Loaded from {self._config_path}")
            except Exception as e:
                QMessageBox.critical(self, "Load Error", f"Failed to load:\n{e}")
    
    @Slot()
    def _on_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About PySolve Eggs",
            "<h2>PySolve Eggs</h2>"
            "<p>Mission optimizer for Egg Inc. using linear programming.</p>"
            "<p>Version 0.1.0</p>"
            "<p>Built with PySide6 and PuLP</p>",
        )
    
    def closeEvent(self, event) -> None:
        """Handle window close."""
        if self._dirty:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Save before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Save:
                self._on_save_config()
                event.accept()
            elif reply == QMessageBox.StandardButton.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
