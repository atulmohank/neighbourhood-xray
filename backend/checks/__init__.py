"""Check modules. Each exposes CHECK_ID and an async run(listing) -> dict."""

from checks import flood_risk, power, rent_value, water_source, water_supply

ALL_CHECKS = [water_supply, power, flood_risk, rent_value, water_source]
