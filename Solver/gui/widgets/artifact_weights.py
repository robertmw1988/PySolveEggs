"""
Artifact weights configuration widgets.

Provides editable tables for:
- Mission artifact collection weights (what to gather from missions)
- Crafted artifact target weights (what to prioritize crafting)
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
    QLineEdit,
    QComboBox,
    QPushButton,
    QScrollArea,
    QFrame,
    QAbstractItemView,
)

from ...config import UserConfig


# Weight categories for filtering/grouping
WEIGHT_CATEGORIES = {
    "Target (1.0)": 1.0,
    "Ingredient (0.0)": 0.0,
    "Unwanted (-1.0)": -1.0,
    "Custom": None,
}


class ArtifactWeightRow(QWidget):
    """
    A single row for editing an artifact weight.
    
    Contains: artifact name, weight category dropdown, custom weight input
    
    Signals:
        weight_changed(str, float): Emitted when weight changes (artifact_name, weight)
    """
    
    weight_changed = Signal(str, float)
    
    def __init__(
        self,
        artifact_name: str,
        weight: float = 1.0,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._artifact_name = artifact_name
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)
        
        # Artifact name
        name_label = QLabel(artifact_name)
        name_label.setMinimumWidth(250)
        name_label.setWordWrap(True)
        layout.addWidget(name_label, stretch=3)
        
        # Category dropdown
        self._category_combo = QComboBox()
        self._category_combo.setFixedWidth(120)
        for cat in WEIGHT_CATEGORIES:
            self._category_combo.addItem(cat)
        self._category_combo.currentTextChanged.connect(self._on_category_changed)
        layout.addWidget(self._category_combo)
        
        # Custom weight input
        self._weight_spin = QLineEdit()
        self._weight_spin.setFixedWidth(60)
        self._weight_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._weight_spin.editingFinished.connect(self._on_weight_edited)
        layout.addWidget(self._weight_spin)
        
        # Set initial value
        self._set_weight_silently(weight)
    
    def _set_weight_silently(self, weight: float) -> None:
        """Set weight without emitting signals."""
        self._category_combo.blockSignals(True)
        self._weight_spin.blockSignals(True)
        
        self._weight_spin.setText(f"{weight:.1f}")
        
        # Match to category
        category_found = False
        for cat, val in WEIGHT_CATEGORIES.items():
            if val is not None and abs(weight - val) < 0.01:
                self._category_combo.setCurrentText(cat)
                self._weight_spin.setEnabled(False)
                category_found = True
                break
        
        if not category_found:
            self._category_combo.setCurrentText("Custom")
            self._weight_spin.setEnabled(True)
        
        self._category_combo.blockSignals(False)
        self._weight_spin.blockSignals(False)
    
    @property
    def weight(self) -> float:
        try:
            return float(self._weight_spin.text())
        except ValueError:
            return 0.0
    
    @weight.setter
    def weight(self, val: float) -> None:
        self._set_weight_silently(val)
    
    def _on_category_changed(self, text: str) -> None:
        cat_val = WEIGHT_CATEGORIES.get(text)
        if cat_val is not None:
            self._weight_spin.setEnabled(False)
            self._weight_spin.setText(f"{cat_val:.1f}")
            self.weight_changed.emit(self._artifact_name, cat_val)
        else:
            self._weight_spin.setEnabled(True)
    
    def _on_weight_edited(self) -> None:
        try:
            val = float(self._weight_spin.text())
            self.weight_changed.emit(self._artifact_name, val)
        except ValueError:
            pass  # Invalid input, ignore


class ArtifactWeightsTableWidget(QWidget):
    """
    Table widget for editing artifact weights.
    
    Provides search/filter, category filter, and bulk operations.
    
    Signals:
        weights_changed(dict): Emitted when any weight changes.
            Dict maps artifact name -> weight
    """
    
    weights_changed = Signal(dict)
    
    def __init__(
        self,
        title: str,
        weights: dict[str, float],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        self._weights = dict(weights)
        self._rows: dict[str, ArtifactWeightRow] = {}
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Header with title
        header = QLabel(title)
        header.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(header)
        
        # Filter row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        
        # Search box
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search artifacts...")
        self._search_box.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._search_box, stretch=2)
        
        # Category filter
        self._category_filter = QComboBox()
        self._category_filter.addItem("All")
        self._category_filter.addItems(list(WEIGHT_CATEGORIES.keys()))
        self._category_filter.currentTextChanged.connect(self._apply_filter)
        filter_row.addWidget(self._category_filter)
        
        layout.addLayout(filter_row)
        
        # Scrollable area for rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.StyledPanel)
        
        container = QWidget()
        self._rows_layout = QVBoxLayout(container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        
        # Create rows for all artifacts
        for artifact, weight in sorted(weights.items()):
            row = ArtifactWeightRow(artifact, weight)
            row.weight_changed.connect(self._on_weight_changed)
            self._rows[artifact] = row
            self._rows_layout.addWidget(row)
        
        self._rows_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)
        
        # Bulk operations
        bulk_row = QHBoxLayout()
        bulk_row.setSpacing(8)
        
        bulk_label = QLabel("Set filtered to:")
        bulk_row.addWidget(bulk_label)
        
        for cat, val in WEIGHT_CATEGORIES.items():
            if val is not None:
                btn = QPushButton(cat.split()[0])  # Just first word
                btn.setFixedWidth(80)
                btn.clicked.connect(lambda checked, v=val: self._set_filtered_weights(v))
                bulk_row.addWidget(btn)
        
        bulk_row.addStretch()
        layout.addLayout(bulk_row)
    
    def _on_weight_changed(self, artifact: str, weight: float) -> None:
        """Handle individual weight change."""
        self._weights[artifact] = weight
        self.weights_changed.emit(self._weights)
    
    def _apply_filter(self) -> None:
        """Apply search and category filters."""
        search_text = self._search_box.text().lower()
        category = self._category_filter.currentText()
        
        for artifact, row in self._rows.items():
            # Check search match
            search_match = not search_text or search_text in artifact.lower()
            
            # Check category match
            if category == "All":
                cat_match = True
            else:
                cat_val = WEIGHT_CATEGORIES.get(category)
                if cat_val is not None:
                    cat_match = abs(row.weight - cat_val) < 0.01
                else:
                    # Custom - show items that don't match standard categories
                    cat_match = all(
                        v is None or abs(row.weight - v) >= 0.01
                        for v in WEIGHT_CATEGORIES.values()
                    )
            
            row.setVisible(search_match and cat_match)
    
    def _set_filtered_weights(self, value: float) -> None:
        """Set all currently visible rows to a specific weight."""
        for artifact, row in self._rows.items():
            if row.isVisible():
                row.weight = value
                self._weights[artifact] = value
        self.weights_changed.emit(self._weights)
    
    def get_weights(self) -> dict[str, float]:
        """Get current weights dict."""
        return dict(self._weights)
    
    def update_weights(self, weights: dict[str, float]) -> None:
        """Update all weights from a dict."""
        self._weights = dict(weights)
        for artifact, row in self._rows.items():
            if artifact in weights:
                row.weight = weights[artifact]


class MissionArtifactWeightsWidget(QWidget):
    """
    Widget for editing mission artifact collection weights.
    
    These weights determine which artifacts the solver prioritizes gathering.
    
    Signals:
        weights_changed(dict): Emitted when weights change
    """
    
    weights_changed = Signal(dict)
    
    def __init__(
        self,
        user_config: Optional[UserConfig] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        config = user_config or UserConfig()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Description
        desc = QLabel(
            "Configure which artifacts to prioritize during mission collection. "
            "Higher weights mean higher priority."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666; margin-bottom: 8px;")
        layout.addWidget(desc)
        
        # Weights table
        self._table = ArtifactWeightsTableWidget(
            title="Mission Artifact Weights",
            weights=config.mission_artifact_weights,
        )
        self._table.weights_changed.connect(self.weights_changed.emit)
        layout.addWidget(self._table)
    
    def get_weights(self) -> dict[str, float]:
        return self._table.get_weights()
    
    def update_from_user_config(self, user_config: UserConfig) -> None:
        self._table.update_weights(user_config.mission_artifact_weights)


class CraftedArtifactWeightsWidget(QWidget):
    """
    Widget for editing crafted artifact target weights.
    
    These weights determine which artifacts the solver prioritizes for crafting.
    
    Signals:
        weights_changed(dict): Emitted when weights change
    """
    
    weights_changed = Signal(dict)
    
    def __init__(
        self,
        user_config: Optional[UserConfig] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        config = user_config or UserConfig()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Description
        desc = QLabel(
            "Configure which artifacts to target for crafting. "
            "Target (1.0) = craft these, Ingredient (0.0) = use as materials, "
            "Unwanted (-1.0) = avoid collecting."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666; margin-bottom: 8px;")
        layout.addWidget(desc)
        
        # Weights table
        self._table = ArtifactWeightsTableWidget(
            title="Crafting Target Weights",
            weights=config.crafted_artifact_weights,
        )
        self._table.weights_changed.connect(self.weights_changed.emit)
        layout.addWidget(self._table)
    
    def get_weights(self) -> dict[str, float]:
        return self._table.get_weights()
    
    def update_from_user_config(self, user_config: UserConfig) -> None:
        self._table.update_weights(user_config.crafted_artifact_weights)
