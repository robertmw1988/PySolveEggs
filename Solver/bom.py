"""Bill of Materials (BOM) rollup engine for artifact crafting.

This module provides functionality to:
1. Load recipe data from eiafx-data.json
2. Build a dependency graph for crafting
3. Flatten BOM requirements using topological sort
4. Roll up inventory based on crafting priorities with shared ingredient allocation
5. Handle partial crafts when ingredients are insufficient
"""
from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

# Paths
BASE_DIR = Path(__file__).resolve().parent
WASMEGG_DIR = BASE_DIR.parent / "Wasmegg"
EIAFX_DATA_PATH = WASMEGG_DIR / "eiafx-data.json"

# Minimum ingredient threshold for partial crafts
DEFAULT_INGREDIENT_THRESHOLD = 0.001

# Rarity suffixes used in display names
RARITY_SUFFIXES = frozenset({"(Rare)", "(Epic)", "(Legendary)"})


@dataclass
class Recipe:
    """Represents a crafting recipe for an artifact tier."""
    artifact_id: str
    artifact_name: str
    ingredients: List[Tuple[str, str, int]]  # [(id, name, count), ...]
    
    def __hash__(self) -> int:
        return hash(self.artifact_id)
    

@dataclass
class BOMRequirement:
    """Represents total requirements for a single ingredient after BOM expansion."""
    artifact_id: str
    artifact_name: str
    quantity: float
    is_base_ingredient: bool = False  # True if this is a non-craftable base material


@dataclass
class RollupResult:
    """Result of a BOM rollup operation."""
    # Artifacts successfully crafted (id -> quantity)
    crafted: Dict[str, float] = field(default_factory=dict)
    # Base ingredients consumed (id -> quantity)
    consumed: Dict[str, float] = field(default_factory=dict)
    # Remaining inventory after rollup (id -> quantity)
    remaining: Dict[str, float] = field(default_factory=dict)
    # Shortfall for ingredients that were insufficient (id -> shortfall amount)
    shortfall: Dict[str, float] = field(default_factory=dict)
    # Partial craft progress (target_id -> fraction completed toward next craft)
    partial_progress: Dict[str, float] = field(default_factory=dict)


