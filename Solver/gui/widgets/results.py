"""
Results display widgets.

Displays solver output including:
- Mission recommendations table
- Expected artifact drops
- BOM rollup (crafting summary)
- Fuel usage summary
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QGroupBox,
    QScrollArea,
    QFrame,
    QTextEdit,
    QSplitter,
    QTabWidget,
)

from ...mission_solver import SolverResult
from ...bom import RollupResult


class MissionTableWidget(QWidget):
    """
    Table displaying recommended missions.
    
    Columns: Count, Ship, Duration, Level, Target
    """
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        header = QLabel("Recommended Missions")
        header.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(header)
        
        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["Count", "Ship", "Duration", "Level", "Target"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)
    
    def clear(self) -> None:
        """Clear the table."""
        self._table.setRowCount(0)
    
    def set_results(self, result: SolverResult) -> None:
        """Populate table from solver result."""
        self.clear()
        
        missions = result.selected_missions
        self._table.setRowCount(len(missions))
        
        for row, (mission, count) in enumerate(missions):
            # Count
            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 0, count_item)
            
            # Ship
            self._table.setItem(row, 1, QTableWidgetItem(mission.ship_label))
            
            # Duration
            duration = mission.duration_type.capitalize()
            self._table.setItem(row, 2, QTableWidgetItem(duration))
            
            # Level
            level_item = QTableWidgetItem(str(mission.level))
            level_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 3, level_item)
            
            # Target
            target = mission.target_artifact or "Any"
            if target.upper() == "UNKNOWN":
                target = "Any"
            self._table.setItem(row, 4, QTableWidgetItem(target))


class DropsTableWidget(QWidget):
    """
    Table displaying expected artifact drops.
    
    Columns: Artifact, Expected Count
    """
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        header = QLabel("Expected Drops")
        header.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(header)
        
        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["Artifact", "Expected"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)
    
    def clear(self) -> None:
        """Clear the table."""
        self._table.setRowCount(0)
    
    def set_drops(self, drops: dict[str, float]) -> None:
        """Populate table from drops dict."""
        self.clear()
        
        # Sort by count descending, filter out zero
        sorted_drops = sorted(
            [(art, amt) for art, amt in drops.items() if amt > 0.01],
            key=lambda x: -x[1]
        )
        
        self._table.setRowCount(len(sorted_drops))
        
        for row, (artifact, amount) in enumerate(sorted_drops):
            self._table.setItem(row, 0, QTableWidgetItem(artifact))
            
            amt_item = QTableWidgetItem(f"{amount:.2f}")
            amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, 1, amt_item)


class BOMRollupWidget(QWidget):
    """
    Table displaying BOM rollup results - what can be crafted from drops.
    
    Shows:
    - Crafted artifacts and quantities
    - Consumed ingredients
    - Remaining inventory
    - Any shortfalls
    """
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Sub-tabs for different BOM sections
        self._bom_tabs = QTabWidget()
        
        # Crafted artifacts tab
        self._crafted_table = QTableWidget()
        self._crafted_table.setColumnCount(2)
        self._crafted_table.setHorizontalHeaderLabels(["Artifact", "Crafted"])
        self._crafted_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._crafted_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._crafted_table.setAlternatingRowColors(True)
        self._crafted_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._bom_tabs.addTab(self._crafted_table, "Crafted")
        
        # Consumed ingredients tab
        self._consumed_table = QTableWidget()
        self._consumed_table.setColumnCount(2)
        self._consumed_table.setHorizontalHeaderLabels(["Ingredient", "Used"])
        self._consumed_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._consumed_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._consumed_table.setAlternatingRowColors(True)
        self._consumed_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._bom_tabs.addTab(self._consumed_table, "Consumed")
        
        # Remaining inventory tab
        self._remaining_table = QTableWidget()
        self._remaining_table.setColumnCount(2)
        self._remaining_table.setHorizontalHeaderLabels(["Artifact", "Remaining"])
        self._remaining_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._remaining_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._remaining_table.setAlternatingRowColors(True)
        self._remaining_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._bom_tabs.addTab(self._remaining_table, "Remaining")
        
        layout.addWidget(self._bom_tabs)
        
        # Placeholder label when no BOM data
        self._placeholder = QLabel("No BOM rollup data.\nSet crafting weights to enable.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self._placeholder)
        
        # Initially show placeholder
        self._bom_tabs.hide()
    
    def clear(self) -> None:
        """Clear all tables."""
        self._crafted_table.setRowCount(0)
        self._consumed_table.setRowCount(0)
        self._remaining_table.setRowCount(0)
        self._bom_tabs.hide()
        self._placeholder.show()
    
    def set_rollup(self, rollup: Optional[RollupResult]) -> None:
        """Populate tables from BOM rollup result."""
        self.clear()
        
        if rollup is None:
            return
        
        # Check if there's any data
        has_data = (rollup.crafted or rollup.consumed or rollup.remaining)
        if not has_data:
            return
        
        self._placeholder.hide()
        self._bom_tabs.show()
        
        # Populate crafted table
        if rollup.crafted:
            sorted_crafted = sorted(
                [(art, qty) for art, qty in rollup.crafted.items() if qty > 0.001],
                key=lambda x: -x[1]
            )
            self._crafted_table.setRowCount(len(sorted_crafted))
            for row, (artifact, qty) in enumerate(sorted_crafted):
                self._crafted_table.setItem(row, 0, QTableWidgetItem(artifact))
                qty_item = QTableWidgetItem(f"{qty:.2f}")
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._crafted_table.setItem(row, 1, qty_item)
        
        # Populate consumed table
        if rollup.consumed:
            sorted_consumed = sorted(
                [(art, qty) for art, qty in rollup.consumed.items() if qty > 0.001],
                key=lambda x: -x[1]
            )
            self._consumed_table.setRowCount(len(sorted_consumed))
            for row, (artifact, qty) in enumerate(sorted_consumed):
                self._consumed_table.setItem(row, 0, QTableWidgetItem(artifact))
                qty_item = QTableWidgetItem(f"{qty:.2f}")
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._consumed_table.setItem(row, 1, qty_item)
        
        # Populate remaining table
        if rollup.remaining:
            sorted_remaining = sorted(
                [(art, qty) for art, qty in rollup.remaining.items() if qty > 0.001],
                key=lambda x: -x[1]
            )
            self._remaining_table.setRowCount(len(sorted_remaining))
            for row, (artifact, qty) in enumerate(sorted_remaining):
                self._remaining_table.setItem(row, 0, QTableWidgetItem(artifact))
                qty_item = QTableWidgetItem(f"{qty:.2f}")
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._remaining_table.setItem(row, 1, qty_item)


class SummaryWidget(QWidget):
    """
    Summary panel showing solver status and key metrics.
    Compact design - only 4-5 lines of text.
    """
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        
        # Status
        self._status_label = QLabel("Status: Ready")
        self._status_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._status_label)
        
        # Objective
        self._objective_label = QLabel("Objective: -")
        layout.addWidget(self._objective_label)
        
        # Time
        self._time_label = QLabel("Total Time: -")
        layout.addWidget(self._time_label)
        
        # Fuel
        self._fuel_label = QLabel("Fuel Usage: -")
        layout.addWidget(self._fuel_label)
        
        # Set fixed height - only needs 4 lines of text
        self.setMaximumHeight(90)
    
    def clear(self) -> None:
        """Reset to default state."""
        self._status_label.setText("Status: Ready")
        self._objective_label.setText("Objective: -")
        self._time_label.setText("Total Time: -")
        self._fuel_label.setText("Fuel Usage: -")
    
    def set_running(self) -> None:
        """Show running state."""
        self._status_label.setText("Status: Solving...")
        self._status_label.setStyleSheet("font-weight: bold; color: #f39c12;")
    
    def set_result(self, result: SolverResult, fuel_capacity: float) -> None:
        """Update from solver result."""
        # Status
        if result.status == "Optimal":
            self._status_label.setText(f"Status: {result.status}")
            self._status_label.setStyleSheet("font-weight: bold; color: #27ae60;")
        else:
            self._status_label.setText(f"Status: {result.status}")
            self._status_label.setStyleSheet("font-weight: bold; color: #e74c3c;")
        
        # Objective
        self._objective_label.setText(f"Objective: {result.objective_value:.2f}")
        
        # Time
        hours = result.total_time_hours
        if hours >= 24:
            days = hours / 24
            self._time_label.setText(f"Total Time: {hours:.1f}h ({days:.1f} days)")
        else:
            self._time_label.setText(f"Total Time: {hours:.1f} hours")
        
        # Fuel
        tank_used = result.fuel_usage.tank_total / 1e12
        remaining = fuel_capacity - tank_used
        self._fuel_label.setText(f"Fuel: {tank_used:.1f}T used, {remaining:.1f}T remaining")


class ResultsWidget(QWidget):
    """
    Combined results display widget.
    
    Contains:
    - Compact summary at top (fixed height)
    - Tabs for missions, drops, and BOM rollup (expandable)
    """
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Summary at top (compact, fixed height)
        self._summary = SummaryWidget()
        layout.addWidget(self._summary, stretch=0)
        
        # Tabs for details (gets all remaining space)
        self._tabs = QTabWidget()
        
        # Missions tab
        self._missions_table = MissionTableWidget()
        self._tabs.addTab(self._missions_table, "Missions")
        
        # Drops tab
        self._drops_table = DropsTableWidget()
        self._tabs.addTab(self._drops_table, "Drops")
        
        # BOM Rollup tab
        self._bom_widget = BOMRollupWidget()
        self._tabs.addTab(self._bom_widget, "BOM Rollup")
        
        layout.addWidget(self._tabs, stretch=1)
    
    def clear(self) -> None:
        """Clear all results."""
        self._summary.clear()
        self._missions_table.clear()
        self._drops_table.clear()
        self._bom_widget.clear()
    
    def set_running(self) -> None:
        """Show solving state."""
        self._summary.set_running()
    
    def set_result(self, result: SolverResult, fuel_capacity: float) -> None:
        """Update all displays from solver result."""
        self._summary.set_result(result, fuel_capacity)
        self._missions_table.set_results(result)
        self._drops_table.set_drops(result.total_drops)
        self._bom_widget.set_rollup(result.bom_rollup)
