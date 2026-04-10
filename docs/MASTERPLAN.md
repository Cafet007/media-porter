# Media Porter — Master Plan

Updated: April 7, 2026

---

## 1. Vision

Media Porter is a cross-platform desktop application for photographers and videographers
who need safe, verified, organized ingest of camera card media onto local drives.

The promise is simple: plug in your card, import your files, know the copy is verified.

Media Porter is not a DAM, not an editor, not a cloud tool. It is a focused ingest and
backup utility that does one thing right.

---

## 2. Strategic Position

### The market

Paid ingest tools exist and people pay for them. Observed pricing as of April 6, 2026:

| Product            | Price                       | Type              |
|--------------------|-----------------------------|-------------------|
| OffShoot           | $169 perpetual              | Ingest + backup   |
| OffShoot Pro       | $249 perpetual / $49/30 days| Pro ingest        |
| ShotPut Pro        | $169 perpetual / $60/30 days| Verified offload  |
| ProGrade Ingest Pro| $99.99/year                 | Ingest + organize |
| Photo Mechanic     | $149/year or $299 perpetual | Workflow + ingest |
| Lightroom          | $11.99/month                | Photo workflow    |

The market supports paid ingest tools. The competition is real but not dominant. There is no
obvious cheap and trustworthy option for photographers and small video teams.

### Where Media Porter fits

Media Porter is best positioned between Lightroom (too broad, no real verification) and
OffShoot/ShotPut (correct but complex, expensive, DIT-oriented).

The target is:

- any who repeats the same ingest workflow after every shoot

The differentiator is not features. It is trustworthiness at a lower price point and lower
complexity than OffShoot or ShotPut.

### Strategic principle

Trust should not be paywalled. Workflow acceleration should be.

- Free tier: full verification, single destination, basic history
- Pro tier: dual backup, presets, rich history, advanced workflow controls

---

## 3. Current State (April 2026)

### What is done

| Area                          | Status |
|-------------------------------|--------|
| Core import engine            | Done   |
| Camera-aware scanning         | Done   |
| EXIF + video metadata         | Done   |
| Destination rules engine      | Done   |
| Atomic copy + safety          | Done   |
| Drive detection + watcher     | Done   |
| Base GUI (PySide6)            | Done   |
| Import history (DB)           | Done   |
| Test suite (73/73)            | Done   |
| Source card protection in GUI | Done   |
| guard_write before mkdir      | Done   |
| Duplicate identity (name+size)| Done   |
| SHA256 post-copy verification | Done   |
| Live verify status in UI      | Done   |
| Verified count in DB sessions | Done   |

### Known bugs — all fixed

| # | Location | Description | Status |
|---|----------|-------------|--------|
| 1 | `main_window.py` + `safety.py` | Source card not registered as protected in GUI | Fixed |
| 2 | `safety.py` | Dest dir created before `guard_write()` | Fixed |
| 3 | `main_window.py` / `importer.py` / `file_table.py` | Duplicate filename identity used bare name | Fixed |
| 4 | `import_card.py` | CLI progress callback wrong arity | Fixed |
| 5 | `main_window.py` | Per-file progress bar showed batch bytes | Fixed |

### Gaps vs competitors

Compared to OffShoot (the most relevant direct competitor):

| Capability                  | OffShoot | Media Porter |
|-----------------------------|----------|--------------|
| Source + dest verification  | Yes      | **Yes**      |
| Multiple checksum modes     | Yes      | No           |
| Stop and resume             | Yes      | No           |
| Incremental backup          | Yes      | No           |
| Dual-destination copy       | Yes      | No           |
| Presets                     | Yes      | No           |
| Rename during ingest        | Yes      | No           |
| Transfer logs / reports     | Yes      | Partial      |
| Queue multiple jobs         | Yes      | No           |
| Sidecar file handling       | Yes      | No           |
| ASC MHL / S3 / Codex        | Yes (Pro)| No           |

Verification is now done. The next gap that matters for a paid V1 is resume/recovery,
then dual backup and presets.

---

## 4. Roadmap

### Phase 1 — Fix and Stabilize
Target: April 2026 (2 weeks)
Goal: app is safe and trustworthy on real shoots

**Week 1 — Critical bugs** ✅ Complete

- [x] Fix safety gap: register source card as protected when selected in GUI
- [x] Fix write-before-guard: move dest directory creation to after `guard_write()` in `safety.py`
- [x] Fix duplicate filename identity: use `(name, size_bytes)` tuples throughout
- [x] Fix CLI: align `import_card.py` progress callback to 7-argument signature
- [x] Fix progress bars: per-file bar shows file bytes, overall bar shows batch bytes

**Week 2 — Core missing features** 🔧 In progress

