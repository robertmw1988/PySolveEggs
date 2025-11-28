"""
Ship configuration widget with star-rating selector.

Provides a visual interface for configuring ship levels and exclusions,
similar to the reference image with clickable stars and exclude toggle.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QColor, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QSizePolicy,
)

from ...config import SHIP_METADATA, ShipConfig, UserConfig, get_all_ship_configs


class StarRatingWidget(QWidget):
    """
    A clickable star rating widget.
    
    Features:
    - Click a star to set that level
    - Click the currently-selected highest star again to reset to 0
    - Shows filled stars up to current level, empty stars after
    
    Signals:
        level_changed(int): Emitted when level changes
    """
    
    level_changed = Signal(int)
    
    # Unicode characters for stars
    STAR_FILLED = "★"
    STAR_EMPTY = "☆"
    
    def __init__(
        self,
        max_level: int,
        current_level: int = 0,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._max_level = max_level
        self._current_level = min(current_level, max_level)
        self._hover_level: Optional[int] = None
        
        # Style
        self._star_color = QColor("#FFD700")  # Gold
        self._empty_color = QColor("#C0C0C0")  # Silver/gray
        self._hover_color = QColor("#FFA500")  # Orange
        
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Size based on number of stars
        star_width = 20
        self.setFixedSize(star_width * max(max_level, 1) + 4, 24)
    
    @property
    def level(self) -> int:
        return self._current_level
    
    @level.setter
    def level(self, value: int) -> None:
        value = max(0, min(value, self._max_level))
        if value != self._current_level:
            self._current_level = value
            self.update()
            self.level_changed.emit(value)
    
    def _star_at_position(self, x: int) -> int:
        """Get the star index (1-based) at the given x position."""
        if self._max_level == 0:
            return 0
        star_width = (self.width() - 4) / self._max_level
        star_idx = int(x / star_width) + 1
        return max(1, min(star_idx, self._max_level))
    
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._max_level > 0:
            clicked_star = self._star_at_position(int(event.position().x()))
            
            # If clicking the current level (highest filled star), toggle to 0
            if clicked_star == self._current_level:
                self.level = 0
            else:
                self.level = clicked_star
    
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._max_level > 0:
            self._hover_level = self._star_at_position(int(event.position().x()))
            self.update()
    
    def leaveEvent(self, event) -> None:
        self._hover_level = None
        self.update()
    
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        font = QFont()
        font.setPointSize(14)
        painter.setFont(font)
        
        if self._max_level == 0:
            # No stars for this ship
            painter.setPen(self._empty_color)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "-")
            return
        
        star_width = (self.width() - 4) / self._max_level
        
        for i in range(self._max_level):
            star_num = i + 1
            x = int(2 + i * star_width)
            
            # Determine star appearance
            if self._hover_level is not None and star_num <= self._hover_level:
                color = self._hover_color
                char = self.STAR_FILLED
            elif star_num <= self._current_level:
                color = self._star_color
                char = self.STAR_FILLED
            else:
                color = self._empty_color
                char = self.STAR_EMPTY
            
            painter.setPen(color)
            rect = self.rect()
            rect.setLeft(x)
            rect.setWidth(int(star_width))
            painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, char)


class ExcludeButton(QWidget):
    """
    A toggle button for excluding a ship from solving.
    
    Shows Ø symbol, highlighted when ship is excluded.
    
    Signals:
        toggled(bool): Emitted when exclusion state changes
    """
    
    toggled = Signal(bool)
    
    EXCLUDE_SYMBOL = "Ø"
    
    def __init__(self, excluded: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._excluded = excluded
        
        self._active_color = QColor("#E74C3C")  # Red when excluded
        self._inactive_color = QColor("#95A5A6")  # Gray when not excluded
        
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(24, 24)
        self.setToolTip("Exclude ship from optimization")
    
    @property
    def excluded(self) -> bool:
        return self._excluded
    
    @excluded.setter
    def excluded(self, value: bool) -> None:
        if value != self._excluded:
            self._excluded = value
            self.update()
            self.toggled.emit(value)
    
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.excluded = not self._excluded
    
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        font = QFont()
        font.setPointSize(14)
        font.setBold(self._excluded)
        painter.setFont(font)
        
        color = self._active_color if self._excluded else self._inactive_color
        painter.setPen(color)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.EXCLUDE_SYMBOL)


class ShipRowWidget(QWidget):
    """
    A single row in the ship configuration list.
    
    Contains: Ship name, exclude button, star rating
    
    Signals:
        config_changed(ShipConfig): Emitted when configuration changes
    """
    
    config_changed = Signal(object)  # ShipConfig
    
    def __init__(self, ship_config: ShipConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._config = ship_config
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(12)
        
        # Ship name
        name_label = QLabel(ship_config.display_name)
        name_label.setMinimumWidth(150)
        name_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(name_label)
        
        # Exclude button
        self._exclude_btn = ExcludeButton(ship_config.excluded)
        self._exclude_btn.toggled.connect(self._on_excluded_changed)
        layout.addWidget(self._exclude_btn)
        
        # Star rating
        self._star_rating = StarRatingWidget(
            max_level=ship_config.max_level,
            current_level=ship_config.level,
        )
        self._star_rating.level_changed.connect(self._on_level_changed)
        layout.addWidget(self._star_rating)
        
        layout.addStretch()
    
    @property
    def config(self) -> ShipConfig:
        return self._config
    
    def _on_level_changed(self, level: int) -> None:
        self._config.level = level
        self.config_changed.emit(self._config)
    
    def _on_excluded_changed(self, excluded: bool) -> None:
        self._config.excluded = excluded
        self.config_changed.emit(self._config)
    
    def update_from_config(self, config: ShipConfig) -> None:
        """Update widget state from a ShipConfig."""
        self._config = config
        self._star_rating.level = config.level
        self._exclude_btn.excluded = config.excluded


class ShipConfigWidget(QWidget):
    """
    Widget for configuring all ships.
    
    Displays a scrollable list of ships with star ratings and exclude toggles.
    
    Signals:
        config_changed(dict): Emitted when any ship config changes.
            Dict maps ship API name -> (level, excluded)
    """
    
    config_changed = Signal(dict)
    
    def __init__(self, user_config: Optional[UserConfig] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._ship_rows: dict[str, ShipRowWidget] = {}
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        header = QLabel("Mission Configuration")
        header.setStyleSheet("font-size: 14px; font-weight: bold; padding: 8px;")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(header)
        
        # Scrollable area for ships
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        container = QWidget()
        self._ships_layout = QVBoxLayout(container)
        self._ships_layout.setContentsMargins(0, 0, 0, 0)
        self._ships_layout.setSpacing(2)
        
        # Create ship rows
        ship_configs = get_all_ship_configs(user_config or UserConfig())
        for ship_config in ship_configs:
            # Skip Chicken One (tutorial ship with 0 stars)
            if ship_config.api_name == "CHICKEN_ONE":
                continue
            
            row = ShipRowWidget(ship_config)
            row.config_changed.connect(self._on_ship_changed)
            self._ship_rows[ship_config.api_name] = row
            self._ships_layout.addWidget(row)
        
        self._ships_layout.addStretch()
        scroll.setWidget(container)
        main_layout.addWidget(scroll)
    
    def _on_ship_changed(self, config: ShipConfig) -> None:
        """Handle a single ship's config change."""
        self.config_changed.emit(self.get_missions_dict())
    
    def get_missions_dict(self) -> dict[str, int]:
        """
        Get current ship configurations as a missions dict.
        
        Returns dict mapping ship API name -> level.
        Excluded ships are set to level -1 to signal exclusion.
        """
        result = {}
        for api_name, row in self._ship_rows.items():
            if row.config.excluded:
                result[api_name] = -1  # Signal exclusion
            else:
                result[api_name] = row.config.level
        return result
    
    def get_ship_configs(self) -> list[ShipConfig]:
        """Get list of all ShipConfig objects."""
        return [row.config for row in self._ship_rows.values()]
    
    def update_from_user_config(self, user_config: UserConfig) -> None:
        """Update all ship rows from a UserConfig."""
        for api_name, row in self._ship_rows.items():
            level = user_config.missions.get(api_name, 0)
            excluded = level < 0
            actual_level = max(0, level)
            
            config = ShipConfig.from_metadata(api_name, level=actual_level, excluded=excluded)
            row.update_from_config(config)
