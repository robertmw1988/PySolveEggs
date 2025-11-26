"""Tests for mission drop calculations.

These tests validate that per-mission average drops match known reference data.
Reference data is from FetchData/egginc_data_verified_references.csv
"""
from __future__ import annotations

import csv
from pathlib import Path
import pytest
from typing import Dict, List, Tuple

from Solver.mission_data import (
    MissionOption,
    build_mission_inventory,
    filter_inventory_by_level,
    FTL_SHIPS,
)


# ---------------------------------------------------------------------------
# Load verified reference data
# ---------------------------------------------------------------------------

REFERENCE_CSV_PATH = Path(__file__).resolve().parent.parent.parent / "FetchData" / "egginc_data_verified_references.csv"


def load_verified_references() -> List[Dict]:
    """Load verified mission drop data from CSV."""
    if not REFERENCE_CSV_PATH.exists():
        return []
    
    references = []
    with REFERENCE_CSV_PATH.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ship = row["Ship"]
            duration = row["Duration"]
            level = int(row["Level"])
            target = row["Target Artifact"]
            
            # Sum drops by artifact family (aggregate all tiers)
            drops = {}
            for col, val in row.items():
                if col in ("Ship", "Duration", "Level", "Target Artifact"):
                    continue
                try:
                    count = int(val)
                    if count > 0:
                        drops[col] = count
                except ValueError:
                    continue
            
            references.append({
                "ship": ship,
                "duration": duration,
                "level": level,
                "target": target,
                "drops": drops,
                "total_drops": sum(drops.values()),
            })
    
    return references


VERIFIED_REFERENCES = load_verified_references()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def full_inventory() -> list[MissionOption]:
    """Load full mission inventory once per test module."""
    return build_mission_inventory()


@pytest.fixture
def henerprise_epic_missions(full_inventory: list[MissionOption]) -> list[MissionOption]:
    """Filter to Henerprise Epic missions only."""
    return [
        m for m in full_inventory
        if m.ship == "HENERPRISE" and m.duration_type == "EPIC"
    ]


@pytest.fixture
def atreggies_epic_missions(full_inventory: list[MissionOption]) -> list[MissionOption]:
    """Filter to Atreggies Epic missions only."""
    return [
        m for m in full_inventory
        if m.ship == "ATREGGIES" and m.duration_type == "EPIC"
    ]


# ---------------------------------------------------------------------------
# Helper to display mission drop summary
# ---------------------------------------------------------------------------

def print_mission_drops(
    mission: MissionOption,
    mission_level: int = 0,
    capacity_bonus: float = 0.0,
    top_n: int = 10,
) -> Dict[str, float]:
    """
    Print and return expected drops for a mission.

    Parameters
    ----------
    mission : MissionOption to analyze
    mission_level : user's mission level for capacity calculation
    capacity_bonus : Zero-G research bonus (e.g. 0.5 for 50%)
    top_n : number of top artifacts to display
    """
    effective_cap = mission.effective_capacity(mission_level, capacity_bonus)
    ratios = mission.drop_ratios()
    expected = mission.expected_drops(mission_level, capacity_bonus)

    print(f"\n{'='*60}")
    print(f"Ship: {mission.ship_label} | Duration: {mission.duration_type}")
    print(f"Level: {mission.level} | Target: {mission.target_artifact or 'Any'}")
    print(f"Base Capacity: {mission.base_capacity} | Level Bump: {mission.level_capacity_bump}")
    print(f"Effective Capacity (level={mission_level}, bonus={capacity_bonus:.0%}): {effective_cap}")
    print(f"Total raw drops in data: {sum(mission.drop_vector.values()):.0f}")
    print(f"\nTop {top_n} expected drops per mission:")
    print("-" * 40)

    sorted_drops = sorted(expected.items(), key=lambda x: -x[1])
    for art, amt in sorted_drops[:top_n]:
        ratio = ratios.get(art, 0)
        print(f"  {art}: {amt:.2f} ({ratio:.2%})")

    return expected


# ---------------------------------------------------------------------------
# Tests: Drop ratio sanity checks
# ---------------------------------------------------------------------------

