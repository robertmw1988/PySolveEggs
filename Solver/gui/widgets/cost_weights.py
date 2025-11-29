"""
Cost function weights widget.

Provides controls for solver priority weights:
- Time vs Fuel priority
- Artifact gain weight
- Slack penalty (unwanted artifacts)
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QDoubleSpinBox,
    QGroupBox,
    QFrame,
)

from ...config import CostWeights, UserConfig


class WeightSliderWidget(QWidget):
    """
    A labeled slider with numeric display for weight configuration.
    
    Signals:
        value_changed(float): Emitted when value changes
    """
    
    value_changed = Signal(float)
    
    def __init__(
        self,
        label: str,
        description: str,
        min_val: float = 0.0,
        max_val: float = 10.0,
        initial: float = 1.0,
        decimals: int = 1,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        self._min = min_val
        self._max = max_val
        self._decimals = decimals
        self._scale = 10 ** decimals
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(2)
        
        # Label row
        label_row = QHBoxLayout()
        
        name_label = QLabel(label)
        name_label.setStyleSheet("font-weight: bold;")
        label_row.addWidget(name_label)
        
        label_row.addStretch()
        
        # Value display
        self._value_spin = QDoubleSpinBox()
        self._value_spin.setRange(min_val, max_val)
        self._value_spin.setDecimals(decimals)
        self._value_spin.setValue(initial)
        self._value_spin.setFixedWidth(90)
        self._value_spin.valueChanged.connect(self._on_spin_changed)
        label_row.addWidget(self._value_spin)
        
        layout.addLayout(label_row)
        
        # Description
        desc_label = QLabel(description)
        desc_label.setStyleSheet("color: #666; font-size: 11px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        # Slider
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(int(min_val * self._scale), int(max_val * self._scale))
        self._slider.setValue(int(initial * self._scale))
        self._slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self._slider)
    
    @property
    def value(self) -> float:
        return self._value_spin.value()
    
    @value.setter
    def value(self, val: float) -> None:
        self._value_spin.blockSignals(True)
        self._slider.blockSignals(True)
        
        self._value_spin.setValue(val)
        self._slider.setValue(int(val * self._scale))
        
        self._value_spin.blockSignals(False)
        self._slider.blockSignals(False)
    
    def _on_slider_changed(self, value: int) -> None:
        float_val = value / self._scale
        self._value_spin.blockSignals(True)
        self._value_spin.setValue(float_val)
        self._value_spin.blockSignals(False)
        self.value_changed.emit(float_val)
    
    def _on_spin_changed(self, value: float) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(int(value * self._scale))
        self._slider.blockSignals(False)
        self.value_changed.emit(value)


class CostWeightsWidget(QWidget):
    """
    Widget for configuring cost function weights.
    
    Controls:
    - Mission Time weight (penalty for long missions)
    - Fuel Efficiency weight (penalty for fuel usage)
    - Artifact Gain weight (reward for valuable artifacts)
    - Slack Penalty weight (penalty for unwanted artifacts)
    
    Signals:
        weights_changed(CostWeights): Emitted when any weight changes
    """
    
    weights_changed = Signal(object)  # CostWeights
    
    def __init__(
        self,
        user_config: Optional[UserConfig] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        config = user_config or UserConfig()
        weights = config.cost_weights
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Mission Time
        self._time_weight = WeightSliderWidget(
            label="Mission Time Priority",
            description="Higher values favor shorter missions. Set to 0 to ignore mission duration.",
            min_val=0.0,
            max_val=10.0,
            initial=weights.mission_time,
        )
        self._time_weight.value_changed.connect(self._on_changed)
        layout.addWidget(self._time_weight)
        
        # Fuel Efficiency
        self._fuel_weight = WeightSliderWidget(
            label="Fuel Efficiency Priority",
            description="Higher values favor fuel-efficient missions. Set to 0 to ignore fuel usage.",
            min_val=0.0,
            max_val=10.0,
            initial=weights.fuel_efficiency,
        )
        self._fuel_weight.value_changed.connect(self._on_changed)
        layout.addWidget(self._fuel_weight)
        
        # Artifact Gain
        self._artifact_weight = WeightSliderWidget(
            label="Artifact Value Priority",
            description="Multiplier for artifact weights. Higher values prioritize high-value artifacts.",
            min_val=0.0,
            max_val=50.0,
            initial=weights.artifact_gain,
        )
        self._artifact_weight.value_changed.connect(self._on_changed)
        layout.addWidget(self._artifact_weight)
        
        # Slack Penalty
        self._slack_weight = WeightSliderWidget(
            label="Unwanted Artifact Penalty",
            description="Penalty for collecting artifacts with negative weights. Higher = avoid slack more.",
            min_val=0.0,
            max_val=100.0,
            initial=weights.slack_penalty,
        )
        self._slack_weight.value_changed.connect(self._on_changed)
        layout.addWidget(self._slack_weight)
        
        layout.addStretch()
    
    def _on_changed(self, *args) -> None:
        """Handle any weight change."""
        self.weights_changed.emit(self.get_cost_weights())
    
    def get_cost_weights(self) -> CostWeights:
        """Get current CostWeights object."""
        return CostWeights(
            mission_time=self._time_weight.value,
            fuel_efficiency=self._fuel_weight.value,
            artifact_gain=self._artifact_weight.value,
            slack_penalty=self._slack_weight.value,
        )
    
    def update_from_user_config(self, user_config: UserConfig) -> None:
        """Update from UserConfig."""
        weights = user_config.cost_weights
        self._time_weight.value = weights.mission_time
        self._fuel_weight.value = weights.fuel_efficiency
        self._artifact_weight.value = weights.artifact_gain
        self._slack_weight.value = weights.slack_penalty
