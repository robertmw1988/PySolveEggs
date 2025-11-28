"""
Epic Research configuration widget.

Provides input controls for FTL Drive Upgrades and Zero-G Quantum Containment
with level/max display format matching the reference image.
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
    QFrame,
    QGroupBox,
)

from ...config import EpicResearch, UserConfig


class EpicResearchInput(QWidget):
    """
    Input widget for a single epic research.
    
    Shows: Name, description, level input with "/ max" display
    
    Signals:
        value_changed(int): Emitted when level changes
    """
    
    value_changed = Signal(int)
    
    def __init__(
        self,
        name: str,
        description: str,
        research: EpicResearch,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._name = name
        self._research = research
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        
        # Name
        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(name_label)
        
        # Description
        desc_label = QLabel(description)
        desc_label.setStyleSheet("color: #666; font-size: 11px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        # Level input row
        input_row = QHBoxLayout()
        input_row.setSpacing(4)
        
        self._spinbox = QSpinBox()
        self._spinbox.setRange(0, research.max_level)
        self._spinbox.setValue(research.level)
        self._spinbox.setFixedWidth(60)
        self._spinbox.valueChanged.connect(self._on_value_changed)
        input_row.addWidget(self._spinbox)
        
        max_label = QLabel(f"/ {research.max_level}")
        max_label.setStyleSheet("color: #888;")
        input_row.addWidget(max_label)
        
        input_row.addStretch()
        layout.addLayout(input_row)
    
    @property
    def level(self) -> int:
        return self._spinbox.value()
    
    @level.setter
    def level(self, value: int) -> None:
        self._spinbox.setValue(value)
    
    def _on_value_changed(self, value: int) -> None:
        self._research.level = value
        self.value_changed.emit(value)
    
    def get_research(self) -> EpicResearch:
        """Get the current EpicResearch with updated level."""
        return EpicResearch(
            level=self._spinbox.value(),
            effect=self._research.effect,
            max_level=self._research.max_level,
        )


class EpicResearchWidget(QWidget):
    """
    Widget for configuring epic research levels.
    
    Contains inputs for:
    - FTL Drive Upgrades (mission time reduction)
    - Zero-G Quantum Containment (capacity increase)
    
    Signals:
        config_changed(dict): Emitted when any research changes.
            Dict maps research name -> EpicResearch
    """
    
    config_changed = Signal(dict)
    
    # Research definitions
    FTL_DRIVE = "FTL Drive Upgrades"
    ZERO_G = "Zero-G Quantum Containment"
    
    RESEARCH_DEFS = {
        FTL_DRIVE: {
            "description": "Mission time reducing epic research",
            "effect": 0.01,  # 1% per level
            "max_level": 60,
        },
        ZERO_G: {
            "description": "Mission capacity increasing epic research",
            "effect": 0.05,  # 5% per level
            "max_level": 10,
        },
    }
    
    def __init__(self, user_config: Optional[UserConfig] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._inputs: dict[str, EpicResearchInput] = {}
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Get existing research from config
        config = user_config or UserConfig()
        existing_research = config.epic_researches
        
        # Create inputs for each research
        for name, defs in self.RESEARCH_DEFS.items():
            # Use existing config or create default
            if name in existing_research:
                research = existing_research[name]
            else:
                research = EpicResearch(
                    level=0,
                    effect=defs["effect"],
                    max_level=defs["max_level"],
                )
            
            input_widget = EpicResearchInput(
                name=name,
                description=defs["description"],
                research=research,
            )
            input_widget.value_changed.connect(self._on_research_changed)
            
            self._inputs[name] = input_widget
            layout.addWidget(input_widget)
        
        layout.addStretch()
    
    def _on_research_changed(self, value: int) -> None:
        """Handle research level change."""
        self.config_changed.emit(self.get_epic_researches())
    
    def get_epic_researches(self) -> dict[str, EpicResearch]:
        """Get current epic research configuration."""
        return {name: inp.get_research() for name, inp in self._inputs.items()}
    
    def update_from_user_config(self, user_config: UserConfig) -> None:
        """Update inputs from a UserConfig."""
        for name, inp in self._inputs.items():
            if name in user_config.epic_researches:
                inp.level = user_config.epic_researches[name].level
            else:
                inp.level = 0
    
    def get_ftl_level(self) -> int:
        """Get FTL Drive Upgrades level."""
        return self._inputs[self.FTL_DRIVE].level
    
    def get_zero_g_level(self) -> int:
        """Get Zero-G Quantum Containment level."""
        return self._inputs[self.ZERO_G].level
