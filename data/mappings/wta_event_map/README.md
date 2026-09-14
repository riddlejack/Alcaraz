# WTA event mapping tables

Mapping and alias tables that pair tennis-data.co.uk event names with Sackmann mirror
tournament ids, and the per-edition match-format inventory. They contain event names,
tournament ids, dates, counts and format flags; no odds and no result rows.

| File | Derived from | Licence |
|---|---|---|
| `wta_event_crosswalk.csv` | tennis-data event names and dates paired with mirror `tourney_id`s (WTA01 crosswalk, frozen 2007–2024) | mapping table; Sackmann side CC BY-NC-SA 4.0 |
| `wta_event_alias_table.csv` | the same pairing, one row per alias | mapping table |
| `rule_inventory_by_edition.csv` | per-edition deciding-set and tiebreak inventory computed from the mirror's score strings | CC BY-NC-SA 4.0, © Jeff Sackmann |

Copied byte-for-byte from the archive's `references/WTA01_event_map/` at the commit named
in `docs/ARCHIVE.md`; hashes are bound in `data/manifests/WTA01-event-map.json`.
