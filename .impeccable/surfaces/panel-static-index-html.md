---
version: 1
slug: "panel-static-index-html"
primary_target: "panel/static/index.html"
related_targets: ["templates/index.html","templates/f_home.html","templates/f_search.html","templates/f_queue.html","templates/f_browse.html"]
---

# Surface brief: OpenHomeKaraoke (admin panel + guests' phone site)

Scope: one visual world for two Operate surfaces that share it.
- Admin panel, `panel/static/index.html` (Overview and Library tabs): the host starts, stops and checks on the machine; used in a dark living room during the party, on the PC and the phone.
- Guests' phone site, `templates/index.html` + `templates/f_*.html`: search and queue, see the queue, control the song playing, follow lyrics. Spanish speakers, mixed ages, dim room, a few drinks in.

Constraints: keep every element ID and JS hook; panel works offline (fonts served locally); no neon-arcade look; warmer, more personal, calmer than a dashboard. User steer: the timeline (dial) scrolls sideways.

## Direction contract

THESIS: The house's own console radio, tuned to tonight. Refuses the boxed dark dashboard (cards, pills, KPI tiles) and the neon karaoke bar.

OWN-WORLD: Walnut-tinted flat ground (never woodgrain), cabinet bands one step lighter, cream dial-print text, backlit amber dial glass as the only glow, a red needle, magic-eye green for healthy and its dark tube for off. Condensed dial-scale type for labels and numerals, a warm workhorse sans for reading. Each singer owns one fixed dial colour everywhere. Hierarchy by type scale and space, sections as bands, no boxed cards; rows on one shared baseline; strict stepped type scale; reflow by whole cells.

STORY: At a glance the host sees the radio is on, who is singing, what comes next and whether anything needs them; guests find, queue and follow songs without help.

FIRST VIEWPORT: Panel: top bar with brand, tabs and the band selector (Este monitor / TV / Público) with power. Below it the full-width dial: the current song large, singer in their colour, clock; the amber glass scale in clock time, scrollable sideways: sung songs to the left, the needle at now, queued songs as station marks at estimated start times. Under it three bands: Equipo (magic-eye services), Después (queue), Para sumarse (codes). Phone: the dial strip on top of Home, controls under it in big targets.

FORM: Radio de living, candidate 7 of 7 on the ordered list (console radio dial at night). seed:8e01245dbcd5cb65

Signature move: tonight's dial, a horizontally scrollable tuning scale where the needle is the song and the queue is the stations.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
