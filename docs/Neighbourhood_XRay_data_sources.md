# Neighbourhood X-Ray: authoritative data sources (researched 29 Oct 2026)

## Flooding
1. **OpenCity: Flooding Locations in Bengaluru Urban** (publisher BBMP, origin KSRSAC), official data on a secondary host. https://data.opencity.in/dataset/flooding-locations-in-bengaluru-urban
   - 3 KML files, Public Domain, last updated 27 Nov 2025. The "vulnerable" KML has 158 points with WARD_NAME, WARDNO, ZONE, LocationName and coordinates.
   - HSR Layout ward: points 20, 21, 23, 24 ("HSR sector 2 Garden layout", "HSR layout 9th and 5th main"). Silk Board: 31, 33. Also covers Koramangala, Bellandur and Mahadevapura zone.
   - Proves a location is officially flood-vulnerable. It does NOT give dated incidents. Uses old BBMP ward names (pre-GBA).
   - Vulnerable KML: https://data.opencity.in/dataset/b03218ea-4b7c-4fa9-ab67-b9054d7ecc4c/resource/a7d8a01f-1fbc-41e1-85f0-f15ea16b2d27/download/6b3c63b0-f461-4e9c-a2c2-006f734c5b41.kml
   - Load it statically in the backend. TinyFish isn't needed for this one.
2. **KSNDMC** (official). Dashboard https://www.ksndmc.org/dashboard.aspx, daily reports https://www.ksndmc.org/ReportHomePage.aspx, flood page https://www.ksndmc.org/Flood.aspx, Varunamitra https://varunamitra.karnataka.gov.in
   - Runs 100 rain gauges, 12 weather stations and 26+ water-level sensors in Bengaluru (Urban Flood Monitoring PDF). Live inundation data is in the Bengaluru Meghasandesha app.
   - robots.txt blocked our fetcher, so the pages were not inspected. Test them with TinyFish. Treat as could_not_verify if blocked.
3. **Deccan Herald** (secondary, news) for dated waterlogging incidents. There's no official locality-level incident feed.

## Water source
1. **OpenCity: BWSSB Stage-wise Cauvery Water Supply Areas** (source bwssb.karnataka.gov.in), official data on a secondary host, Public Domain, updated 27 Nov 2025. https://data.opencity.in/dataset/bwssb-stage-wise-cauvery-water-supply-areas
   - CSV: https://data.opencity.in/dataset/d7c5f4bf-e7ec-4afb-8361-87d6b59a9633/resource/78394a03-3f65-42a3-a782-79dff3134396/download/6503e5ef-1315-4c50-ac43-e68a291be8a5.csv
   - Lists about 800+ area names under Stage 1 to Stage 4 Phase 2. Includes "HSR Sector 1st to 7th sector, Bandepalya", Agara village, Bommanahalli, Koramangala blocks, Bellandur and White Field.
   - Shows the area is in the Cauvery network. It does NOT show that a specific building is connected or that supply is adequate.
2. **OpenCity: Bengaluru Tanker Water Data** (Citizen Matters survey, Feb 2024; also 2015 and 2019 files), secondary, CC BY-NC. https://data.opencity.in/dataset/bengaluru-tanker-water-data
   - About 160 responses, pincode level only, with water sources, tanker frequency and tankers per month.
   - 560102 (HSR): 11 rows, 10 of them daily tanker purchase. 560103 (Bellandur) and 560068 also show heavy tanker use.
   - 2024 CSV: https://data.opencity.in/dataset/4e817ca1-5e55-4b97-92a9-e8e21fca299c/resource/bc92b440-fb0d-4c92-90cf-480dd46a03cd/download/1011076d-7fb4-4684-9c88-9b908950dc00.csv
3. **BWSSB official site** (official): Press Release https://bwssb.karnataka.gov.in/info-4/Press+Release/en and Notifications https://bwssb.karnataka.gov.in/new-page/Notifications/en
   - robots.txt blocked our fetcher. Test with TinyFish. Format and language are unknown.
   - Not useful for checking a specific building. Use it for supply disruptions.

## Rules
- A building-level water source (Cauvery connection, borewell or tanker) can't be checked against any public record. Use the listing text and a question for the owner. Return could_not_verify unless the listing states it.
- Label static datasets with their dataset date. Never present them as current conditions.
