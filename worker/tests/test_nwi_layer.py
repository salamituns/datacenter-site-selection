"""
Which layer of a state NWI geodatabase holds the wetlands.

This is a name-matching test, which normally would not earn its keep. It
does here because the bug it pins was invisible in every way that usually
catches one: no exception, no empty result, no warning. A layer was found,
polygons came back, the wetlands gate decided, and the run reported
success. Atlantic County, New Jersey returned ONE wetland polygon and Kent
County, Delaware five -- in states that are a fifth to a quarter wetland.

The old rule took the first layer containing "wetland" that was not
"metadata" or "project". Virginia's geodatabase lists VA_Wetlands first, so
it worked and was never questioned. Delaware and New Jersey also ship
{ST}_Wetlands_Historic_Map_Info, an index of historic map SHEETS, and GDB
layer order is neither alphabetical nor guaranteed -- so which layer won
was luck, per state.
"""

import pytest

from overlay_layers import _nwi_layer


def test_picks_the_exact_state_wetlands_layer():
    layers = ["Delaware", "DE_Wetlands", "DE_Wetlands_Historic_Map_Info",
              "DE_Wetlands_Project_Metadata"]
    assert _nwi_layer(layers, "DE") == "DE_Wetlands"


def test_historic_map_info_does_not_win_by_listing_first():
    # The real New Jersey ordering, which is what broke it.
    layers = ["NJ_Wetlands_Historic_Map_Info", "NJ_Wetlands", "New_Jersey"]
    assert _nwi_layer(layers, "NJ") == "NJ_Wetlands"


def test_virginia_still_resolves():
    # The state the old rule happened to get right; it must not regress.
    layers = ["Virginia", "VA_Wetlands", "VA_Wetlands_Project_Metadata"]
    assert _nwi_layer(layers, "VA") == "VA_Wetlands"


def test_state_code_case_does_not_matter():
    assert _nwi_layer(["de_wetlands"], "DE") == "de_wetlands"
    assert _nwi_layer(["DE_Wetlands"], "de") == "DE_Wetlands"


def test_a_lone_suffixed_layer_is_accepted():
    # A state that names it differently but unambiguously.
    assert _nwi_layer(["Boundary", "Coastal_Wetlands"], "XX") == "Coastal_Wetlands"


@pytest.mark.parametrize("layers", [
    ["Something_Historic_Map_Info", "Boundary"],   # nothing plausible
    ["AA_Wetlands", "BB_Wetlands"],                # ambiguous, no exact match
    [],
])
def test_returns_none_rather_than_guessing(layers):
    # None leaves the layer absent and the gate UNKNOWN. That is the answer
    # this project prefers to a confident wrong one -- a guessed layer is
    # how one polygon came to stand for Atlantic County's salt marsh.
    assert _nwi_layer(layers, "PA") is None