class TestDropRatios:
    """Verify drop ratio calculations."""

    def test_drop_ratios_sum_to_one(self, full_inventory: list[MissionOption]):
        """All missions with drops should have ratios summing to 1.0."""
        for m in full_inventory:
            if m.drop_vector:
                ratios = m.drop_ratios()
                total = sum(ratios.values())
                assert abs(total - 1.0) < 1e-9, (
                    f"{m.ship_label}/{m.duration_type}/L{m.level}: "
                    f"ratios sum to {total}, expected 1.0"
                )

    def test_empty_drop_vector_gives_empty_ratios(self):
        """Mission with no drops should return empty ratios."""
        m = MissionOption(
            ship="TEST",
            ship_label="Test Ship",
            duration_type="SHORT",
            level=0,
            target_artifact=None,
            base_capacity=10,
            level_capacity_bump=1,
            seconds=3600,
            drop_vector={},
        )
        assert m.drop_ratios() == {}
        assert m.expected_drops(0, 0.0) == {}


# ---------------------------------------------------------------------------
# Tests: Capacity calculations
# ---------------------------------------------------------------------------

class TestCapacityCalculations:
    """Verify capacity formulas."""

    def test_base_capacity_no_bonus(self):
        """Capacity with no research bonus."""
        m = MissionOption(
            ship="HENERPRISE",
            ship_label="Henerprise",
            duration_type="EPIC",
            level=0,
            target_artifact=None,
            base_capacity=220,
            level_capacity_bump=5,
            seconds=345600,
            drop_vector={},
        )
        # At mission level 0, no bonus
        assert m.effective_capacity(0, 0.0) == 220

    def test_capacity_with_level_bump(self):
        """Capacity increases with mission level."""
        m = MissionOption(
            ship="HENERPRISE",
            ship_label="Henerprise",
            duration_type="EPIC",
            level=0,
            target_artifact=None,
            base_capacity=220,
            level_capacity_bump=5,
            seconds=345600,
            drop_vector={},
        )
        # At mission level 10: 220 + 10*5 = 270
        assert m.effective_capacity(10, 0.0) == 270

    def test_capacity_with_research_bonus(self):
        """Capacity increases with Zero-G research."""
        m = MissionOption(
            ship="HENERPRISE",
            ship_label="Henerprise",
            duration_type="EPIC",
            level=0,
            target_artifact=None,
            base_capacity=220,
            level_capacity_bump=5,
            seconds=345600,
            drop_vector={},
        )
        # At mission level 0, 50% bonus: floor(220 * 1.5) = 330
        assert m.effective_capacity(0, 0.5) == 330

    def test_capacity_combined(self):
        """Capacity with both level and research bonus."""
        m = MissionOption(
            ship="HENERPRISE",
            ship_label="Henerprise",
            duration_type="EPIC",
            level=0,
            target_artifact=None,
            base_capacity=220,
            level_capacity_bump=5,
            seconds=345600,
            drop_vector={},
        )
        # Level 10 + 50% bonus: floor((220 + 50) * 1.5) = floor(405) = 405
        assert m.effective_capacity(10, 0.5) == 405


# ---------------------------------------------------------------------------
# Tests: Expected drops per mission
# ---------------------------------------------------------------------------

