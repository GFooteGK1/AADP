"""Tests for P1 Accountable assignment rules."""

from __future__ import annotations

from unittest.mock import patch

from alpha_analysis_downstream_processing_mcp.flights import TEAM_MEMBERS
from alpha_analysis_downstream_processing_mcp.wrike import (
    _P1_MICROSCHOOL_CONTACTS,
    assign_p1_accountable_for_new_site,
)

# ---------------------------------------------------------------------------
# Brandon Gee — flights.py TeamMember config
# ---------------------------------------------------------------------------


def test_brandon_in_team_members() -> None:
    assert "brandon" in TEAM_MEMBERS


def test_brandon_home_airport() -> None:
    assert TEAM_MEMBERS["brandon"].home_airport == "DTW"


def test_brandon_wrike_contact_id() -> None:
    assert TEAM_MEMBERS["brandon"].wrike_contact_id == "KUAWKIGO"


def test_brandon_preferred_airlines_delta() -> None:
    assert TEAM_MEMBERS["brandon"].preferred_airlines == frozenset({"DL"})


def test_brandon_no_required_airlines() -> None:
    assert TEAM_MEMBERS["brandon"].required_airlines == frozenset()


def test_brandon_prioritize_shortest_false() -> None:
    assert TEAM_MEMBERS["brandon"].prioritize_shortest is False


# ---------------------------------------------------------------------------
# Brandon Gee — microschool pool
# ---------------------------------------------------------------------------


def test_brandon_in_microschool_contacts() -> None:
    assert "KUAWKIGO" in _P1_MICROSCHOOL_CONTACTS


# ---------------------------------------------------------------------------
# Growth / Flagship — auto-assign both Thomas Barrow and Israe Zizaoui
# ---------------------------------------------------------------------------


def test_growth_returns_both_contacts() -> None:
    result = assign_p1_accountable_for_new_site(
        state="TX", city="Dallas, TX", school_type="250"
    )
    assert set(result.contact_ids) == {"KUAWCQTS", "KUAWVGG4"}


def test_growth_rule_auto_assign() -> None:
    result = assign_p1_accountable_for_new_site(
        state="TX", city="Dallas, TX", school_type="250"
    )
    assert result.rule == "Auto-assign"


def test_flagship_returns_both_contacts() -> None:
    result = assign_p1_accountable_for_new_site(
        state="CA", city="Los Angeles, CA", school_type="1000"
    )
    assert set(result.contact_ids) == {"KUAWCQTS", "KUAWVGG4"}


def test_flagship_rule_auto_assign() -> None:
    result = assign_p1_accountable_for_new_site(
        state="CA", city="Los Angeles, CA", school_type="1000"
    )
    assert result.rule == "Auto-assign"


def test_growth_does_not_call_wrike_api() -> None:
    """Growth/flagship should short-circuit before any Wrike API calls."""
    with patch(
        "alpha_analysis_downstream_processing_mcp.wrike.get_all_site_records"
    ) as mock_get:
        assign_p1_accountable_for_new_site(
            state="TX", city="Dallas, TX", school_type="250"
        )
        mock_get.assert_not_called()


def test_growth_contact_ids_sorted() -> None:
    result = assign_p1_accountable_for_new_site(
        state="TX", city="Dallas, TX", school_type="250"
    )
    assert result.contact_ids == sorted(result.contact_ids)


# ---------------------------------------------------------------------------
# JC Fisher — still excluded
# ---------------------------------------------------------------------------


def test_jc_fisher_excluded() -> None:
    result = assign_p1_accountable_for_new_site(
        state="TX", city="Dallas, TX", school_type="jc_fisher"
    )
    assert result.contact_ids == []
    assert result.rule == "Excluded"


# ---------------------------------------------------------------------------
# Microschool — still runs normal scoring path (hits Wrike API)
# ---------------------------------------------------------------------------


def test_microschool_calls_wrike_api() -> None:
    """Microschool should NOT short-circuit — it needs scoring."""
    with patch(
        "alpha_analysis_downstream_processing_mcp.wrike.get_all_site_records",
        return_value=[],
    ):
        result = assign_p1_accountable_for_new_site(
            state="TX", city="Dallas, TX", school_type="micro"
        )
        # With no existing records, no eligible P1 found
        assert result.rule == "None"
