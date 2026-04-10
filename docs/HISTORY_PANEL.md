# History Panel — Implementation Plan

Created: April 7, 2026
Status: Not started

---

## Goal

Build a searchable, filterable import history panel backed by the local SQLite DB at
`~/.media-porter/history.db`. The user can find any previously imported file by filename,
camera, media type, or date range — without needing the original card or drive connected.

---

## Current State

`gui/widgets/history_panel.py` already exists but is minimal:
- Loads up to 1000 records with no filtering
- Shows a flat table: File, Type, Camera, Captured, Imported, Destination
- Has a Refresh button only
- No search, no filter, no session grouping, no detail view

`backend/db/repository.py` has:
- `get_history(limit)` — returns newest records first, no filtering
- `get_sessions(limit)` — returns session rows, no filtering
- No search query, no camera list query

---

## What to Build

### Phase A — Backend queries

File: `backend/db/repository.py`

Add two new functions:

**`search_history(query, camera, media_type, date_from, date_to, limit)`**
- `query: str` — substring match on filename (source_path LIKE %query%)
- `camera: str | None` — exact match on camera_make + camera_model concat
- `media_type: str | None` — "photo", "raw", "video", or None for all
- `date_from: datetime | None` — filter by captured_at >= date_from
- `date_to: datetime | None` — filter by captured_at <= date_to
- `limit: int` — default 1000
- Returns `list[ImportRecord]` ordered by imported_at desc
- All filters are optional and combinable

**`get_distinct_cameras()`**
- Returns `list[str]` of unique "Make Model" strings from the imports table
- Used to populate the camera filter dropdown
- Returns an empty list if DB is empty or unavailable

Tests: `tests/test_repository.py` (new file)
- search by filename substring
- search by camera
- search by media type
- search by date range
- combined filters
- empty result returns empty list
- get_distinct_cameras with multiple cameras
- get_distinct_cameras with empty DB

---

### Phase B — Search and filter bar UI

File: `gui/widgets/history_panel.py`

Replace the current slim action bar with a two-row filter bar:

**Row 1 — Search + counts**
- Text input: "Search files…" — filters by filename on every keystroke (debounced 300ms)
- Record count label (updates live as filters change)
- Refresh button (right-aligned)

**Row 2 — Filters**
- Camera dropdown: "All Cameras" + one entry per distinct camera in DB
- Media type segmented control: All / Photo / RAW / Video
- Date From picker (QDateEdit, optional)
- Date To picker (QDateEdit, optional)
- Clear Filters button (only visible when any filter is active)

Filter bar height: 36px per row = 72px total
Divider below filter bar before the table.

---

### Phase C — Live filtering

File: `gui/widgets/history_panel.py`

- On any filter change → call `search_history()` with current filter values
- Text search: debounce 300ms using `QTimer.singleShot` to avoid querying on every keystroke
- Camera/type/date changes: query immediately (no debounce needed)
- Show a subtle loading state during query (disable table, show "Loading…" in count label)
- After query: re-populate table, update count label

---

### Phase D — Session grouping headers

File: `gui/widgets/history_panel.py`

Group table rows by import session when no search/filter is active (default view).

Each session group has a non-interactive header row:
- Background: slightly different from regular rows
- Shows: date, source drive name, N files imported, N verified
- Collapsed by default: click to expand/collapse the group rows

When any filter is active: disable grouping, show flat list.

Implementation: use `QTableWidget` span rows for headers.
Session data: from `get_sessions()` — join to records by `imported_at` date proximity.

---

### Phase E — Detail strip

File: `gui/widgets/history_panel.py`

Click any file row → a detail strip expands below the table (fixed height 100px):

Contents:
- Full source path + "Copy" button
- Full destination path + "Copy" button  
- SHA256 hash (truncated to 16 chars + "…") + "Copy full hash" button
- Captured date/time
- Imported date/time

Clicking the same row again collapses the strip.
Clicking a different row switches the strip to that row's data.

---

## File Changes Summary

| File | Type | Description |
|------|------|-------------|
| `backend/db/repository.py` | Modify | Add `search_history()`, `get_distinct_cameras()` |
| `gui/widgets/history_panel.py` | Rewrite | Full new UI: filter bar, live search, session headers, detail strip |
| `tests/test_repository.py` | New | Tests for all search_history filter combinations |

No changes to `main_window.py` — the panel is already wired into the stacked widget at index 1.

---

## Build Order

| Step | What | File | Estimated scope |
|------|------|------|----------------|
| 1 | `search_history()` + `get_distinct_cameras()` | `repository.py` | Small |
| 2 | Tests for new queries | `tests/test_repository.py` | Small |
| 3 | Filter bar UI (rows 1+2) | `history_panel.py` | Medium |
| 4 | Wire filters to `search_history()` with debounce | `history_panel.py` | Medium |
| 5 | Session grouping headers | `history_panel.py` | Medium |
| 6 | Detail strip on row click | `history_panel.py` | Medium |
| 7 | Run full test suite | — | — |

---

## What to Skip

- Export filtered results to CSV — already handled by `report.py`
- Delete history records — non-destructive principle, never delete
- Edit or rename records
- Sync history across machines — Phase 4 feature

---

## Acceptance Criteria

- [ ] User can type a filename and see matching records within 300ms
- [ ] Camera dropdown is populated from real DB values, not hardcoded
- [ ] All four filters work independently and in combination
- [ ] Session headers show correct file count and verified count per session
- [ ] Clicking a row shows full paths and hash in the detail strip
- [ ] Copy buttons copy to clipboard correctly
- [ ] Panel loads in under 200ms for 5000 records
- [ ] All new repository queries have test coverage
- [ ] No regressions — full test suite passes
