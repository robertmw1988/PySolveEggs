"""Tests for mission capacity calculations.

Validates that effective capacity matches expected values at different
mission levels and Epic Research configurations.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from typing import Dict, List

from Solver.mission_data import (
    MissionOption,
    build_mission_inventory,
)


# ---------------------------------------------------------------------------
# Load capacity metadata from eiafx-config.json
# ---------------------------------------------------------------------------

WASMEGG_DIR = Path(__file__).resolve().parent.parent.parent / "Wasmegg"
EIAFX_CONFIG_PATH = WASMEGG_DIR / "eiafx-config.json"


def load_capacity_metadata() -> Dict[str, Dict[str, Dict[str, int]]]:
    """
    Load capacity and levelCapacityBump from eiafx-config.json.
    
    Returns dict: ship -> durationType -> {capacity, levelCapacityBump}
    """
    with EIAFX_CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = json.load(f)
    
    result: Dict[str, Dict[str, Dict[str, int]]] = {}
    for entry in config.get("missionParameters", []):
        ship = entry.get("ship")
        if not ship:
            continue
        result[ship] = {}
        for dur in entry.get("durations", []):
            dur_type = dur.get("durationType")
            if dur_type:
                result[ship][dur_type] = {
                    "capacity": dur.get("capacity", 0),
                    "levelCapacityBump": dur.get("levelCapacityBump", 0),
                }
    return result


@pytest.fixture(scope="module")
def capacity_metadata() -> Dict[str, Dict[str, Dict[str, int]]]:
    """Load capacity metadata once per module."""
    return load_capacity_metadata()


@pytest.fixture(scope="module")
def full_inventory() -> List[MissionOption]:
    """Load full mission inventory once per test module."""
    return build_mission_inventory()


# ---------------------------------------------------------------------------
# Tests: Validate base capacity values from metadata
# ---------------------------------------------------------------------------

class TestMetadataCapacity:
    """Verify capacity metadata is loaded correctly."""

    def test_atreggies_epic_base_capacity(self, capacity_metadata):
        """Atreggies EPIC should have base capacity 86."""
        atreggies = capacity_metadata.get("ATREGGIES", {})
        epic = atreggies.get("EPIC", {})
        assert epic.get("capacity") == 86, f"Expected 86, got {epic.get('capacity')}"
        assert epic.get("levelCapacityBump") == 10, f"Expected 10, got {epic.get('levelCapacityBump')}"

    def test_henerprise_epic_base_capacity(self, capacity_metadata):
        """Henerprise EPIC should have base capacity 56."""
        henerprise = capacity_metadata.get("HENERPRISE", {})
        epic = henerprise.get("EPIC", {})
        assert epic.get("capacity") == 56, f"Expected 56, got {epic.get('capacity')}"
        assert epic.get("levelCapacityBump") == 7, f"Expected 7, got {epic.get('levelCapacityBump')}"

    def test_print_all_epic_capacities(self, capacity_metadata):
        """Print all ship EPIC capacities for reference."""
        print("\n" + "=" * 70)
        print("EPIC MISSION BASE CAPACITIES (from eiafx-config.json)")
        print("=" * 70)
        print(f"{'Ship':<25} {'Base Capacity':<15} {'Level Bump':<15}")
        print("-" * 55)
        
        for ship in sorted(capacity_metadata.keys()):
            epic = capacity_metadata[ship].get("EPIC", {})
            if epic:
                print(f"{ship:<25} {epic.get('capacity', 'N/A'):<15} {epic.get('levelCapacityBump', 'N/A'):<15}")


# ---------------------------------------------------------------------------
# Tests: Atreggies capacity at various levels
# ---------------------------------------------------------------------------

class TestAtreggiesCapacity:
    """Validate Atreggies capacity calculations."""

    # Expected capacities for Atreggies EPIC at each mission level
    # Formula: floor((base + level * bump) * (1 + bonus))
    # base=86, bump=10
    ATREGGIES_EPIC_EXPECTED = {
        # (mission_level, capacity_bonus): expected_capacity
        (0, 0.0): 86,    # 86 + 0*10 = 86
        (1, 0.0): 96,    # 86 + 1*10 = 96
        (2, 0.0): 106,   # 86 + 2*10 = 106
        (3, 0.0): 116,   # 86 + 3*10 = 116
        (4, 0.0): 126,   # 86 + 4*10 = 126
        (5, 0.0): 136,   # 86 + 5*10 = 136
        (6, 0.0): 146,   # 86 + 6*10 = 146
        (7, 0.0): 156,   # 86 + 7*10 = 156
        (8, 0.0): 166,   # 86 + 8*10 = 166
        # With max Zero-G research (level 10 * 0.05 = 50% bonus)
        (0, 0.5): 129,   # floor(86 * 1.5) = 129
        (8, 0.5): 249,   # floor(166 * 1.5) = 249 <- THIS IS THE KEY TEST
        # With partial Zero-G research
        (8, 0.25): 207,  # floor(166 * 1.25) = 207.5 -> 207
        (8, 0.10): 182,  # floor(166 * 1.10) = 182.6 -> 182
    }

    @pytest.fixture
    def atreggies_epic_mission(self) -> MissionOption:
        """Create Atreggies EPIC mission option with correct metadata."""
        return MissionOption(
            ship="ATREGGIES",
            ship_label="Atreggies",
            duration_type="EPIC",
            level=0,
            target_artifact=None,
            base_capacity=86,
            level_capacity_bump=10,
            seconds=345600,
            drop_vector={},
        )

    @pytest.mark.parametrize(
        "level,bonus,expected",
        [(k[0], k[1], v) for k, v in ATREGGIES_EPIC_EXPECTED.items()],
        ids=[f"L{k[0]}_bonus{int(k[1]*100)}pct" for k in ATREGGIES_EPIC_EXPECTED.keys()],
    )
    def test_atreggies_capacity(self, atreggies_epic_mission, level, bonus, expected):
        """Test Atreggies capacity at various levels and research bonuses."""
        actual = atreggies_epic_mission.effective_capacity(level, bonus)
        assert actual == expected, (
            f"Atreggies EPIC at level {level} with {bonus:.0%} bonus: "
            f"expected {expected}, got {actual}"
        )

    def test_atreggies_level_8_max_research(self, atreggies_epic_mission):
        """
        CRITICAL TEST: Atreggies Level 8 with max Zero-G research = 249 artifacts.
        
        Formula: floor((86 + 8*10) * 1.5) = floor(166 * 1.5) = floor(249) = 249
        """
        capacity = atreggies_epic_mission.effective_capacity(
            mission_level=8,
            capacity_bonus=0.5,  # Max Zero-G: 10 levels * 5% = 50%
        )
        assert capacity == 249, f"Expected 249 artifacts, got {capacity}"

    def test_print_atreggies_capacity_table(self, atreggies_epic_mission):
        """Print full capacity table for Atreggies EPIC."""
        print("\n" + "=" * 70)
        print("ATREGGIES EPIC CAPACITY TABLE")
        print("Base Capacity: 86, Level Bump: 10")
        print("=" * 70)
        print(f"{'Level':<8} {'No Bonus':<12} {'25% Bonus':<12} {'50% Bonus':<12}")
        print("-" * 44)
        
        for level in range(9):
            cap_0 = atreggies_epic_mission.effective_capacity(level, 0.0)
            cap_25 = atreggies_epic_mission.effective_capacity(level, 0.25)
            cap_50 = atreggies_epic_mission.effective_capacity(level, 0.50)
            print(f"{level:<8} {cap_0:<12} {cap_25:<12} {cap_50:<12}")


# ---------------------------------------------------------------------------
# Tests: Henerprise capacity at various levels
# ---------------------------------------------------------------------------

class TestHenerpriseCapacity:
    """Validate Henerprise capacity calculations."""

    # base=56, bump=7
    HENERPRISE_EPIC_EXPECTED = {
        (0, 0.0): 56,    # 56 + 0*7 = 56
        (8, 0.0): 112,   # 56 + 8*7 = 112
        (0, 0.5): 84,    # floor(56 * 1.5) = 84
        (8, 0.5): 168,   # floor(112 * 1.5) = 168
    }

    @pytest.fixture
    def henerprise_epic_mission(self) -> MissionOption:
        """Create Henerprise EPIC mission option with correct metadata."""
        return MissionOption(
            ship="HENERPRISE",
            ship_label="Henerprise",
            duration_type="EPIC",
            level=0,
            target_artifact=None,
            base_capacity=56,
            level_capacity_bump=7,
            seconds=259200,
            drop_vector={},
        )

    @pytest.mark.parametrize(
        "level,bonus,expected",
        [(k[0], k[1], v) for k, v in HENERPRISE_EPIC_EXPECTED.items()],
        ids=[f"L{k[0]}_bonus{int(k[1]*100)}pct" for k in HENERPRISE_EPIC_EXPECTED.keys()],
    )
    def test_henerprise_capacity(self, henerprise_epic_mission, level, bonus, expected):
        """Test Henerprise capacity at various levels and research bonuses."""
        actual = henerprise_epic_mission.effective_capacity(level, bonus)
        assert actual == expected, (
            f"Henerprise EPIC at level {level} with {bonus:.0%} bonus: "
            f"expected {expected}, got {actual}"
        )

    def test_print_henerprise_capacity_table(self, henerprise_epic_mission):
        """Print full capacity table for Henerprise EPIC."""
        print("\n" + "=" * 70)
        print("HENERPRISE EPIC CAPACITY TABLE")
        print("Base Capacity: 56, Level Bump: 7")
        print("=" * 70)
        print(f"{'Level':<8} {'No Bonus':<12} {'25% Bonus':<12} {'50% Bonus':<12}")
        print("-" * 44)
        
        for level in range(9):
            cap_0 = henerprise_epic_mission.effective_capacity(level, 0.0)
            cap_25 = henerprise_epic_mission.effective_capacity(level, 0.25)
            cap_50 = henerprise_epic_mission.effective_capacity(level, 0.50)
            print(f"{level:<8} {cap_0:<12} {cap_25:<12} {cap_50:<12}")


# ---------------------------------------------------------------------------
# Tests: Verify inventory missions have correct base capacity from metadata
# ---------------------------------------------------------------------------

class TestInventoryCapacityValues:
    """Verify missions built from inventory have correct capacity metadata."""

    def test_atreggies_inventory_has_correct_capacity(self, full_inventory, capacity_metadata):
        """Atreggies missions in inventory should have base_capacity=86."""
        atreggies_epic = [
            m for m in full_inventory
            if m.ship == "ATREGGIES" and m.duration_type == "EPIC"
        ]
        
        expected_base = capacity_metadata["ATREGGIES"]["EPIC"]["capacity"]
        expected_bump = capacity_metadata["ATREGGIES"]["EPIC"]["levelCapacityBump"]
        
        assert len(atreggies_epic) > 0, "No Atreggies EPIC missions found in inventory"
        
        for m in atreggies_epic:
            assert m.base_capacity == expected_base, (
                f"Atreggies EPIC level {m.level}: "
                f"expected base_capacity={expected_base}, got {m.base_capacity}"
            )
            assert m.level_capacity_bump == expected_bump, (
                f"Atreggies EPIC level {m.level}: "
                f"expected level_capacity_bump={expected_bump}, got {m.level_capacity_bump}"
            )

    def test_henerprise_inventory_has_correct_capacity(self, full_inventory, capacity_metadata):
        """Henerprise missions in inventory should have base_capacity=56."""
        henerprise_epic = [
            m for m in full_inventory
            if m.ship == "HENERPRISE" and m.duration_type == "EPIC"
        ]
        
        expected_base = capacity_metadata["HENERPRISE"]["EPIC"]["capacity"]
        expected_bump = capacity_metadata["HENERPRISE"]["EPIC"]["levelCapacityBump"]
        
        assert len(henerprise_epic) > 0, "No Henerprise EPIC missions found in inventory"
        
        for m in henerprise_epic:
            assert m.base_capacity == expected_base, (
                f"Henerprise EPIC level {m.level}: "
                f"expected base_capacity={expected_base}, got {m.base_capacity}"
            )
            assert m.level_capacity_bump == expected_bump, (
                f"Henerprise EPIC level {m.level}: "
                f"expected level_capacity_bump={expected_bump}, got {m.level_capacity_bump}"
            )

    def test_print_inventory_capacity_summary(self, full_inventory):
        """Print capacity summary for all ships in inventory."""
        print("\n" + "=" * 80)
        print("INVENTORY CAPACITY SUMMARY (EPIC missions only)")
        print("=" * 80)
        print(f"{'Ship':<20} {'Duration':<10} {'Base Cap':<10} {'Bump':<8} {'Cap @ L8':<10} {'Cap @ L8+50%':<12}")
        print("-" * 70)
        
        # Get unique ship/duration combinations
        seen = set()
        for m in sorted(full_inventory, key=lambda x: (x.ship, x.duration_type)):
            if m.duration_type != "EPIC":
                continue
            key = (m.ship, m.duration_type)
            if key in seen:
                continue
            seen.add(key)
            
            cap_l8 = m.effective_capacity(8, 0.0)
            cap_l8_50 = m.effective_capacity(8, 0.5)
            print(f"{m.ship_label:<20} {m.duration_type:<10} {m.base_capacity:<10} {m.level_capacity_bump:<8} {cap_l8:<10} {cap_l8_50:<12}")


# ---------------------------------------------------------------------------
# Tests: Research bonus calculations
# ---------------------------------------------------------------------------

class TestResearchBonusCalculations:
    """Verify Zero-G Quantum Containment bonus calculations."""

    # Zero-G Quantum Containment: 5% per level, max level 10
    @pytest.mark.parametrize(
        "level,expected_bonus",
        [
            (0, 0.00),
            (1, 0.05),
            (5, 0.25),
            (10, 0.50),
        ],
        ids=["L0", "L1", "L5", "L10_max"],
    )
    def test_zerog_bonus_by_level(self, level, expected_bonus):
        """Verify Zero-G bonus multiplier at each research level."""
        effect_per_level = 0.05
        actual_bonus = level * effect_per_level
        assert actual_bonus == pytest.approx(expected_bonus), (
            f"Zero-G level {level}: expected {expected_bonus}, got {actual_bonus}"
        )

    def test_print_zerog_bonus_table(self):
        """Print Zero-G Quantum Containment bonus table."""
        print("\n" + "=" * 50)
        print("ZERO-G QUANTUM CONTAINMENT BONUS TABLE")
        print("Effect: 5% per level, Max Level: 10")
        print("=" * 50)
        print(f"{'Research Level':<18} {'Bonus Multiplier':<18}")
        print("-" * 36)
        
        for level in range(11):
            bonus = level * 0.05
            print(f"{level:<18} {bonus:.0%}")