class TestExpectedDrops:
    """Verify expected drop calculations against known values."""

    def test_expected_drops_scale_with_capacity(self):
        """Expected drops should scale linearly with capacity."""
        m = MissionOption(
            ship="TEST",
            ship_label="Test",
            duration_type="EPIC",
            level=0,
            target_artifact=None,
            base_capacity=100,
            level_capacity_bump=10,
            seconds=86400,
            drop_vector={"Artifact A": 500, "Artifact B": 500},
        )
        # At capacity 100: each artifact is 50% = 50 drops
        drops_100 = m.expected_drops(0, 0.0)
        assert drops_100["Artifact A"] == pytest.approx(50.0)
        assert drops_100["Artifact B"] == pytest.approx(50.0)

        # At level 10: capacity = 100 + 100 = 200, each = 100 drops
        drops_200 = m.expected_drops(10, 0.0)
        assert drops_200["Artifact A"] == pytest.approx(100.0)
        assert drops_200["Artifact B"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Tests: Compare with known reference data
# ---------------------------------------------------------------------------

class TestKnownMissionDrops:
    """
    Compare calculated drops against verified reference values.
    
    Reference data from FetchData/egginc_data_verified_references.csv
    contains manually verified drop counts from actual missions.
    """

    @pytest.fixture
    def verified_refs(self) -> List[Dict]:
        """Get verified reference data."""
        return VERIFIED_REFERENCES

    def test_reference_data_loaded(self, verified_refs):
        """Verify reference data is available."""
        assert len(verified_refs) > 0, "No verified reference data found"
        print(f"\nLoaded {len(verified_refs)} verified mission references")
        for ref in verified_refs:
            print(f"  - {ref['ship']} / {ref['duration']} / L{ref['level']} / {ref['target']}: {ref['total_drops']} total drops")

    def test_atreggies_epic_8_book_of_basan(self, full_inventory: list[MissionOption]):
        """
        Atreggies Epic Level 8 targeting Book of Basan.
        
        Verified total drops: 24,559,310 across all artifact types.
        """
        ref = next((r for r in VERIFIED_REFERENCES 
                    if r["ship"] == "Atreggies" and r["duration"] == "Epic" 
                    and r["level"] == 8 and r["target"] == "Book of Basan"), None)
        
        if ref is None:
            pytest.skip("Reference data not found")
        
        # Find matching mission in inventory
        matches = [
            m for m in full_inventory
            if m.ship == "ATREGGIES" and m.duration_type == "EPIC" and m.level == 8
            and m.target_artifact == "Book of Basan"
        ]
        
        assert len(matches) >= 1, "Atreggies Epic L8 Book of Basan not found in inventory"
        mission = matches[0]
        
        # Compare total drops
        inventory_total = sum(mission.drop_vector.values())
        ref_total = ref["total_drops"]
        
        print(f"\nAtreggies Epic L8 / Book of Basan:")
        print(f"  Reference total drops: {ref_total:,}")
        print(f"  Inventory total drops: {inventory_total:,.0f}")
        print(f"  Base capacity: {mission.base_capacity}")
        print(f"  Level capacity bump: {mission.level_capacity_bump}")
        
        # The totals should match (allowing small tolerance for rounding)
        assert inventory_total == pytest.approx(ref_total, rel=0.001), (
            f"Drop totals don't match: inventory={inventory_total:.0f}, reference={ref_total}"
        )

    def test_atreggies_short_4_tau_ceti(self, full_inventory: list[MissionOption]):
        """
        Atreggies Short Level 4 targeting Tau Ceti geode.
        """
        ref = next((r for r in VERIFIED_REFERENCES 
                    if r["ship"] == "Atreggies" and r["duration"] == "Short" 
                    and r["level"] == 4 and r["target"] == "Tau Ceti geode"), None)
        
        if ref is None:
            pytest.skip("Reference data not found")
        
        matches = [
            m for m in full_inventory
            if m.ship == "ATREGGIES" and m.duration_type == "SHORT" and m.level == 4
            and m.target_artifact == "Tau Ceti geode"
        ]
        
        assert len(matches) >= 1, "Atreggies Short L4 Tau Ceti geode not found in inventory"
        mission = matches[0]
        
        inventory_total = sum(mission.drop_vector.values())
        ref_total = ref["total_drops"]
        
        print(f"\nAtreggies Short L4 / Tau Ceti geode:")
        print(f"  Reference total drops: {ref_total:,}")
        print(f"  Inventory total drops: {inventory_total:,.0f}")
        
        assert inventory_total == pytest.approx(ref_total, rel=0.001)

    def test_henerprise_epic_8_gold_meteorite(self, full_inventory: list[MissionOption]):
        """
        Henerprise Epic Level 8 targeting Gold meteorite.
        """
        ref = next((r for r in VERIFIED_REFERENCES 
                    if r["ship"] == "Henerprise" and r["duration"] == "Epic" 
                    and r["level"] == 8 and r["target"] == "Gold meteorite"), None)
        
        if ref is None:
            pytest.skip("Reference data not found")
        
        matches = [
            m for m in full_inventory
            if m.ship == "HENERPRISE" and m.duration_type == "EPIC" and m.level == 8
            and m.target_artifact == "Gold meteorite"
        ]
        
        assert len(matches) >= 1, "Henerprise Epic L8 Gold meteorite not found in inventory"
        mission = matches[0]
        
        inventory_total = sum(mission.drop_vector.values())
        ref_total = ref["total_drops"]
        
        print(f"\nHenerprise Epic L8 / Gold meteorite:")
        print(f"  Reference total drops: {ref_total:,}")
        print(f"  Inventory total drops: {inventory_total:,.0f}")
        
        assert inventory_total == pytest.approx(ref_total, rel=0.001)

    def test_corellihen_corvette_epic_4(self, full_inventory: list[MissionOption]):
        """
        Corellihen Corvette Epic Level 4 (UNKNOWN target).
        """
        ref = next((r for r in VERIFIED_REFERENCES 
                    if r["ship"] == "Corellihen Corvette" and r["duration"] == "Epic" 
                    and r["level"] == 4), None)
        
        if ref is None:
            pytest.skip("Reference data not found")
        
        matches = [
            m for m in full_inventory
            if m.ship == "CORELLIHEN_CORVETTE" and m.duration_type == "EPIC" and m.level == 4
        ]
        
        assert len(matches) >= 1, "Corellihen Corvette Epic L4 not found in inventory"
        
        # Find mission matching target (UNKNOWN means no specific target)
        target_matches = [m for m in matches if m.target_artifact == ref["target"]]
        mission = target_matches[0] if target_matches else matches[0]
        
        inventory_total = sum(mission.drop_vector.values())
        ref_total = ref["total_drops"]
        
        print(f"\nCorellihen Corvette Epic L4 / {ref['target']}:")
        print(f"  Reference total drops: {ref_total:,}")
        print(f"  Inventory total drops: {inventory_total:,.0f}")
        print(f"  Mission target: {mission.target_artifact}")
        
        assert inventory_total == pytest.approx(ref_total, rel=0.001)

    def test_millenium_chicken_short_1(self, full_inventory: list[MissionOption]):
        """
        Millenium Chicken Short Level 1 (UNKNOWN target).
        """
        ref = next((r for r in VERIFIED_REFERENCES 
                    if r["ship"] == "Millenium Chicken" and r["duration"] == "Short" 
                    and r["level"] == 1), None)
        
        if ref is None:
            pytest.skip("Reference data not found")
        
        matches = [
            m for m in full_inventory
            if m.ship == "MILLENIUM_CHICKEN" and m.duration_type == "SHORT" and m.level == 1
        ]
        
        assert len(matches) >= 1, "Millenium Chicken Short L1 not found in inventory"
        
        # Find mission matching target (UNKNOWN means no specific target)
        target_matches = [m for m in matches if m.target_artifact == ref["target"]]
        mission = target_matches[0] if target_matches else matches[0]
        
        inventory_total = sum(mission.drop_vector.values())
        ref_total = ref["total_drops"]
        
        print(f"\nMillenium Chicken Short L1 / {ref['target']}:")
        print(f"  Reference total drops: {ref_total:,}")
        print(f"  Inventory total drops: {inventory_total:,.0f}")
        print(f"  Mission target: {mission.target_artifact}")
        
        assert inventory_total == pytest.approx(ref_total, rel=0.001)

    def test_voyegger_short_5(self, full_inventory: list[MissionOption]):
        """
        Voyegger Short Level 5 (UNKNOWN target).
        """
        ref = next((r for r in VERIFIED_REFERENCES 
                    if r["ship"] == "Voyegger" and r["duration"] == "Short" 
                    and r["level"] == 5), None)
        
        if ref is None:
            pytest.skip("Reference data not found")
        
        matches = [
            m for m in full_inventory
            if m.ship == "VOYEGGER" and m.duration_type == "SHORT" and m.level == 5
        ]
        
        assert len(matches) >= 1, "Voyegger Short L5 not found in inventory"
        
        # Find mission matching target (UNKNOWN means no specific target)
        target_matches = [m for m in matches if m.target_artifact == ref["target"]]
        mission = target_matches[0] if target_matches else matches[0]
        
        inventory_total = sum(mission.drop_vector.values())
        ref_total = ref["total_drops"]
        
        print(f"\nVoyegger Short L5 / {ref['target']}:")
        print(f"  Reference total drops: {ref_total:,}")
        print(f"  Inventory total drops: {inventory_total:,.0f}")
        print(f"  Mission target: {mission.target_artifact}")
        
        assert inventory_total == pytest.approx(ref_total, rel=0.001)

    def test_all_verified_references(self, full_inventory: list[MissionOption]):
        """
        Test all verified references match inventory data.
        """
        if not VERIFIED_REFERENCES:
            pytest.skip("No verified reference data")
        
        print("\n" + "=" * 80)
        print("VERIFIED REFERENCE COMPARISON")
        print("=" * 80)
        
        failed = []
        for ref in VERIFIED_REFERENCES:
            # Map ship name to API format
            ship_api = ref["ship"].upper().replace(" ", "_")
            duration_api = ref["duration"].upper()
            
            matches = [
                m for m in full_inventory
                if m.ship == ship_api 
                and m.duration_type == duration_api 
                and m.level == ref["level"]
            ]
            
            if not matches:
                print(f"  SKIP: {ref['ship']} {ref['duration']} L{ref['level']} - not in inventory")
                continue
            
            # Try to find exact target match first
            target_matches = [m for m in matches if m.target_artifact == ref["target"]]
            mission = target_matches[0] if target_matches else matches[0]
            
            inventory_total = sum(mission.drop_vector.values())
            ref_total = ref["total_drops"]
            diff_pct = abs(inventory_total - ref_total) / ref_total * 100 if ref_total > 0 else 0
            
            status = "✓" if diff_pct < 0.1 else "✗"
            print(f"  {status} {ref['ship']:<20} {ref['duration']:<6} L{ref['level']} {ref['target'][:20]:<20}")
            print(f"      Ref: {ref_total:>12,}  Inv: {inventory_total:>12,.0f}  Diff: {diff_pct:.2f}%")
            
            if diff_pct >= 0.1:
                failed.append(f"{ref['ship']} {ref['duration']} L{ref['level']}")
        
        if failed:
            pytest.fail(f"Mismatched references: {', '.join(failed)}")


# ---------------------------------------------------------------------------
# Diagnostic test: Print mission averages for manual comparison
# ---------------------------------------------------------------------------

class TestPrintMissionAverages:
    """Diagnostic tests to output drop averages for manual verification."""

    @pytest.mark.skip(reason="Run manually with: pytest -k print_henerprise -s")
    def test_print_henerprise_epic_drops(self, henerprise_epic_missions: list[MissionOption]):
        """Print Henerprise Epic mission drops for comparison."""
        print("\n" + "=" * 70)
        print("HENERPRISE EPIC MISSIONS - DROP AVERAGES")
        print("=" * 70)

        for m in henerprise_epic_missions[:5]:  # Limit to first 5
            print_mission_drops(m, mission_level=0, capacity_bonus=0.0, top_n=15)

    @pytest.mark.skip(reason="Run manually with: pytest -k print_atreggies -s")
    def test_print_atreggies_epic_drops(self, atreggies_epic_missions: list[MissionOption]):
        """Print Atreggies Epic mission drops for comparison."""
        print("\n" + "=" * 70)
        print("ATREGGIES EPIC MISSIONS - DROP AVERAGES")
        print("=" * 70)

        for m in atreggies_epic_missions[:5]:  # Limit to first 5
            print_mission_drops(m, mission_level=0, capacity_bonus=0.0, top_n=15)

    def test_summary_all_epic_missions(self, full_inventory: list[MissionOption]):
        """Output summary of all Epic missions with capacity info."""
        epic_missions = [m for m in full_inventory if m.duration_type == "EPIC"]

        print("\n" + "=" * 70)
        print("ALL EPIC MISSIONS SUMMARY")
        print("=" * 70)
        print(f"{'Ship':<20} {'Level':<6} {'Target':<25} {'BaseCap':<8} {'TotalDrops':<12}")
        print("-" * 70)

        for m in sorted(epic_missions, key=lambda x: (x.ship, x.level)):
            total = sum(m.drop_vector.values())
            target = (m.target_artifact or "Any")[:24]
            print(f"{m.ship_label:<20} {m.level:<6} {target:<25} {m.base_capacity:<8} {total:<12.0f}")
