"""Check modules. Each exposes CHECK_ID and an async run(listing) -> dict."""

from checks import flooding, power_cuts, rent_compare, water_cuts, water_source

ALL_CHECKS = [water_cuts, power_cuts, flooding, rent_compare, water_source]
