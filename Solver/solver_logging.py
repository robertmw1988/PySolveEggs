"""
Comprehensive logging for the mission solver.

Provides detailed insight into solver behavior at multiple verbosity levels:
    - MINIMAL: Only final results and errors
    - SUMMARY: Configuration overview and key metrics
    - DETAILED: Coefficient tables, constraint details
    - DEBUG: Full solver iterations and all internal state
    - TRACE: Everything including per-artifact calculations

Usage:
    from Solver.solver_logging import SolverLogger, LogLevel
    
    logger = SolverLogger(level=LogLevel.DETAILED)
    logger.log_config(user_config)
    logger.log_objective_coefficients(...)
    # ... use throughout solve()
    logger.log_solution(result)
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TextIO, Tuple, Union

from .config import CostWeights, Constraints, EpicResearch, UserConfig


class LogLevel(IntEnum):
    """Verbosity levels for solver logging."""
    SILENT = 0      # No output at all
    MINIMAL = 10    # Only final results and errors
    SUMMARY = 20    # Configuration overview and key metrics
    DETAILED = 30   # Coefficient tables, constraint details
    DEBUG = 40      # Full solver iterations and internal state
    TRACE = 50      # Everything including per-artifact calculations


@dataclass
class LogEntry:
    """A single log entry with metadata."""
    timestamp: datetime
    level: LogLevel
    category: str
    message: str
    data: Optional[Dict[str, Any]] = None
    
    def format(self, include_timestamp: bool = True, include_level: bool = True) -> str:
        """Format the log entry as a string."""
        parts = []
        if include_timestamp:
            parts.append(f"[{self.timestamp.strftime('%H:%M:%S.%f')[:-3]}]")
        if include_level:
            parts.append(f"[{self.level.name:8}]")
        parts.append(f"[{self.category}]")
        parts.append(self.message)
        return " ".join(parts)


@dataclass
class SolverLogger:
    """
    Structured logger for the mission solver.
    
    Collects log entries at various verbosity levels and can output
    to multiple destinations (console, file, string buffer).
    
    Attributes
    ----------
    level : LogLevel
        Minimum level to log (entries below this level are ignored)
    output : TextIO | None
        Output stream (defaults to sys.stdout)
    log_to_file : Path | None
        Optional path to also write logs to a file
    entries : list[LogEntry]
        All logged entries (for programmatic access)
    """
    level: LogLevel = LogLevel.SUMMARY
    output: Optional[TextIO] = None
    log_to_file: Optional[Path] = None
    include_timestamp: bool = True
    include_level: bool = True
    entries: List[LogEntry] = field(default_factory=list)
    _file_handle: Optional[TextIO] = field(default=None, repr=False)
    
    def __post_init__(self):
        if self.output is None:
            self.output = sys.stdout
        if self.log_to_file:
            self._file_handle = open(self.log_to_file, "w", encoding="utf-8")
    
    def close(self):
        """Close the file handle if opened."""
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
    
    def _log(self, level: LogLevel, category: str, message: str, 
             data: Optional[Dict[str, Any]] = None) -> None:
        """Internal method to record and output a log entry."""
        if level > self.level:
            return
        
        entry = LogEntry(
            timestamp=datetime.now(),
            level=level,
            category=category,
            message=message,
            data=data,
        )
        self.entries.append(entry)
        
        formatted = entry.format(self.include_timestamp, self.include_level)
        if self.output:
            self.output.write(formatted + "\n")
            self.output.flush()
        if self._file_handle:
            self._file_handle.write(formatted + "\n")
            self._file_handle.flush()
    
    def _log_table(self, level: LogLevel, category: str, 
                   headers: List[str], rows: List[List[Any]], 
                   title: Optional[str] = None) -> None:
        """Log a formatted table."""
        if level > self.level:
            return
        
        # Calculate column widths
        all_rows = [headers] + rows
        widths = [max(len(str(row[i])) for row in all_rows) for i in range(len(headers))]
        
        # Format
        lines = []
        if title:
            lines.append(title)
            lines.append("=" * len(title))
        
        # Header
        header_line = " | ".join(str(h).ljust(w) for h, w in zip(headers, widths))
        lines.append(header_line)
        lines.append("-" * len(header_line))
        
        # Rows
        for row in rows:
            row_line = " | ".join(str(v).ljust(w) for v, w in zip(row, widths))
            lines.append(row_line)
        
        for line in lines:
            self._log(level, category, line)
    
    # -------------------------------------------------------------------------
    # Configuration Logging
    # -------------------------------------------------------------------------
    
    def log_config_start(self, config: UserConfig, num_ships: int) -> None:
        """Log the start of a solve with configuration summary."""
        self._log(LogLevel.MINIMAL, "SOLVER", 
                  f"Starting solve with {num_ships} ships")
        
        if self.level >= LogLevel.SUMMARY:
            self._log(LogLevel.SUMMARY, "CONFIG", 
                      f"Fuel tank: {config.constraints.fuel_tank_capacity:.1f}T, "
                      f"Max time: {config.constraints.max_time_hours:.1f}h")
            
            # Count active ships
            active_ships = [s for s, lvl in config.missions.items() if lvl > 0]
            self._log(LogLevel.SUMMARY, "CONFIG", 
                      f"Active ships: {len(active_ships)} ({', '.join(active_ships)})")
    
    def log_cost_weights(self, weights: CostWeights) -> None:
        """Log the cost function weights."""
        self._log(LogLevel.SUMMARY, "WEIGHTS", 
                  f"Cost weights - Time: {weights.mission_time:.2f}, "
                  f"Fuel: {weights.fuel_efficiency:.2f}, "
                  f"Artifact: {weights.artifact_gain:.2f}, "
                  f"Slack: {weights.slack_penalty:.2f}")
    
    def log_epic_research(self, epic: Dict[str, EpicResearch]) -> None:
        """Log epic research settings."""
        if self.level < LogLevel.DETAILED:
            return
        
        rows = []
        for name, research in epic.items():
            rows.append([name, research.level, research.max_level, 
                        f"{research.effect * 100:.1f}%"])
        
        if rows:
            self._log_table(LogLevel.DETAILED, "RESEARCH",
                           ["Research", "Level", "Max", "Effect/Level"],
                           rows, title="Epic Research Configuration")
    
    def log_artifact_weights(self, weights: Dict[str, float], 
                             category: str = "Mission") -> None:
        """Log artifact weight configuration."""
        if self.level < LogLevel.DETAILED:
            return
        
        # Group by weight value for compact display
        by_weight: Dict[float, List[str]] = {}
        for art, w in weights.items():
            by_weight.setdefault(w, []).append(art)
        
        self._log(LogLevel.DETAILED, "WEIGHTS", 
                  f"{category} artifact weights ({len(weights)} artifacts):")
        
        for w in sorted(by_weight.keys(), reverse=True):
            arts = by_weight[w]
            if len(arts) <= 5:
                self._log(LogLevel.DETAILED, "WEIGHTS", 
                          f"  {w:+.2f}: {', '.join(arts)}")
            else:
                self._log(LogLevel.DETAILED, "WEIGHTS", 
                          f"  {w:+.2f}: {len(arts)} artifacts")
        
        # At TRACE level, list all artifacts
        if self.level >= LogLevel.TRACE:
            for art, w in sorted(weights.items()):
                self._log(LogLevel.TRACE, "WEIGHTS", f"    {art}: {w:+.2f}")
    
    # -------------------------------------------------------------------------
    # Mission Inventory Logging
    # -------------------------------------------------------------------------
    
    def log_inventory_built(self, inventory_count: int, 
                            filtered_count: int) -> None:
        """Log mission inventory construction."""
        self._log(LogLevel.SUMMARY, "INVENTORY", 
                  f"Built inventory: {inventory_count} total missions, "
                  f"{filtered_count} after level filtering")
    
    def log_mission_details(self, missions: List[Any], 
                           effective_caps: List[int],
                           effective_secs: List[int]) -> None:
        """Log detailed mission information."""
        if self.level < LogLevel.DETAILED:
            return
        
        rows = []
        for i, m in enumerate(missions):
            rows.append([
                i,
                m.ship,
                m.duration_type,
                effective_caps[i],
                f"{effective_secs[i] / 3600:.1f}h",
                f"{sum(m.fuel_requirements.values()) / 1e12:.2f}T",
            ])
        
        self._log_table(LogLevel.DETAILED, "MISSIONS",
                       ["#", "Ship", "Duration", "Capacity", "Time", "Fuel"],
                       rows, title="Mission Inventory")
    
    # -------------------------------------------------------------------------
    # Objective Function Logging
    # -------------------------------------------------------------------------
    
    def log_objective_start(self) -> None:
        """Log the start of objective function construction."""
        self._log(LogLevel.DETAILED, "OBJECTIVE", 
                  "Building objective function...")
    
    def log_objective_mission_contribution(
        self, 
        mission_idx: int,
        mission_name: str,
        positive_value: float,
        time_penalty: float,
        slack_penalty: float,
        total_contrib: float,
    ) -> None:
        """Log the objective contribution for a single mission."""
        if self.level < LogLevel.DEBUG:
            return
        
        self._log(LogLevel.DEBUG, "OBJECTIVE", 
                  f"Mission {mission_idx} ({mission_name}): "
                  f"artifact_value={positive_value:+.4f}, "
                  f"time_penalty={time_penalty:-.4f}, "
                  f"slack_penalty={slack_penalty:-.4f}, "
                  f"total={total_contrib:+.4f}")
    
    def log_objective_artifact_detail(
        self,
        mission_idx: int,
        artifact: str,
        ratio: float,
        expected_drops: float,
        weight: float,
        contribution: float,
    ) -> None:
        """Log per-artifact contribution to objective (TRACE level)."""
        if self.level < LogLevel.TRACE:
            return
        
        tag = "SLACK" if weight <= 0 else "VALUE"
        self._log(LogLevel.TRACE, "OBJECTIVE", 
                  f"  [{tag}] {artifact}: ratio={ratio:.4f}, "
                  f"expected={expected_drops:.2f}, weight={weight:+.2f}, "
                  f"contrib={contribution:+.4f}")
    
    def log_objective_summary(self, coefficients: List[float]) -> None:
        """Log summary of objective coefficients."""
        if self.level < LogLevel.DETAILED:
            return
        
        pos_count = sum(1 for c in coefficients if c > 0)
        neg_count = sum(1 for c in coefficients if c < 0)
        zero_count = sum(1 for c in coefficients if c == 0)
        
        self._log(LogLevel.DETAILED, "OBJECTIVE", 
                  f"Objective coefficients: {len(coefficients)} total, "
                  f"{pos_count} positive, {neg_count} negative, {zero_count} zero")
        
        if coefficients:
            self._log(LogLevel.DETAILED, "OBJECTIVE", 
                      f"Coefficient range: [{min(coefficients):.4f}, "
                      f"{max(coefficients):.4f}]")
    
    def log_objective_coefficients_table(
        self,
        missions: List[Any],
        coefficients: List[float],
        components: Optional[List[Dict[str, float]]] = None,
    ) -> None:
        """Log full table of objective coefficients."""
        if self.level < LogLevel.DEBUG:
            return
        
        rows = []
        for i, (m, coef) in enumerate(zip(missions, coefficients)):
            row = [i, m.ship, m.duration_type, f"{coef:+.4f}"]
            if components:
                comp = components[i]
                row.extend([
                    f"{comp.get('artifact_value', 0):+.4f}",
                    f"{comp.get('fuel_bonus', 0):+.4f}",
                    f"{comp.get('time_penalty', 0):-.4f}",
                    f"{comp.get('slack_penalty', 0):-.4f}",
                ])
            rows.append(row)
        
        headers = ["#", "Ship", "Duration", "Total"]
        if components:
            headers.extend(["ArtifactVal", "FuelBonus", "TimePen", "SlackPen"])
        
        self._log_table(LogLevel.DEBUG, "OBJECTIVE", headers, rows,
                       title="Objective Coefficients by Mission")
    
    # -------------------------------------------------------------------------
    # Constraint Logging
    # -------------------------------------------------------------------------
    
    def log_constraints_start(self) -> None:
        """Log the start of constraint construction."""
        self._log(LogLevel.DETAILED, "CONSTRAINTS", "Building constraints...")
    
    def log_constraint_added(self, name: str, 
                            description: str,
                            rhs_value: float) -> None:
        """Log a constraint being added to the problem."""
        self._log(LogLevel.DETAILED, "CONSTRAINTS", 
                  f"Added: {name} - {description} (RHS={rhs_value})")
    
    def log_fuel_coefficients(self, fuel_coeffs: Dict[str, List[float]]) -> None:
        """Log fuel consumption coefficients."""
        if self.level < LogLevel.DEBUG:
            return
        
        for egg, coeffs in fuel_coeffs.items():
            nonzero = [(i, c) for i, c in enumerate(coeffs) if c > 0]
            self._log(LogLevel.DEBUG, "FUEL", 
                      f"{egg}: {len(nonzero)} missions use this fuel")
            for i, c in nonzero:
                self._log(LogLevel.TRACE, "FUEL", 
                          f"  Mission {i}: {c / 1e12:.2f}T")
    
    # -------------------------------------------------------------------------
    # Solver Execution Logging
    # -------------------------------------------------------------------------
    
    def log_solver_start(self, solver_name: str, msg_enabled: bool) -> None:
        """Log solver invocation."""
        self._log(LogLevel.SUMMARY, "SOLVER", 
                  f"Invoking {solver_name} (verbose={msg_enabled})")
    
    def log_solver_iteration(self, iteration: int, 
                            objective: float,
                            bound: float,
                            gap: float) -> None:
        """Log a solver iteration (if solver provides callbacks)."""
        if self.level < LogLevel.DEBUG:
            return
        
        self._log(LogLevel.DEBUG, "SOLVER", 
                  f"Iter {iteration}: obj={objective:.4f}, "
                  f"bound={bound:.4f}, gap={gap:.2%}")
    
    def log_solver_complete(self, status: str, 
                           objective_value: float,
                           solve_time_ms: float) -> None:
        """Log solver completion."""
        self._log(LogLevel.SUMMARY, "SOLVER", 
                  f"Solver complete: status={status}, "
                  f"objective={objective_value:.4f}, "
                  f"time={solve_time_ms:.1f}ms")
    
    # -------------------------------------------------------------------------
    # Solution Logging
    # -------------------------------------------------------------------------
    
    def log_solution_summary(
        self,
        status: str,
        num_selected: int,
        total_time_hours: float,
        fuel_usage_tank: float,
        objective_value: float,
    ) -> None:
        """Log solution summary."""
        self._log(LogLevel.MINIMAL, "SOLUTION", 
                  f"Status: {status}, Selected: {num_selected} missions, "
                  f"Time: {total_time_hours:.1f}h, "
                  f"Tank fuel: {fuel_usage_tank / 1e12:.2f}T")
        
        self._log(LogLevel.SUMMARY, "SOLUTION", 
                  f"Objective value: {objective_value:.4f}")
    
    def log_selected_missions(
        self,
        selected: List[Tuple[Any, int]],
        capacities: List[int],
    ) -> None:
        """Log details of selected missions."""
        if self.level < LogLevel.DETAILED:
            return
        
        rows = []
        for idx, (mission, count) in enumerate(selected):
            cap = capacities[idx] if idx < len(capacities) else 0
            total_artifacts = cap * count
            rows.append([
                mission.ship,
                mission.duration_type,
                count,
                cap,
                total_artifacts,
            ])
        
        self._log_table(LogLevel.DETAILED, "SOLUTION",
                       ["Ship", "Duration", "Count", "Capacity", "Total Artifacts"],
                       rows, title="Selected Missions")
    
    def log_expected_drops(
        self,
        drops: Dict[str, float],
        weights: Dict[str, float],
        top_n: int = 20,
    ) -> None:
        """Log expected artifact drops."""
        if self.level < LogLevel.DETAILED:
            return
        
        # Sort by quantity
        sorted_drops = sorted(drops.items(), key=lambda x: -x[1])
        
        rows = []
        for art, qty in sorted_drops[:top_n]:
            w = weights.get(art, 1.0)
            tag = "SLACK" if w <= 0 else ""
            rows.append([art, f"{qty:.2f}", f"{w:+.2f}", tag])
        
        if len(sorted_drops) > top_n:
            rows.append(["...", f"({len(sorted_drops) - top_n} more)", "", ""])
        
        self._log_table(LogLevel.DETAILED, "DROPS",
                       ["Artifact", "Expected", "Weight", "Status"],
                       rows, title="Expected Artifact Drops")
    
    def log_slack_analysis(
        self,
        slack_drops: Dict[str, float],
        slack_fuel_cost: float,
    ) -> None:
        """Log analysis of slack (unwanted) artifacts."""
        if not slack_drops:
            self._log(LogLevel.SUMMARY, "SLACK", "No slack artifacts in solution")
            return
        
        total_slack = sum(slack_drops.values())
        self._log(LogLevel.SUMMARY, "SLACK", 
                  f"Slack artifacts: {total_slack:.1f} total, "
                  f"fuel cost: {slack_fuel_cost / 1e12:.2f}T")
        
        if self.level >= LogLevel.DETAILED:
            rows = [[art, f"{qty:.2f}"] 
                    for art, qty in sorted(slack_drops.items(), key=lambda x: -x[1])]
            self._log_table(LogLevel.DETAILED, "SLACK",
                           ["Artifact", "Expected"],
                           rows, title="Slack (Unwanted) Artifacts")
    
    def log_bom_rollup(self, rollup: Any) -> None:
        """Log BOM rollup results."""
        if rollup is None or self.level < LogLevel.DETAILED:
            return
        
        # RollupResult uses 'crafted' attribute (Dict[str, float])
        crafted = getattr(rollup, 'crafted', {})
        consumed = getattr(rollup, 'consumed', {})
        shortfall = getattr(rollup, 'shortfall', {})
        
        self._log(LogLevel.DETAILED, "BOM", 
                  f"BOM rollup: {len(crafted)} items crafted, "
                  f"{len(consumed)} ingredients consumed")
        
        if shortfall:
            self._log(LogLevel.DETAILED, "BOM",
                      f"WARNING: {len(shortfall)} items had shortfall")
        
        if self.level >= LogLevel.DEBUG and crafted:
            rows = [[item_id, f"{qty:.2f}"] 
                    for item_id, qty in sorted(crafted.items(), 
                                               key=lambda x: -x[1])]
            if rows:
                self._log_table(LogLevel.DEBUG, "BOM",
                               ["Crafted Item ID", "Quantity"],
                               rows[:20], title="Crafted Artifacts")
        
        if self.level >= LogLevel.TRACE:
            if consumed:
                rows = [[item_id, f"{qty:.2f}"] 
                        for item_id, qty in sorted(consumed.items(), 
                                                   key=lambda x: -x[1])]
                self._log_table(LogLevel.TRACE, "BOM",
                               ["Consumed Ingredient ID", "Quantity"],
                               rows[:30], title="Consumed Ingredients")
            
            if shortfall:
                rows = [[item_id, f"{qty:.2f}"] 
                        for item_id, qty in sorted(shortfall.items(), 
                                                   key=lambda x: -x[1])]
                self._log_table(LogLevel.TRACE, "BOM",
                               ["Item ID", "Shortfall"],
                               rows, title="Ingredient Shortfalls")
    
    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------
    
    def get_all_entries(self) -> List[LogEntry]:
        """Return all logged entries."""
        return self.entries.copy()
    
    def get_entries_by_level(self, level: LogLevel) -> List[LogEntry]:
        """Return entries at or below a specific level."""
        return [e for e in self.entries if e.level <= level]
    
    def get_entries_by_category(self, category: str) -> List[LogEntry]:
        """Return entries matching a category."""
        return [e for e in self.entries if e.category == category]
    
    def to_string(self, level: Optional[LogLevel] = None) -> str:
        """Format all entries to a string."""
        entries = self.entries if level is None else self.get_entries_by_level(level)
        return "\n".join(e.format(self.include_timestamp, self.include_level) 
                        for e in entries)
    
    def clear(self) -> None:
        """Clear all logged entries."""
        self.entries.clear()


def create_logger(
    level: Union[LogLevel, str, int] = LogLevel.SUMMARY,
    output: Optional[TextIO] = None,
    log_file: Optional[Path] = None,
) -> SolverLogger:
    """
    Factory function to create a SolverLogger.
    
    Parameters
    ----------
    level : LogLevel | str | int
        Verbosity level. Can be LogLevel enum, string name, or integer.
    output : TextIO | None
        Output stream. Defaults to sys.stdout.
    log_file : Path | None
        Optional path to write logs to file.
    
    Returns
    -------
    SolverLogger
        Configured logger instance
    """
    if isinstance(level, str):
        level = LogLevel[level.upper()]
    elif isinstance(level, int) and not isinstance(level, LogLevel):
        level = LogLevel(level)
    
    return SolverLogger(
        level=level,
        output=output,
        log_to_file=log_file,
    )


def create_string_logger(level: LogLevel = LogLevel.DETAILED) -> Tuple[SolverLogger, StringIO]:
    """
    Create a logger that writes to a string buffer.
    
    Useful for testing or capturing logs programmatically.
    
    Returns
    -------
    tuple[SolverLogger, StringIO]
        The logger and the buffer it writes to
    """
    buffer = StringIO()
    logger = SolverLogger(level=level, output=buffer)
    return logger, buffer
