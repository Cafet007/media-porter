# Media Porter

A cross-platform desktop application for importing media from camera SD cards to an external hard drive. Built for photographers and videographers who want automatic, rule-based file organisation with zero risk of data loss.

---

## Features

- **Automatic SD card detection** — detects cards via direct slot or USB dongle; a newly inserted card is selected and scanned automatically (toggle in Settings)
- **Camera-aware scanning** — handles Sony, Canon, Nikon, Fuji, GoPro, DJI folder structures (Sony MP4s in `PRIVATE/M4ROOT/CLIP/` are found automatically)
- **Smart deduplication** — skips files already on your drive (filename + size match)
- **SHA256 post-copy verification** — confirms every copied file matches the source
- **Import history database** — SQLite log of every imported file (source, dest, camera, capture date)
- **Rule-based folder organisation** — customisable templates per file type with live preview
- **Settings panel** — edit folder naming templates with variable reference
- **Non-destructive** — always copies, never moves or deletes; source card is never touched
- **Atomic file copy** — writes to a temp file first, renames only on success; no partial files on failure
- **Pre-import space check** — warns before starting if destination drive lacks space
- **Dual progress bars** — overall import progress + per-file bar, with copy speed and time remaining
- **Stays responsive during big copies** — writes bypass the OS cache and are flushed regularly, so slow USB drives can't stall the app or the computer; verification re-reads from disk
- **Completion summary** — totals, plain-language problems, Show in Finder, Eject Card, Save Report, Retry Failed
- **Done notification** — system notification and sound when an import finishes; the Mac is kept awake while copying
- **Cancel anytime** — stop import cleanly between files; already-copied files are kept
- **Sortable file table** — click any column header to sort by name, type, size, or date
- **Appearance** — Match System, Light, or Dark (View → Appearance)
- **Keyboard shortcuts** — ⌘R scan, ⌘I import, ⌘. cancel, ⌘E eject, ⌘1/⌘2 Files/History
- **Persistent config** — destination paths and folder rules saved across launches
- **Full logging** — rotating log at `~/.media-porter/logs/mporter.log`

---

## Supported File Types

| Type  | Extensions |
|-------|-----------|
| RAW   | `.arw` `.cr2` `.cr3` `.nef` `.dng` `.raf` `.rw2` |
| Photo | `.jpg` `.jpeg` `.heic` `.png` `.tif` `.tiff` |
| Video | `.mp4` `.mov` `.mts` `.m2ts` `.avi` `.mkv` |

---

## Folder Structure

Files are organised on the destination drive using configurable templates. Default layout:

```
External Drive/
├── Photography/
│   ├── RAW/
│   │   └── 2026-03-24/
│   │       └── DSC06001.ARW
│   └── JPG/
│       └── 2026-03-24/
│           └── DSC06001.JPG
└── Footage/
    └── 2026-03-24/
        └── C0001.MP4
```

Date folders use the **capture date from EXIF / video metadata**, not today's date. Templates are fully customisable via the Settings panel using variables like `{year}`, `{month_name}`, `{camera_make}`, etc.

---

## Requirements

- Python 3.9+
- macOS or Windows
- [MediaInfo](https://mediaarea.net/en/MediaInfo) (required by `pymediainfo` for video metadata)

---

## Installation

```bash
# Clone the repo
git clone git@github.com:Cafet007/media-porter.git
cd media-porter

# Create and activate a virtual environment (conda or venv)
conda create -n media-porter python=3.11 -y
conda activate media-porter

# Install dependencies
pip install -r requirements.txt
```

---

## Running

```bash
conda activate media-porter
python main.py
```

---

## Usage

1. **Plug in your SD card** — it appears under **Camera Cards** in the left panel
2. **Select your external drive** — click it under **Storage Drives**; destination paths are auto-filled
3. **Click Scan Card** — the app scans the card and shows all files with New / Already Imported status
4. **Click Import New Files** — only new files are copied; dual progress bars update per chunk
5. **Cancel anytime** — the current file finishes cleanly, already-copied files are kept

---

## CLI Tools

```bash
# Scan an SD card and list all media files
python scan_card.py /Volumes/Untitled

# Import new files from SD card to external drive
python import_card.py /Volumes/Untitled /Volumes/External

# Show kind + capture date for all files
python inspect_files.py /Volumes/Untitled
```

---

## Running Tests

```bash
python3 -m pytest tests/ -v
```

---

## Project Structure

```
media-porter/
├── backend/
│   ├── core/
│   │   ├── scanner.py          # SD card scan with camera profile detection
│   │   ├── camera_profiles.py  # per-brand folder structure profiles
│   │   ├── inspector.py        # extract kind + capture date from any file
│   │   ├── metadata.py         # EXIF (exifread/Pillow) + video (pymediainfo)
│   │   ├── models.py           # MediaFile, MediaType
│   │   ├── rules.py            # destination path engine + template variables
│   │   ├── importer.py         # chunked copy engine with progress + cancel
│   │   ├── dedup.py            # filename+size dedup index
│   │   └── safety.py           # safety guards, atomic copy, space checks
│   ├── db/
│   │   ├── models.py           # SQLAlchemy ORM (ImportRecord, ImportSession)
│   │   └── repository.py       # import history CRUD
│   └── utils/
│       ├── detector.py         # drive detection (Mac diskutil / Windows ctypes)
│       ├── registry.py         # drive role registry (persisted JSON)
│       ├── config.py           # load/save TOML config
│       └── log_setup.py        # rotating file log + console handler
├── gui/
│   ├── main_window.py          # main window, workers, signals
│   ├── theme.py                # dark/light theme palette + style helpers
│   └── widgets/
│       ├── source_panel.py     # Camera Cards / Storage Drives sections
│       ├── dest_panel.py       # destination path pickers
│       ├── file_table.py       # sortable file list with live status updates
│       ├── history_panel.py    # import history viewer
│       └── settings_panel.py   # folder naming template editor
├── tests/
│   ├── test_scanner.py
│   ├── test_safety.py
│   ├── test_detector.py
│   ├── test_rules.py
│   ├── test_dedup.py
│   └── test_importer.py
├── main.py                     # entry point
├── requirements.txt
└── PLAN.md
```

---

## Safety Guarantees

| Rule | How it's enforced |
|---|---|
| Never write to SD card | Source drive registered as protected on detection |
| Never delete any file | `guard_delete()` always raises — unconditional |
| Never overwrite existing files | Existence check before every copy |
| No partial files on failure | Atomic temp file → rename on success only |
| Space check before import | Batch check per destination drive, blocks import if insufficient |
| Post-copy verification | SHA256 of source computed during copy, stored in DB |

---

## Logs & Data

```
~/.media-porter/
├── logs/
│   ├── mporter.log        # current log (up to 5 MB)
│   ├── mporter.log.1      # previous
│   └── mporter.log.2
├── config.toml            # saved destination paths + folder naming rules
├── history.db             # SQLite import history
└── drives.json            # saved drive registry
```

---

## License

MIT
