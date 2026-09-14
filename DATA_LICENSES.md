# Data licences

The code in this repository is MIT-licensed (see `LICENSE`). The data it consumes is not,
and this file states what is and is not redistributed here.

## Rule

This repository carries code, manifests and hashes, mapping and alias tables, aggregates,
forecasts and scores. It never carries raw source files or row-level reproductions of a
source. Every derived table that is tracked here names its source and licence below.

## Sources

| Source | Terms | What this repository does |
|---|---|---|
| Jeff Sackmann, `tennis_atp` and `tennis_wta` (match results, rankings, players) | CC BY-NC-SA 4.0 | Consumed locally from a hash-pinned mirror (`data/manifests/ARCHIVE01.json`). Tables derived from it are published here under CC BY-NC-SA 4.0 with this attribution. The mirror itself is not redistributed. |
| Jeff Sackmann, Match Charting Project | CC BY-NC-SA 4.0 | Not consumed by the modelling trunk. |
| tennis-data.co.uk annual results and odds workbooks | Site terms; no redistribution granted | Consumed locally only. Nothing derived from its odds or full result rows is redistributed. Sample data contains no tennis-data rows. |
| Wikipedia draw and season-calendar pages | CC BY-SA 4.0 | Parsed locally; small event-name and date mapping tables may be tracked with attribution. |
| The Odds API and Software Heritage payloads | Provider terms | Stay local, never tracked. |

## Attribution

Match, ranking and player data © Jeff Sackmann, licensed under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Derived tables in
this repository that carry Sackmann-derived rows are released under the same licence and
may not be used commercially.

## Sample data

`data/sample/` is either synthetic or Sackmann-derived under the terms above. It contains
no odds and no tennis-data.co.uk rows. Its provenance is stated in `data/sample/README.md`.