- [x] Post-copy SHA256 verification: hash source during copy, hash dest after rename, show live status in UI
- [ ] Resume/recovery: on relaunch after crash, detect and skip already-copied files
- [ ] Session report: plain CSV or text — copied, skipped, failed, verification status per file

**Exit criteria:** 10 real testers complete card ingests without data-loss incidents.

---

### Phase 2 — Paid V1
Target: June 2026 (6 weeks)
Goal: first version people will pay for

**Storage and history**

- [ ] Full SQLite import history: session, files, hashes, camera, dates
- [ ] Replace filename+size dedup with SHA256 hash dedup against history DB
- [ ] History panel: searchable and filterable by date, camera, session name
- [ ] Cross-session duplicate protection: never re-import a file seen in any past session

**Workflow**

- [ ] Dual-destination copy: main drive + backup drive in one operation
- [ ] Job/session naming before import: client name, shoot name, date
- [ ] Presets: save and recall destination + folder rule combinations per workflow
- [ ] Sidecar awareness: keep RAW + JPG + XMP + LRV/THM companion files together

**Settings and config**

- [ ] TOML config persistence: last destination, last drive UUID, active preset
- [ ] Settings panel: chunk size, verification mode, default paths, sidecar rules
- [ ] Template rule engine: replace hardcoded layout with `{year}/{month_name}` variables
- [ ] Rules editor: visual template builder with live path preview

**Pricing at launch**

| Tier | Price        | Included                                                       |
|------|--------------|----------------------------------------------------------------|
| Free | $0           | Single destination, full SHA256 verification, basic history    |
| Pro  | $89 one-time | Dual backup, presets, searchable history, reports, session naming |

---

### Phase 3 — Pro Differentiation
Target: September–November 2026
Goal: photographers describe Media Porter as part of their normal shoot workflow

**Workflow**

- [ ] Auto-ingest on card insert (detect card, start scan automatically)
- [ ] Queue multiple cards or jobs
- [ ] Rename rules during import (not just folder structure)
- [ ] Conflict resolution UI: show and resolve destination-exists collisions
- [ ] Retry failed files from within the session report

**Drive and storage**

- [ ] Destination space forecast before import starts
- [ ] Drive health warnings for destination
- [ ] Watch-folder / hot-folder ingest mode for studio use

**UI polish**

- [ ] Thumbnail strip preview before import (photos and video proxies)
- [ ] Error log panel surfaced in the UI
- [ ] App icon (macOS `.icns`, Windows `.ico`)

**Packaging**

- [ ] PyInstaller macOS `.app` bundle + `create-dmg` installer
- [ ] PyInstaller Windows `.exe` + NSIS or Inno Setup installer
- [ ] Windows drive detection testing and fixes

---

### Phase 4 — Studio and Team
Target: December 2026 and beyond
Goal: sell multi-seat licenses to small studios

- [ ] Shared preset packs: export and import preset collections across machines
- [ ] Shared import logs: network drive or export/sync workflow
- [ ] Operator notes per session
- [ ] Multi-user licensing model
- [ ] Admin export and reporting

---

## 5. Technical Architecture

### Data flow

```
SD Card (DCIM/ + PRIVATE/M4ROOT/CLIP/)
    └─► Scanner + CameraProfiles  → MediaFile list (path, size, type)
            └─► Inspector         → enriched with capture date (EXIF / video meta / mtime)
                    └─► DedupChecker  → filter_new() via filename+size index
                            └─► Rule Engine   → compute destination path
                                    └─► safe_copy()   → atomic temp→rename, chunked progress
                                            └─► SHA256 verify  → confirm dest hash matches source
                                                    └─► DB        → record import history
```

### Tech stack

| Layer        | Technology                         | Status     |
|--------------|------------------------------------|------------|
| Language     | Python 3.11+                       | Done       |
| GUI          | PySide6 (Qt6)                      | Done       |
| File ops     | `pathlib`, `shutil`                | Done       |
| Photo meta   | `Pillow`, `exifread`               | Done       |
| Video meta   | `pymediainfo`                      | Done       |
| Dedup        | filename + size (fast scan)        | Done       |
| Dedup        | SHA256 via history DB              | Phase 2    |
| Verification | SHA256 post-copy                   | Phase 1    |
| Database     | SQLite + SQLAlchemy                | Phase 2    |
| SD detection | polling via DriveWatcher           | Done       |
| Config       | TOML via `tomllib` / `tomli-w`     | Phase 2    |
| Packaging    | PyInstaller `.app` / `.exe`        | Phase 3    |

### Database schema