class BOMEngine:
    """
    Bill of Materials engine for artifact crafting.
    
    Loads recipe data, builds dependency graphs, and performs BOM rollup
    calculations with priority-based allocation of shared ingredients.
    """
    
    def __init__(self, data_path: Optional[Path] = None):
        """
        Initialize the BOM engine.
        
        Parameters
        ----------
        data_path : Path, optional
            Path to eiafx-data.json. Defaults to Wasmegg/eiafx-data.json.
        """
        self._data_path = data_path or EIAFX_DATA_PATH
        self._recipes: Dict[str, Recipe] = {}  # artifact_id -> Recipe
        self._id_to_name: Dict[str, str] = {}  # artifact_id -> display name
        self._name_to_id: Dict[str, str] = {}  # display name -> artifact_id
        self._base_name_to_id: Dict[str, str] = {}  # base name (no rarity) -> artifact_id
        self._craftable: Set[str] = set()  # set of craftable artifact IDs
        self._dependencies: Dict[str, List[str]] = {}  # artifact_id -> [dependency_ids]
        self._dependents: Dict[str, List[str]] = {}  # artifact_id -> [dependent_ids]
        
        self._load_data()
        self._build_dependency_graph()
    
    def _load_data(self) -> None:
        """Load recipe data from eiafx-data.json."""
        if not self._data_path.exists():
            raise FileNotFoundError(f"eiafx-data.json not found at {self._data_path}")
        
        with self._data_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        
        artifact_families = data.get("artifact_families", [])
        
        for family in artifact_families:
            tiers = family.get("tiers", [])
            for tier in tiers:
                artifact_id = tier.get("id", "")
                artifact_name = tier.get("name", "")
                craftable = tier.get("craftable", False)
                
                if not artifact_id:
                    continue
                
                # Store name mappings
                self._id_to_name[artifact_id] = artifact_name
                self._name_to_id[artifact_name] = artifact_id
                self._base_name_to_id[artifact_name] = artifact_id
                
                # Also map rarity variants to the same base ID
                for rarity in ["Rare", "Epic", "Legendary"]:
                    rarity_name = f"{artifact_name} ({rarity})"
                    self._name_to_id[rarity_name] = artifact_id
                
                if craftable:
                    self._craftable.add(artifact_id)
                    recipe_data = tier.get("recipe")
                    if recipe_data:
                        ingredients = []
                        for ing in recipe_data.get("ingredients", []):
                            ing_id = ing.get("id", "")
                            ing_name = ing.get("name", "")
                            ing_count = ing.get("count", 0)
                            if ing_id and ing_count > 0:
                                ingredients.append((ing_id, ing_name, ing_count))
                        
                        self._recipes[artifact_id] = Recipe(
                            artifact_id=artifact_id,
                            artifact_name=artifact_name,
                            ingredients=ingredients,
                        )
    
    def _build_dependency_graph(self) -> None:
        """Build the dependency graph from recipes."""
        for artifact_id, recipe in self._recipes.items():
            deps = [ing_id for ing_id, _, _ in recipe.ingredients]
            self._dependencies[artifact_id] = deps
            
            for dep_id in deps:
                if dep_id not in self._dependents:
                    self._dependents[dep_id] = []
                self._dependents[dep_id].append(artifact_id)
    
    def get_recipe(self, artifact_id: str) -> Optional[Recipe]:
        """Get the recipe for an artifact by ID."""
        return self._recipes.get(artifact_id)
    
    def is_craftable(self, artifact_id: str) -> bool:
        """Check if an artifact is craftable."""
        return artifact_id in self._craftable
    
    def name_to_id(self, display_name: str) -> Optional[str]:
        """Convert a display name (with optional rarity) to artifact ID."""
        return self._name_to_id.get(display_name)
    
    def id_to_name(self, artifact_id: str) -> Optional[str]:
        """Convert an artifact ID to its display name."""
        return self._id_to_name.get(artifact_id)
    
    def strip_rarity(self, display_name: str) -> str:
        """
        Strip rarity suffix from a display name.
        
        Examples:
            "Puzzle cube (Epic)" -> "Puzzle cube"
            "Ancient puzzle cube" -> "Ancient puzzle cube"
        """
        for suffix in RARITY_SUFFIXES:
            if display_name.endswith(suffix):
                return display_name[: -len(suffix)].rstrip()
        return display_name
    
    def normalize_inventory(
        self,
        inventory: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Normalize inventory by aggregating rarity variants to base artifact IDs.
        
        All rarities are treated as equivalent (demoted to common) for crafting.
        
        Parameters
        ----------
        inventory : dict
            Mapping of display name -> quantity (may include rarity variants)
        
        Returns
        -------
        dict
            Mapping of artifact_id -> aggregated quantity
        """
        normalized: Dict[str, float] = defaultdict(float)
        
        for name, qty in inventory.items():
            if qty <= 0:
                continue
            
            # Try direct lookup first
            artifact_id = self._name_to_id.get(name)
            if artifact_id:
                normalized[artifact_id] += qty
            else:
                # Try stripping rarity and looking up
                base_name = self.strip_rarity(name)
                artifact_id = self._base_name_to_id.get(base_name)
                if artifact_id:
                    normalized[artifact_id] += qty
        
        return dict(normalized)
    
    def topological_sort(self, target_ids: Set[str]) -> List[str]:
        """
        Perform topological sort on target artifacts and their dependencies.
        
        Returns artifacts in order from leaves (base ingredients) to roots (final targets).
        This ensures we process dependencies before dependents during rollup.
        
        Parameters
        ----------
        target_ids : set
            Set of artifact IDs to include in the sort
        
        Returns
        -------
        list
            Artifact IDs in topologically sorted order (dependencies first)
        """
        # Collect all nodes needed (targets and their transitive dependencies)
        all_nodes: Set[str] = set()
        queue = deque(target_ids)
        
        while queue:
            node = queue.popleft()
            if node in all_nodes:
                continue
            all_nodes.add(node)
            
            # Add dependencies
            for dep_id in self._dependencies.get(node, []):
                if dep_id not in all_nodes:
                    queue.append(dep_id)
        
        # Kahn's algorithm for topological sort
        # Build in-degree map (only for nodes in our subgraph)
        in_degree: Dict[str, int] = {node: 0 for node in all_nodes}
        for node in all_nodes:
            for dep_id in self._dependencies.get(node, []):
                if dep_id in all_nodes:
                    in_degree[node] += 1
        
        # Start with nodes that have no dependencies
        ready = deque([node for node, degree in in_degree.items() if degree == 0])
        sorted_order: List[str] = []
        
        while ready:
            node = ready.popleft()
            sorted_order.append(node)
            
            # Reduce in-degree for dependents
            for dependent in self._dependents.get(node, []):
                if dependent in in_degree:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        ready.append(dependent)
        
        return sorted_order
    
    def flatten_bom(
        self,
        artifact_id: str,
        quantity: float = 1.0,
    ) -> Dict[str, float]:
        """
        Flatten the BOM for a single artifact, returning total base ingredient requirements.
        
        Recursively expands the recipe tree to find all base (non-craftable) ingredients.
        
        Parameters
        ----------
        artifact_id : str
            The artifact ID to expand
        quantity : float
            Number of artifacts to craft
        
        Returns
        -------
        dict
            Mapping of base ingredient ID -> total quantity required
        """
        requirements: Dict[str, float] = defaultdict(float)
        
        # Use iterative approach with stack to avoid recursion limits
        stack: List[Tuple[str, float]] = [(artifact_id, quantity)]
        
        while stack:
            current_id, current_qty = stack.pop()
            
            recipe = self._recipes.get(current_id)
            if not recipe:
                # Base ingredient (not craftable)
                requirements[current_id] += current_qty
                continue
            
            # Expand recipe
            for ing_id, _, ing_count in recipe.ingredients:
                needed = current_qty * ing_count
                stack.append((ing_id, needed))
        
        return dict(requirements)
    
    def calculate_craft_ratios(
        self,
        crafting_weights: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Calculate crafting priority ratios from weights.
        
        Only includes artifacts with weight > 0 (artifacts with <= 0 are ingredient-only).
        Ratios are normalized so they sum to 1.0 within each shared ingredient group.
        
        Parameters
        ----------
        crafting_weights : dict
            Mapping of display name -> weight (from craftedArtifactTargetWeights)
        
        Returns
        -------
        dict
            Mapping of artifact_id -> normalized priority ratio
        """
        # Convert to IDs and filter out non-positive weights
        id_weights: Dict[str, float] = {}
        for name, weight in crafting_weights.items():
            if weight <= 0:
                continue
            artifact_id = self._name_to_id.get(name)
            if artifact_id and artifact_id in self._craftable:
                # Aggregate weights across rarities to the same ID
                if artifact_id not in id_weights:
                    id_weights[artifact_id] = 0.0
                id_weights[artifact_id] = max(id_weights[artifact_id], weight)
        
        # Normalize to sum to 1.0
        total = sum(id_weights.values())
        if total <= 0:
            return {}
        
        return {k: v / total for k, v in id_weights.items()}
    
    def rollup(
        self,
        inventory: Dict[str, float],
        crafting_weights: Dict[str, float],
        ingredient_threshold: float = DEFAULT_INGREDIENT_THRESHOLD,
    ) -> RollupResult:
        """
        Perform BOM rollup on inventory based on crafting priorities.
        
        This is the main rollup function that:
        1. Normalizes inventory (aggregates rarities)
        2. Determines target artifacts based on weights (weight > 0)
        3. Processes artifacts in topological order (dependencies first)
        4. Allocates shared ingredients proportionally by weight
        5. Handles partial crafts when ingredients are insufficient
        
        Parameters
        ----------
        inventory : dict
            Current inventory as display_name -> quantity
        crafting_weights : dict
            Crafting priorities as display_name -> weight
            Artifacts with weight <= 0 are NOT crafted, only used as ingredients
        ingredient_threshold : float
            Minimum ingredient quantity to consider for crafting (default 0.001)
            Below this threshold, crafting is skipped and remaining is recorded
        
        Returns
        -------
        RollupResult
            Contains crafted quantities, consumed ingredients, remaining inventory,
            shortfalls, and partial craft progress
        """
        result = RollupResult()
        
        # Normalize inventory to artifact IDs
        working_inv = self.normalize_inventory(inventory)
        
        # Get craft targets (weight > 0) and their ratios
        craft_ratios = self.calculate_craft_ratios(crafting_weights)
        if not craft_ratios:
            # Nothing to craft, return inventory as-is
            result.remaining = working_inv.copy()
            return result
        
        target_ids = set(craft_ratios.keys())
        
        # Get topological order (dependencies first)
        sorted_ids = self.topological_sort(target_ids)
        
        # Reverse so we process from highest tier down
        # This ensures we craft high-tier items first, consuming lower tiers
        sorted_ids = sorted_ids[::-1]
        
        # Track what we need to consume for each target
        # Key insight: we iterate in priority order and allocate ingredients
        # proportionally among competing targets
        
        # First pass: identify all ingredient demands by artifact
        demands: Dict[str, Dict[str, float]] = {}  # target_id -> {ingredient_id -> qty needed per craft}
        for target_id in sorted_ids:
            if target_id not in target_ids:
                continue
            recipe = self._recipes.get(target_id)
            if recipe:
                demands[target_id] = {
                    ing_id: float(ing_count)
                    for ing_id, _, ing_count in recipe.ingredients
                }
        
        # Second pass: calculate how many crafts we can do, respecting shared ingredients
        crafts_possible: Dict[str, float] = {}
        
        # Group targets by shared ingredients
        ingredient_users: Dict[str, List[str]] = defaultdict(list)  # ingredient_id -> [target_ids using it]
        for target_id, recipe_demands in demands.items():
            for ing_id in recipe_demands:
                ingredient_users[ing_id].append(target_id)
        
        # For each target, calculate theoretical max crafts from inventory
        for target_id in demands:
            recipe = self._recipes.get(target_id)
            if not recipe:
                continue
            
            # Maximum crafts limited by least available ingredient
            max_crafts = float("inf")
            for ing_id, _, ing_count in recipe.ingredients:
                available = working_inv.get(ing_id, 0.0)
                if ing_count > 0:
                    possible = available / ing_count
                    max_crafts = min(max_crafts, possible)
            
            if max_crafts == float("inf"):
                max_crafts = 0.0
            
            crafts_possible[target_id] = max_crafts
        
        # Third pass: allocate shared ingredients proportionally
        # Process each shared ingredient and distribute among users by weight
        ingredient_allocation: Dict[str, Dict[str, float]] = defaultdict(dict)  # ingredient_id -> {target_id -> allocated qty}
        
        for ing_id, users in ingredient_users.items():
            if len(users) <= 1:
                # No sharing, allocate all to single user
                if users:
                    target_id = users[0]
                    ingredient_allocation[ing_id][target_id] = working_inv.get(ing_id, 0.0)
            else:
                # Shared ingredient - distribute by weight
                available = working_inv.get(ing_id, 0.0)
                if available <= ingredient_threshold:
                    continue
                
                # Calculate total weighted demand
                total_weighted_demand = 0.0
                weighted_demands: Dict[str, float] = {}
                
                for target_id in users:
                    if target_id not in craft_ratios:
                        continue
                    ratio = craft_ratios[target_id]
                    per_craft = demands.get(target_id, {}).get(ing_id, 0.0)
                    # Weight by priority and demand
                    weighted_demands[target_id] = ratio * per_craft
                    total_weighted_demand += ratio
                
                if total_weighted_demand <= 0:
                    continue
                
                # Allocate proportionally
                for target_id, weighted_demand in weighted_demands.items():
                    share = craft_ratios.get(target_id, 0.0) / total_weighted_demand
                    ingredient_allocation[ing_id][target_id] = available * share
        
        # Fourth pass: execute crafts with allocated ingredients
        for target_id in sorted_ids:
            if target_id not in target_ids:
                continue
            
            recipe = self._recipes.get(target_id)
            if not recipe:
                continue
            
            # Calculate how many we can craft with allocated ingredients
            max_crafts = float("inf")
            limiting_ingredient = None
            
            for ing_id, _, ing_count in recipe.ingredients:
                if ing_count <= 0:
                    continue
                
                # Check allocation for shared ingredients
                if ing_id in ingredient_allocation:
                    allocated = ingredient_allocation[ing_id].get(target_id, 0.0)
                else:
                    allocated = working_inv.get(ing_id, 0.0)
                
                # Also cap by actual inventory
                allocated = min(allocated, working_inv.get(ing_id, 0.0))
                
                possible = allocated / ing_count
                if possible < max_crafts:
                    max_crafts = possible
                    limiting_ingredient = ing_id
            
            if max_crafts == float("inf"):
                max_crafts = 0.0
            
            # Check threshold
            if max_crafts < ingredient_threshold:
                # Record partial progress if any
                if max_crafts > 0 and limiting_ingredient:
                    result.partial_progress[target_id] = max_crafts
                    # Record shortfall (what's needed for 1 full craft)
                    for ing_id, _, ing_count in recipe.ingredients:
                        available = working_inv.get(ing_id, 0.0)
                        needed_for_one = ing_count
                        if available < needed_for_one:
                            shortfall = needed_for_one - available
                            if shortfall > 0:
                                result.shortfall[ing_id] = result.shortfall.get(ing_id, 0.0) + shortfall
                continue
            
            # Execute the crafts
            crafts = max_crafts  # Use fractional crafts
            
            # Consume ingredients
            for ing_id, _, ing_count in recipe.ingredients:
                consumed = crafts * ing_count
                working_inv[ing_id] = working_inv.get(ing_id, 0.0) - consumed
                result.consumed[ing_id] = result.consumed.get(ing_id, 0.0) + consumed
            
            # Add crafted artifacts to inventory
            working_inv[target_id] = working_inv.get(target_id, 0.0) + crafts
            result.crafted[target_id] = result.crafted.get(target_id, 0.0) + crafts
        
        # Record remaining inventory
        result.remaining = {k: v for k, v in working_inv.items() if v > ingredient_threshold}
        
        return result
    
    def rollup_with_display_names(
        self,
        inventory: Dict[str, float],
        crafting_weights: Dict[str, float],
        ingredient_threshold: float = DEFAULT_INGREDIENT_THRESHOLD,
    ) -> RollupResult:
        """
        Perform BOM rollup and convert result IDs back to display names.
        
        Same as rollup() but returns results keyed by display names instead of IDs.
        """
        result = self.rollup(inventory, crafting_weights, ingredient_threshold)
        
        def to_names(d: Dict[str, float]) -> Dict[str, float]:
            return {
                self._id_to_name.get(k, k): v
                for k, v in d.items()
            }
        
        return RollupResult(
            crafted=to_names(result.crafted),
            consumed=to_names(result.consumed),
            remaining=to_names(result.remaining),
            shortfall=to_names(result.shortfall),
            partial_progress=to_names(result.partial_progress),
        )


# Module-level singleton for convenience
_engine: Optional[BOMEngine] = None


def get_bom_engine() -> BOMEngine:
    """Get or create the singleton BOM engine instance."""
    global _engine
    if _engine is None:
        _engine = BOMEngine()
    return _engine


def flatten_bom(artifact_id: str, quantity: float = 1.0) -> Dict[str, float]:
    """
    Convenience function to flatten BOM for an artifact.
    
    See BOMEngine.flatten_bom for details.
    """
    return get_bom_engine().flatten_bom(artifact_id, quantity)


def rollup_inventory(
    inventory: Dict[str, float],
    crafting_weights: Dict[str, float],
    ingredient_threshold: float = DEFAULT_INGREDIENT_THRESHOLD,
) -> RollupResult:
    """
    Convenience function to perform BOM rollup on inventory.
    
    See BOMEngine.rollup for details.
    """
    return get_bom_engine().rollup(inventory, crafting_weights, ingredient_threshold)


def rollup_missions(
    missions: List[Tuple[str, str, Optional[str], int]],
    crafting_weights: Optional[Dict[str, float]] = None,
    mission_level: int = 0,
    capacity_bonus: float = 0.0,
    ingredient_threshold: float = DEFAULT_INGREDIENT_THRESHOLD,
) -> RollupResult:
    """
    Calculate BOM rollup from a list of mission specifications.
    
    This is the main convenience function for getting a rollup from missions.
    
    Parameters
    ----------
    missions : list of tuples
        Each tuple is (ship, duration, target_artifact, count):
        - ship: Ship name (e.g., "Henerprise", "HENERPRISE", "henerprise")
        - duration: Duration type (e.g., "Short", "SHORT", "Epic")
        - target_artifact: Target artifact filter or None for any
        - count: Number of missions to run
    crafting_weights : dict, optional
        Crafting priorities. If None, uses default weights (all 1.0)
    mission_level : int
        Mission level for capacity calculation (default 0)
    capacity_bonus : float
        Zero-G research bonus (e.g., 0.5 for 50%)
    ingredient_threshold : float
        Minimum quantity to consider for crafting
    
    Returns
    -------
    RollupResult
        BOM rollup results with display names
    
    Examples
    --------
    >>> # Single mission type
    >>> result = rollup_missions([("Henerprise", "Short", "Gold Meteorite", 20)])
    
    >>> # Multiple mission types
    >>> result = rollup_missions([
    ...     ("Henerprise", "Epic", None, 10),
    ...     ("Atreggies", "Short", "Book of Basan", 5),
    ... ])
    
    >>> # With custom weights (only craft certain items)
    >>> weights = {"Solid gold meteorite": 1.0, "Enriched gold meteorite": 0.0}
    >>> result = rollup_missions([("Henerprise", "Short", None, 20)], weights)
    """
    from .mission_data import build_mission_inventory
    
    # Build full inventory to find matching missions
    all_missions = build_mission_inventory()
    
    # Aggregate drops from all specified missions
    total_drops: Dict[str, float] = {}
    
    for ship, duration, target, count in missions:
        # Normalize inputs
        ship_norm = ship.upper().replace(" ", "_")
        duration_norm = duration.upper()
        
        # Find matching mission(s)
        matches = [
            m for m in all_missions
            if m.ship.upper() == ship_norm
            and m.duration_type.upper() == duration_norm
        ]
        
        # Filter by target if specified
        if target:
            target_lower = target.lower()
            matches = [
                m for m in matches
                if m.target_artifact and target_lower in m.target_artifact.lower()
            ]
        
        if not matches:
            # Try friendly name match
            ship_friendly = ship.lower().replace("_", " ")
            matches = [
                m for m in all_missions
                if m.ship_label.lower() == ship_friendly
                and m.duration_type.upper() == duration_norm
            ]
            if target:
                matches = [
                    m for m in matches
                    if m.target_artifact and target_lower in m.target_artifact.lower()
                ]
        
        if not matches:
            print(f"Warning: No mission found for {ship}/{duration}/{target}")
            continue
        
        # Use first match (or aggregate if multiple)
        for mission in matches:
            drops = mission.expected_drops(mission_level, capacity_bonus)
            for art, qty in drops.items():
                total_drops[art] = total_drops.get(art, 0.0) + qty * count
    
    # Use default weights if not provided
    if crafting_weights is None:
        # Default: craft everything with equal weight
        engine = get_bom_engine()
        crafting_weights = {
            engine.id_to_name(art_id): 1.0
            for art_id in engine._craftable
            if engine.id_to_name(art_id)
        }
    
    # Perform rollup
    engine = get_bom_engine()
    return engine.rollup_with_display_names(
        inventory=total_drops,
        crafting_weights=crafting_weights,
        ingredient_threshold=ingredient_threshold,
    )


def rollup_mission(
    ship: str,
    duration: str,
    count: int,
    target: Optional[str] = None,
    crafting_weights: Optional[Dict[str, float]] = None,
    mission_level: int = 0,
    capacity_bonus: float = 0.0,
) -> RollupResult:
    """
    Calculate BOM rollup for a single mission type.
    
    Convenience wrapper around rollup_missions for single mission type.
    
    Parameters
    ----------
    ship : str
        Ship name (e.g., "Henerprise", "HENERPRISE")
    duration : str  
        Duration type (e.g., "Short", "Epic")
    count : int
        Number of missions
    target : str, optional
        Target artifact filter
    crafting_weights : dict, optional
        Crafting priorities
    mission_level : int
        Mission level (default 0)
    capacity_bonus : float
        Zero-G bonus (default 0.0)
    
    Returns
    -------
    RollupResult
    
    Examples
    --------
    >>> result = rollup_mission("Henerprise", "Short", 20, target="Gold Meteorite")
    >>> print(f"Crafted: {result.crafted}")
    """
    return rollup_missions(
        missions=[(ship, duration, target, count)],
        crafting_weights=crafting_weights,
        mission_level=mission_level,
        capacity_bonus=capacity_bonus,
    )


def print_rollup(result: RollupResult, show_remaining: bool = True) -> None:
    """
    Pretty-print a rollup result.
    
    Parameters
    ----------
    result : RollupResult
        The rollup result to display
    show_remaining : bool
        Whether to show remaining inventory (default True)
    """
    print("\n=== BOM Rollup Results ===\n")
    
    if result.crafted:
        print("Crafted:")
        for name, qty in sorted(result.crafted.items(), key=lambda kv: -kv[1]):
            if qty >= 0.001:
                print(f"  {name}: {qty:.3f}")
    else:
        print("Crafted: (none)")
    
    if result.consumed:
        print("\nConsumed as ingredients:")
        for name, qty in sorted(result.consumed.items(), key=lambda kv: -kv[1]):
            if qty >= 0.001:
                print(f"  {name}: {qty:.3f}")
    
    if result.partial_progress:
        print("\nPartial progress:")
        for name, progress in sorted(result.partial_progress.items(), key=lambda kv: -kv[1]):
            print(f"  {name}: {progress*100:.1f}%")
    
    if result.shortfall:
        print("\nShortfall (for next craft):")
        for name, qty in sorted(result.shortfall.items(), key=lambda kv: -kv[1]):
            if qty >= 0.001:
                print(f"  {name}: {qty:.3f} needed")
    
    if show_remaining and result.remaining:
        print("\nRemaining inventory:")
        for name, qty in sorted(result.remaining.items(), key=lambda kv: -kv[1]):
            if qty >= 0.01:
                print(f"  {name}: {qty:.2f}")


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

def _parse_mission_spec(spec: str) -> Tuple[str, str, Optional[str], int]:
    """
    Parse a mission specification string.
    
    Format: "Ship,Duration,Target,Count" or "Ship,Duration,Count"
    
    Examples:
        "Henerprise,Short,Gold Meteorite,20"
        "Henerprise,Epic,10"
        "ATREGGIES,SHORT,Book of Basan,5"
    """
    parts = [p.strip() for p in spec.split(",")]
    
    if len(parts) == 3:
        ship, duration, count_str = parts
        target = None
        count = int(count_str)
    elif len(parts) == 4:
        ship, duration, target, count_str = parts
        count = int(count_str)
    else:
        raise ValueError(
            f"Invalid mission spec: {spec}\n"
            "Expected format: Ship,Duration,Target,Count or Ship,Duration,Count"
        )
    
    return ship, duration, target, count


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for BOM rollup."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Calculate BOM rollup from mission specifications.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m Solver.bom "Henerprise,Short,Gold Meteorite,20"
  python -m Solver.bom "Henerprise,Epic,10" "Atreggies,Short,5"
  python -m Solver.bom --level 8 --bonus 0.5 "Henerprise,Epic,3"
        """,
    )
    parser.add_argument(
        "missions",
        nargs="+",
        help="Mission specs: 'Ship,Duration,Target,Count' or 'Ship,Duration,Count'",
    )
    parser.add_argument(
        "--level", "-l",
        type=int,
        default=0,
        help="Mission level (default: 0)",
    )
    parser.add_argument(
        "--bonus", "-b",
        type=float,
        default=0.0,
        help="Zero-G capacity bonus as decimal (e.g., 0.5 for 50%%)",
    )
    parser.add_argument(
        "--no-remaining",
        action="store_true",
        help="Don't show remaining inventory",
    )
    
    args = parser.parse_args(argv)
    
    # Parse mission specifications
    parsed_missions = []
    for spec in args.missions:
        try:
            parsed_missions.append(_parse_mission_spec(spec))
        except ValueError as e:
            print(f"Error: {e}")
            return 1
    
    # Calculate rollup
    result = rollup_missions(
        missions=parsed_missions,
        mission_level=args.level,
        capacity_bonus=args.bonus,
    )
    
    # Display results
    print_rollup(result, show_remaining=not args.no_remaining)
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
