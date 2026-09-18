"""The geographic block: countries named in a real company description, and an honest
``unavailable`` for profiles captured before the company page was."""

from __future__ import annotations

from app.web.services.dashboard.geography import NOT_CAPTURED, geographic_block, operating_countries

KCB = (
    "KCB Group PLC, together with its subsidiaries, provides corporate, investment, and retail "
    "banking services in Kenya, Tanzania, South Sudan, Rwanda, Uganda, Burundi, and the "
    "Democratic Republic of Congo. It operates through four segments. KCB Group PLC was "
    "founded in 1896 and is headquartered in Nairobi, Kenya."
)


def test_countries_in_order_of_first_mention_without_duplicates() -> None:
    assert operating_countries(KCB) == [
        "Kenya",
        "Tanzania",
        "South Sudan",
        "Rwanda",
        "Uganda",
        "Burundi",
        "Democratic Republic of Congo",
    ]
    assert operating_countries("Sudanese operations only") == []  # no partial-word match
    assert operating_countries("listed in Dubai and Côte d'Ivoire") == [
        "United Arab Emirates",
        "Ivory Coast",
    ]
    assert operating_countries(None) == []


def test_block_is_known_only_when_the_page_was_captured() -> None:
    old = {"industry": "Commercial Banks", "founded": 1896, "employees": 11253}
    block = geographic_block(old)
    assert block["status"] == "unavailable" and block["reason"] == NOT_CAPTURED
    assert block["operating_countries"] == [] and block["home_country"] is None
    new = {**old, "country": "Kenya", "description": KCB}
    block = geographic_block(new)
    assert block["status"] == "known" and block["home_country"] == "Kenya"
    assert block["operating_countries"][0] == "Kenya" and len(block["operating_countries"]) == 7
    assert "not a revenue" in block["note"] and block["segments"] == []
    assert block["coverage"] == {"value": 7.0, "status": "known", "reason": None}
    # a home country the description never names is still listed first
    block = geographic_block({"country": "Mauritius", "description": "operates in Kenya."})
    assert block["operating_countries"] == ["Mauritius", "Kenya"]
