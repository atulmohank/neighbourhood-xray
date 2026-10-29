# Neighbourhood X-Ray: selected UI design

## final/  <- BUILD FROM THIS
- xray_ui_final.html : open in Chrome. Overview tab + listing badge, then Rent, Residents, Ask tabs.
- xray_ui_final.png  : same thing as an image.

## stitch_reference/  (layout ideas only, NOT the colours)
- overview/          : Stitch Overview panel (labels on scores, source under each finding, export button)
- rent_tab/          : Stitch Rent tab (Fair band / Monthly premium / 1-yr overpay, value alternative card)
- palette_reference/ : cream + black Stitch version that inspired our palette

Note: Stitch HTML loads Tailwind from a CDN. Chrome MV3 extensions can't load remote scripts,
so copy the layout, write plain CSS using the tokens below.

## Design tokens
| Token  | Hex     | Use |
|--------|---------|-----|
| paper  | #F6F3EC | page / listing background |
| card   | #FFFDF8 | panel + cards |
| ink    | #1C1A17 | text, primary button |
| ink-2  | #55504A | secondary text |
| mute   | #8D867C | labels, metadata |
| line   | #E7E1D6 | borders |
| accent | #C98A12 | brand (one accent only) |
| good   | #4F7A5A | good / stable |
| watch  | #B7791F | check / caution |
| risk   | #A8432F | risk / overpriced |

Fonts: Inter (text), JetBrains Mono (all numbers), Fraunces (big headline lines + quotes only).
Panel width: 420-430px. Card radius 12px. No gradients except the soft amber hero card.