```sql
CREATE TABLE imports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_hash    TEXT NOT NULL UNIQUE,
    source_path  TEXT NOT NULL,
    dest_path    TEXT NOT NULL,
    file_size    INTEGER,
    media_type   TEXT,
    camera_make  TEXT,
    camera_model TEXT,
    captured_at  DATETIME,
    imported_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    session_id   INTEGER REFERENCES sessions(id)
);

CREATE TABLE sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT,
    source_root  TEXT NOT NULL,
    dest_root    TEXT NOT NULL,
    backup_root  TEXT,
    total_files  INTEGER,
    imported     INTEGER,
    skipped      INTEGER,
    errors       INTEGER,
    verified     INTEGER,
    started_at   DATETIME,
    finished_at  DATETIME
);
```

### Folder rule variables

| Variable         | Example       | Source                |
|------------------|---------------|-----------------------|
| `{year}`         | `2026`        | EXIF DateTimeOriginal |
| `{month}`        | `03`          | EXIF                  |
| `{month_name}`   | `March`       | EXIF                  |
| `{day}`          | `15`          | EXIF                  |
| `{date}`         | `2026-03-15`  | EXIF                  |
| `{camera_make}`  | `Sony`        | EXIF Make             |
| `{camera_model}` | `ILCE-6300`   | EXIF Model            |
| `{ext}`          | `arw`         | file extension        |
| `{original_name}`| `DSC06001`    | source filename stem  |
| `{counter}`      | `001`         | auto-increment        |
| `{media_type}`   | `Raw`         | file type             |

### Safety rules

| Rule                   | Implementation                                            |
|------------------------|-----------------------------------------------------------|
| Never write to SD card | Protected path registry, `guard_write()`                 |
| Never delete           | `guard_delete()` always raises — unconditional           |
| Never overwrite        | Existence check before copy                              |
| Space check per file   | `guard_space()` before each copy                         |
| Space check full batch | `check_batch_space()` before import starts               |
| Atomic copy            | Write to `.mporter_tmp_` → rename on success             |
| Temp cleanup           | `finally` block deletes temp on failure                  |
| Block scanning dest    | `_is_dest_drive()` check in GUI                          |
| Post-copy verification | SHA256 source hash vs dest hash after every file (Phase 1)|

### Supported file types

| Category | Extensions                                              |
|----------|---------------------------------------------------------|
| Photo    | `.jpg`, `.jpeg`, `.heic`, `.png`, `.tif`, `.tiff`      |
| Raw      | `.cr2`, `.cr3`, `.nef`, `.arw`, `.dng`, `.raf`, `.rw2` |
| Video    | `.mp4`, `.mov`, `.mts`, `.m2ts`, `.avi`, `.mkv`        |

---

## 6. Design Principles

1. **Non-destructive** — always copy, never move; source card is never modified
2. **Safety first** — protected path registry, atomic copy, no overwrite, no delete
3. **Verified always** — SHA256 check after every copy; verification is free, not a paid feature
4. **Fast dedup** — filename+size for live scan; SHA256+DB for history dedup
5. **Camera-aware** — Sony PRIVATE/M4ROOT/CLIP/, Canon, Nikon, Fuji, GoPro, DJI all handled
6. **Rule templates** — user-configurable folder layout via TOML, editable in GUI
7. **Offline-first** — no cloud, no login, no telemetry, fully local
8. **Resumable** — interrupted imports restart cleanly by skipping already-copied files
9. **Cross-platform** — `pathlib.Path` throughout; no hardcoded separators
10. **Chunked copy** — 4 MB chunks with live progress, cancel between files

---

## 7. What Not to Build

These will not be built unless paying users explicitly request them in volume:

- AI culling or star rating
- Photo or video editing features
- Cloud gallery, sync, or publishing
- Social media integration
- Digital asset management (DAM)
- Mobile companion app
- ASC MHL, Codex, or S3 support (unless DIT market demand appears)

---

## 8. Revenue Model

**Free tier** keeps trust features accessible. This is intentional: users who cannot afford
Pro should still be able to trust the app with their files.

**Pro tier** charges for workflow acceleration and time savings, not for safety.

Target revenue scenarios:

| Users | Price  | Annual Revenue |
|-------|--------|----------------|
| 500   | $89    | ~$44,500       |
| 1,000 | $89    | ~$89,000       |
| 2,000 | $89    | ~$178,000      |

These are not forecasts. They are sanity-check numbers to frame the business size.

A sustainable indie business is reachable. A venture-scale business is not the goal.

---

## 9. Next Immediate Action

Phase 1, Week 1: fix the five known bugs listed in Section 3.

Priority order:
1. Safety gap (bug #1 and #2) — data integrity risk
2. Duplicate filename identity (bug #3) — silent miscounting risk
3. CLI callback signature (bug #4) — broken CLI
4. Progress bar fix (bug #5) — UX confusion

After bugs are fixed: add SHA256 verification and session reports. Then recruit 10 beta testers.
