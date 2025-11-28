"""
Constraint configuration widgets.

Provides input controls for:
- Number of concurrent ships
- Fuel tank capacity (with presets)
- Time budget (hours/days)
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QGroupBox,
    QFrame,
)

from ...config import Constraints, UserConfig


# Fuel tank presets (in trillions)
FUEL_TANK_PRESETS = {
    "10T (Basic)": 10.0,
    "100T": 100.0,
    "1000T (1q)": 1000.0,
    "10000T (10q)": 10000.0,
    "Custom": -1.0,  # Sentinel for custom input
}


class FuelTankWidget(QWidget):
    """
    Widget for configuring fuel tank capacity.
    
    Provides preset dropdown and custom input option.
    
    Signals:
        value_changed(float): Emitted when capacity changes (in trillions)
    """
    
    value_changed = Signal(float)
    
    def __init__(
        self,
        initial_value: float = 500.0,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Label
        label = QLabel("Fuel Tank Capacity")
        label.setStyleSheet("font-weight: bold;")
        layout.addWidget(label)
        
        # Input row
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        
        # Preset dropdown
        self._preset_combo = QComboBox()
        for name in FUEL_TANK_PRESETS:
            self._preset_combo.addItem(name)
        self._preset_combo.currentTextChanged.connect(self._on_preset_changed)
        input_row.addWidget(self._preset_combo)
        
        # Custom input
        self._custom_spin = QDoubleSpinBox()
        self._custom_spin.setRange(1.0, 100000.0)
        self._custom_spin.setDecimals(0)
        self._custom_spin.setSuffix(" T")
        self._custom_spin.setValue(initial_value)
        self._custom_spin.setFixedWidth(100)
        self._custom_spin.valueChanged.connect(self._on_custom_changed)
        input_row.addWidget(self._custom_spin)
        
        input_row.addStretch()
        layout.addLayout(input_row)
        
        # Set initial state
        self._set_value_silently(initial_value)
    
    def _set_value_silently(self, value: float) -> None:
        """Set value without emitting signals."""
        # Block signals during update
        self._custom_spin.blockSignals(True)
        self._preset_combo.blockSignals(True)
        
        self._custom_spin.setValue(value)
        
        # Find matching preset
        preset_found = False
        for name, preset_val in FUEL_TANK_PRESETS.items():
            if preset_val == value:
                self._preset_combo.setCurrentText(name)
                self._custom_spin.setEnabled(False)
                preset_found = True
                break
        
        if not preset_found:
            self._preset_combo.setCurrentText("Custom")
            self._custom_spin.setEnabled(True)
        
        self._custom_spin.blockSignals(False)
        self._preset_combo.blockSignals(False)
    
    @property
    def value(self) -> float:
        return self._custom_spin.value()
    
    @value.setter
    def value(self, val: float) -> None:
        self._set_value_silently(val)
        self.value_changed.emit(val)
    
    def _on_preset_changed(self, text: str) -> None:
        preset_val = FUEL_TANK_PRESETS.get(text, -1.0)
        if preset_val > 0:
            self._custom_spin.setEnabled(False)
            self._custom_spin.setValue(preset_val)
            self.value_changed.emit(preset_val)
        else:
            self._custom_spin.setEnabled(True)
    
    def _on_custom_changed(self, value: float) -> None:
        self.value_changed.emit(value)


class TimeBudgetWidget(QWidget):
    """
    Widget for configuring time budget.
    
    Allows input in hours or days with conversion.
    
    Signals:
        value_changed(float): Emitted when time changes (in hours)
    """
    
    value_changed = Signal(float)
    
    def __init__(
        self,
        initial_hours: float = 336.0,  # 14 days
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Label
        label = QLabel("Time Budget")
        label.setStyleSheet("font-weight: bold;")
        layout.addWidget(label)
        
        # Input row
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        
        # Value input
        self._value_spin = QDoubleSpinBox()
        self._value_spin.setRange(1.0, 9999.0)
        self._value_spin.setDecimals(1)
        self._value_spin.setFixedWidth(80)
        self._value_spin.valueChanged.connect(self._on_value_changed)
        input_row.addWidget(self._value_spin)
        
        # Unit selector
        self._unit_combo = QComboBox()
        self._unit_combo.addItems(["Hours", "Days"])
        self._unit_combo.currentTextChanged.connect(self._on_unit_changed)
        input_row.addWidget(self._unit_combo)
        
        # Hours display
        self._hours_label = QLabel()
        self._hours_label.setStyleSheet("color: #666;")
        input_row.addWidget(self._hours_label)
        
        input_row.addStretch()
        layout.addLayout(input_row)
        
        # Initialize
        self._current_hours = initial_hours
        self._update_display()
    
    def _update_display(self) -> None:
        """Update the display based on current hours value."""
        unit = self._unit_combo.currentText()
        
        self._value_spin.blockSignals(True)
        if unit == "Hours":
            self._value_spin.setValue(self._current_hours)
            self._hours_label.setText("")
        else:  # Days
            self._value_spin.setValue(self._current_hours / 24.0)
            self._hours_label.setText(f"({self._current_hours:.0f} hours)")
        self._value_spin.blockSignals(False)
    
    @property
    def hours(self) -> float:
        return self._current_hours
    
    @hours.setter
    def hours(self, value: float) -> None:
        self._current_hours = value
        self._update_display()
        self.value_changed.emit(value)
    
    def _on_value_changed(self, value: float) -> None:
        unit = self._unit_combo.currentText()
        if unit == "Hours":
            self._current_hours = value
        else:  # Days
            self._current_hours = value * 24.0
        self._update_display()
        self.value_changed.emit(self._current_hours)
    
    def _on_unit_changed(self, text: str) -> None:
        self._update_display()


class NumShipsWidget(QWidget):
    """
    Widget for configuring number of concurrent mission ships.
    
    Signals:
        value_changed(int): Emitted when count changes
    """
    
    value_changed = Signal(int)
    
    def __init__(
        self,
        initial_value: int = 3,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Label
        label = QLabel("Concurrent Ships:")
        label.setStyleSheet("font-weight: bold;")
        layout.addWidget(label)
        
        # Spinbox
        self._spinbox = QSpinBox()
        self._spinbox.setRange(1, 10)
        self._spinbox.setValue(initial_value)
        self._spinbox.setFixedWidth(60)
        self._spinbox.valueChanged.connect(self.value_changed.emit)
        layout.addWidget(self._spinbox)
        
        layout.addStretch()
    
    @property
    def value(self) -> int:
        return self._spinbox.value()
    
    @value.setter
    def value(self, val: int) -> None:
        self._spinbox.setValue(val)


class ConstraintsWidget(QWidget):
    """
    Combined widget for all solver constraints.
    
    Contains:
    - Number of concurrent ships
    - Fuel tank capacity
    - Time budget
    
    Signals:
        config_changed(Constraints, int): Emitted when any constraint changes.
            Returns (Constraints, num_ships)
    """
    
    config_changed = Signal(object, int)  # (Constraints, num_ships)
    
    def __init__(
        self,
        user_config: Optional[UserConfig] = None,
        num_ships: int = 3,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        config = user_config or UserConfig()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        # Number of ships
        self._num_ships = NumShipsWidget(initial_value=num_ships)
        self._num_ships.value_changed.connect(self._on_changed)
        layout.addWidget(self._num_ships)
        
        # Fuel tank
        self._fuel_tank = FuelTankWidget(initial_value=config.constraints.fuel_tank_capacity)
        self._fuel_tank.value_changed.connect(self._on_changed)
        layout.addWidget(self._fuel_tank)
        
        # Time budget
        self._time_budget = TimeBudgetWidget(initial_hours=config.constraints.max_time_hours)
        self._time_budget.value_changed.connect(self._on_changed)
        layout.addWidget(self._time_budget)
        
        layout.addStretch()
    
    def _on_changed(self, *args) -> None:
        """Handle any constraint change."""
        self.config_changed.emit(self.get_constraints(), self.get_num_ships())
    
    def get_constraints(self) -> Constraints:
        """Get current Constraints object."""
        return Constraints(
            fuel_tank_capacity=self._fuel_tank.value,
            max_time_hours=self._time_budget.hours,
        )
    
    def get_num_ships(self) -> int:
        """Get number of concurrent ships."""
        return self._num_ships.value
    
    def update_from_user_config(self, user_config: UserConfig, num_ships: int = 3) -> None:
        """Update all constraints from a UserConfig."""
        self._fuel_tank.value = user_config.constraints.fuel_tank_capacity
        self._time_budget.hours = user_config.constraints.max_time_hours
        self._num_ships.value = num_ships
