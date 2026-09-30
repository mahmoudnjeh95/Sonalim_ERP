# Sonalim OCR service

Reads photos of the paper shift fiches (fabrication, conditionnement, changement bobines) with
local OCR -- RapidOCR on ONNX Runtime, CPU only -- in its own stateless, capped container. No
database, no tenant, no secret.

- `POST /read?form_hint=<form_type>` -- raw image bytes as the body; returns
  `{form_type, form_confidence, rotation, accept_score, header, blocks}`. Every `box` is
  `[x0, y0, x1, y1]` as fractions of the **upright** image. Table rows are `{"cells": {...}}`.
- `GET /health` -- `{"status": "ok"}`.
- One photo at a time (a lock), `mem_limit: 1536m`, `cpus: 2` in `compose.yaml`; the backend
  reaches it at `OCR_URL` (default `http://ocr:8100`).

## How a photo is read (`app/pipeline.py`)

1. **Orientation.** On a copy shrunk to 960 px, the engine reads the page at 0/90/180/270 and
   keeps the rotation with the most printed landmarks (titles, markers, band titles) read as
   lines **wider than tall**. Stops at 0 when 3 are read there. The width test matters: RapidOCR
   turns a tall text box before reading it, so a sideways page reads its titles at 0 too.
2. **Detection + recognition** on the upright image, **without** the angle classifier (the page
   is already upright; the classifier would read upside-down lines and hide a wrong rotation).
3. **Classify and locate** (`app/locate.py`, the templates in `templates/`).
4. **Per-cell re-read.** Each table row's column regions (the column span x the row's height,
   padded 2 px, clipped to the image) are read again, recognition only. A non-blank re-read
   replaces that cell (text, its score, the region as box); a blank one keeps detection's text.

## Engine calls (`app/engine.py`, rapidocr 3.9.2 -- PP-OCRv6 small det/rec, bundled in the wheel)

```python
engine = RapidOCR(params={"Global.text_score": 0.0, "Global.log_level": "warning"})
engine(image, use_det=True, use_cls=False, use_rec=True)   # page: .boxes / .txts / .scores
engine(crop,  use_det=False, use_cls=False, use_rec=True)  # one cell: TextRecOutput .txts[0] / .scores[0]
```

The `use_*` arguments **stick** on the RapidOCR object (`update_params` sets attributes and skips
`None`), so every call passes all three. Detection size is RapidOCR's default
(`Det.limit_side_len: 736`, `limit_type: min`); see the calibration sweep below.

## Running the tests

```
python -m pip install -r requirements.txt -r requirements-dev.txt   # plus httpx for TestClient
$env:PYTHONUTF8="1"; $env:OCR_FIXTURES_DIR="$env:USERPROFILE\sonalim-ocr-fixtures"
python -m pytest tests -q -s
```

`tests/test_photos.py` skips its photo tests without `OCR_FIXTURES_DIR` (the photos show workers'
names and never enter the repo); its fake-engine test of the re-read always runs.

## Calibration on the example photos (2026-09-30)

The three examples are ~700 px screenshots, not phone photos. Result with the committed templates:
fabrication -> `fabrication` 0 deg, conditionnement -> `conditionnement` 0 deg, bobines ->
`bobines` 90 deg (all three form/orientation tests pass).

**Key-cell report** (`test_key_cells_accuracy_report`, 8 cells):

| | fabrication (5) | conditionnement (3) | total |
|---|---|---|---|
| Task 15 templates, before the per-cell re-read (first run, classifier on) | 1 | 1 | 2/8 |
| Task 15 templates, with the re-read (first run, classifier on) | 1 | 1 | 2/8 |
| calibrated templates, before the per-cell re-read | 1 | 1 | **2/8** |
| calibrated templates, with the re-read (committed) | 1 | 1 | **2/8** |

The re-read changes *which* cells come out, not how many: it recovers `stops.start = 12h18`
(detection had glued it into "12h18 12h37 Po0uctions112 GB" in the next column) and cleans
`silo_end.level` ("29%·" -> "29%") and `packing.lot` ("" -> "D621495v"), but it loses
`production.water`: detection read "28,9 9,83" as one box, while the re-read of the water
region reads "9,83" (the printed "% Eau Humidité" headers come out as **one** box, which pins
the water column on the humidity side). Most misses are the digits themselves on these small
screenshots ("3,.5" for 3,25, "75,25Kg" for 75,28Kg) -- the per-cell crop should gain most on
real phone photos, where it reads the full-resolution image while detection works on a
~736 px copy.

**Detection size sweep** (calibrated templates, key cells with / without the re-read, seconds per
photo with the re-read for fabrication / conditionnement / bobines):

| `Det.limit_side_len` | without | with | seconds | blocks not found |
|---|---|---|---|---|
| 736 (default, kept) | 2/8 | 2/8 | 5.5 / 4.1 / 9.9 | fabrication `silo_end` ("Fin production" unread) |
| 1024 | 2/8 | 2/8 | 8.0 / 6.1 / 14.0 | conditionnement `packet_checks` (band unread) |
| 1400 | 3/8 | 3/8 | 9.7 / 7.6 / 18.3 | fabrication `mold_washes`, conditionnement `waste` |

**Seconds per photo** (Windows dev laptop, one process, engine already loaded, default size):
fabrication 5.5 s, conditionnement 4.1 s, bobines 9.9 s (sideways: four orientation passes).
Without the re-read: 5.1 / 3.7 / 8.9 s.

**Template changes made** (templates only; see the task report for the full list):
- Column `x` now places the **midpoint between neighbouring columns on the printed ruling**
  (measured on the photos), since that midpoint is where `locate` splits columns -- so an `x`
  is not always the visual centre of its column. Fabrication's silo tables are laid out
  differently from conditionnement's and got their own values.
- Band titles printed in wide-spaced capitals are read without spaces: conditionnement anchors
  gained `etatdepaquet`, `dechetpatesouintrants`, `arretmachine`; fabrication `stops` gained
  `arret delaproduction`, `arretdelaproduction`.
- Fabrication production headers gained `nlot`, `hd`, `hf` ("NLOT", "HD." / "Prod." read apart).

To redo with the blank fiches: run the photo tests with `-s`, measure each table's rulings,
and set `x` the same way.

## Container

`Dockerfile`: `python:3.12-slim-trixie` + `libglib2.0-0t64` (trixie's name for libglib2.0-0) and
`libgomp1`. rapidocr depends on `opencv-python` (GUI build, needs libGL), which lands in the
same `cv2` folder as the pinned `opencv-python-headless`; the build removes it and reinstalls the
headless wheel. The last `RUN` loads the engine and templates, so a broken install fails the
build. All pins resolve to cp312 manylinux wheels (checked with `pip install --dry-run
--platform manylinux2014_x86_64 --python-version 3.12`).

**The image was not built locally** (no Docker on the dev machine): it is first built by CI
(`.github/workflows/deploy.yml`, "Build and push OCR image"). Memory under the 1536 MB cap and
seconds per photo inside the container are still to be measured on the first deploy
(`docker stats`, and a `POST /read` of an example photo).

---

# RapidOCR probe — findings (Task 14, throwaway probe)

Decision-gate probe run on 2026-09-30 against the three example fiche photos
(`conditionnement.png`, `fabrication.png`, `bobines.png`) kept outside the repo at
`%USERPROFILE%\sonalim-ocr-fixtures\` (never committed — the photos show workers' names).

## Pinned versions (from `pip freeze` in the scratch venv)

```
rapidocr==3.9.2
onnxruntime==1.30.0
opencv-python-headless==5.0.0.93
numpy==2.4.6
```

Installed with:
```
python -m venv "$SCRATCH/ocr-probe"
"$SCRATCH/ocr-probe/Scripts/python" -m pip install rapidocr onnxruntime opencv-python-headless numpy
```
No extra `pip install` flags were needed. `pip install` did reach out to PyPI to resolve/download
the packages themselves (normal internet use), but **no separate model download happened at OCR
run time** — the three ONNX models rapidocr actually used (`PP-OCRv6_det_small.onnx`,
`ch_ppocr_mobile_v2.0_cls_mobile.onnx`, `PP-OCRv6_rec_small.onnx`) are bundled inside the
`rapidocr` wheel itself under `rapidocr/models/`, so the first `RapidOCR()` call found them
already on disk ("File exists and is valid" in the log) with no fetch.

**Note for the brief/plan:** the installed `rapidocr` (3.9.2, current PyPI release) defaults to
**PP-OCRv6 (small)** detection + recognition models, not PP-OCRv5 as the brief assumed. This is
a newer default than the plan expected; it is what "PyPI install with default params" gives you
today. If PP-OCRv5 is specifically wanted, a `params=` override or a different bundled model name
would be needed — not investigated further here since v6-small already gave good anchor
detection.

## Call API used (matches the brief's script as-is — no adaptation needed)

```python
from rapidocr import RapidOCR
engine = RapidOCR(params={"Global.text_score": 0.0})
result = engine(image)          # image: numpy ndarray (cv2.imread / cv2.rotate output)
result.boxes                    # list[np.ndarray] of quad corner coords, or None
result.txts                     # list[str], parallel to .boxes
result.scores                   # list[float], parallel to .boxes
```

This is rapidocr's current (v3-line) API: `rapidocr.RapidOCR()` returning an object with
`.boxes/.txts/.scores`, exactly as the brief described for "v3". No fallback to the v1
`rapidocr_onnxruntime` API was needed.

Detection-size override tried per Step 4:
```python
engine = RapidOCR(params={"Global.text_score": 0.0, "Det.limit_side_len": 1600})
```
(default `Det.limit_side_len` is smaller; 1600 is well above the photos' native ~700 px width,
so the image is effectively upscaled before detection.)

## How to rerun the probe

```bash
python -m venv "$SCRATCH/ocr-probe"
"$SCRATCH/ocr-probe/Scripts/python" -m pip install rapidocr onnxruntime opencv-python-headless numpy
export PYTHONUTF8=1   # required on Windows/cp1252 consoles — French accents otherwise crash printing
"$SCRATCH/ocr-probe/Scripts/python" "$SCRATCH/probe.py"        # default detection size
"$SCRATCH/ocr-probe/Scripts/python" "$SCRATCH/probe_large.py"  # Det.limit_side_len=1600
```
Both scripts read `%USERPROFILE%\sonalim-ocr-fixtures\{fabrication,conditionnement,bobines}.png`,
run all 4 rotations (0/90/180/270) per photo, and dump one JSON per photo/rotation with every
detected box's text, score and quad coordinates. No files outside `ocr/README.md` are meant to
survive this task — the venv, scripts and JSON dumps are scratchpad-only.

## Findings, per photo at its upright rotation

Upright rotation used: `fabrication` → 0°, `conditionnement` → 0°, `bobines` → 90° (it was
photographed rotated 90°; see question 5).

### (1) Is the printed title read?
- **fabrication**: yes — "FICHE FABRICATION PAR EQUIPE" score 1.00, plus "PASTA DOUMAN" 0.98-0.99.
- **conditionnement**: yes — "FICHE CONDITIONNEMENT PAR EQUIPE" score 0.99, "SONALIM" 1.00.
- **bobines**: yes (at its upright 90° rotation) — "FICHE CHANGEMENT BOBINES" score 0.98-1.00,
  "SONALIM" 1.00.

### (2) Are the grey band titles and column headers read? (which)
- **fabrication**: bands — "PRODUCTION" (1.00), "PATES NON CONFORME" (0.96-1.00),
  "ARRET DE LA PRODUCTION" (0.96-0.99), "ETAT DE SILO" (0.94-0.99, note: OCR reads "DE" not "DU"
  — the physical band may actually say "DE SILO", need to confirm against the original if the
  plan hardcodes "DU"), "PRESENCE PERSONNEL" (0.99-1.00), "LAVAGE DES MOULES" (0.94-0.98).
  Column headers — "Origine", "Qté de semoule", "Lot", "Qté (Sac)", "Qté (T)", "% Eau Humidité",
  "Heure", "N° lot", "N° moule", "Cause", "Broyage", "Semoule", "Pétrin", "Format" all read with
  scores ≥0.90.
- **conditionnement**: bands — "ETATDUSILO"/"ETATDUSHLO" (0.95-0.96, concatenated, one character
  wrong in the large-detection pass), "CONDITIONNEMENT" (1.00),
  "VERIFICATIOND'ETATDEPAQUET" (0.96, concatenated), "DECHETPATESOUINTRANTS" (0.94, concatenated),
  "ARRETMACHINE" (1.00, concatenated). Column headers — "Qté du cartons Qté bobine Qte scotch Qté
  ruban" (as one run in the 90° dump, ≥0.90), "Type de conditi[onnement]" (0.98), "Date :" (0.94-
  0.99), "Début production" / "Fin production" (1.00), "En Marche" / "En Arret" (0.92-1.00).
- **bobines**: bands/headers — "Direction:" / "Direetion" (0.96-0.97), "Production" (0.99-1.00),
  "Service:" (0.95-1.00), "Conditionnement" (1.00), "Ligne: PL O PC" (0.94-0.97), "Date" (1.00),
  "Format" (1.00), "Type bobine" (0.98-1.00), "Nlot"/"N lot" (0.81-0.91), "H.D"/"H.F" (0.76-0.97),
  "POIDS" (0.85-0.99), "RESTE" (0.79-1.00), "Non"/"Conf" (0.90-1.00), "Machinis[te]" (0.99-1.00),
  "Visa du responsable :" (0.99), "Validé par :" (0.94-0.99).

All titles, band titles and column headers listed above are read with high confidence on the
upright rotation of every photo. The anchor approach can locate these blocks.

### (3) Which handwritten values come out right
Scored against the 23 discrete handwritten values listed in the brief (13 fabrication, 6
conditionnement, 4 bobines), at the larger detection size (`Det.limit_side_len=1600`):

**Counted as a hit only when the digits/value are correct AND separable from neighboring text as
detected** (the strict, "usable as-is" count):
- fabrication: `3,3` (in "66 3,3"), `66` sacs, `65` sacs, `28,9 9,83` (eau/humidité pair) → 4 of 13
- conditionnement: `29%` silo (clean, isolated), lot "D6249sNL" (close enough to count) → 2 of 6
- bobines: `15H18` (leading fragment of a longer glued string) → 1 of 4 (weak — see caveat below)
- **Strict total: 7 of 23**

**Counted as a hit when the correct digits are present anywhere in a box's text, even glued to a
neighboring value** (the generous count — relevant because Task 15+'s anchor approach would crop
narrow per-field regions before OCR, which should un-glue most of these):
- fabrication: adds `12h18`, `12h37`, `10h43` (all present, though run together as
  "12h1812h37" / "10h43-10y53") → the `53` in `10h53` is misread as `y53`, still a miss. `3,25`
  is misread as `3,85` (digit wrong, not just glued) — miss. Silo `0%`/`29%` for fabrication's own
  silo sub-block were not found at all in this photo's dump — 2 misses.
  → fabrication generous count: 7 of 13
- conditionnement: adds waste `02,46kg` (as "0246ke"), `0,35Kg` (as "035Ks") — digits correct,
  unit/comma garbled. `0,23Kg` not found. `75,28Kg` misread as `75,25Ke` (digit wrong, genuine
  miss). → conditionnement generous count: 4 of 6
- bobines: adds `0,63` (present but always glued to the end of a longer number string, e.g.
  "R6,850,63", "7400,63" — never isolated). `87,00` and `86,80` were not recovered as clean
  values anywhere in the dump; the closest fragments ("1426,80063") mix two numbers together.
  → bobines generous count: 2 of 4
- **Generous total: 13 of 23**

**Answer to (3): 7 of 23 strictly usable as detected; 13 of 23 if judged by digit content that a
downstream per-field crop could still recover.** Neither count is a clean "most values are
directly usable" result — small handwritten digits on these ~700px-wide photos are the weak
point, consistent with the brief's expectation that detection size would matter.

### (4) Seconds per photo (all 4 rotations timed; single-rotation cost ≈ total/4)
Default detection size:
- fabrication: 4.7s / 4.7s / 5.3s / 4.8s (0/90/180/270)
- conditionnement: 3.6s / 3.5s / 4.0s / 2.8s
- bobines: 3.7s / 3.2s / 2.7s / 3.0s

`Det.limit_side_len=1600` (larger detection size):
- fabrication: 4.9s / 5.2s / 6.7s / 6.1s
- conditionnement: 5.5s / 5.9s / 5.5s / 5.5s
- bobines: 5.6s / 5.2s / 4.5s / 4.6s

Larger detection size costs roughly +1-2s per rotation (CPU, single photo, cold-model-loaded
process). It did **not** materially change the handwritten-value hit count in a way that flips
the gate — see (3).

### (5) Does the rotation with the most title/band hits equal the upright one for bobines?
Yes. Bobines was photographed rotated 90°; scoring all four rotations by count and quality of
clean title/band/header reads, **90° (clockwise)** is unambiguously the best: "FICHE CHANGEMENT
BOBINES", "SONALIM", "Direction:", "Production", "Service:", "Conditionnement", "Date", "Format",
"Type bobine", "Visa du responsable :", "Validé par :" all read cleanly only at 90°. At 0° and
180° the same title reads as broken fragments ("labore Da", "DOUNANY"); at 270° almost everything
is garbage. So the best-scoring rotation does correctly identify upright for the sideways photo.

## Decision gate (Step 5)

- Printed titles/bands not read on upright photos? **No** — all three photos read every named
  title, band and column header cleanly (see (1)/(2)). This stop condition does **not** hold.
- Fewer than half the handwritten values in (3) come out right at the larger detection size?
  **Borderline.** Strictly (usable as detected, no further parsing): 7 of 23 ≈ 30% — below half.
  Generously (digit content present, recoverable by a per-field crop before OCR): 13 of 23 ≈ 57%
  — at/above half. Which count is the right one depends on whether Tasks 15+ crop small
  per-field regions around each anchor before running OCR again (this probe only ran OCR on the
  whole photo, once). This condition is **ambiguous** on the whole-photo probe alone.

Given the strict count is the one actually observed (no cropping was tested in this task) and it
falls clearly under half, **this stop condition arguably holds** on the data actually gathered.
Per the brief, findings are written and committed regardless; reporting **BLOCKED** to the
controller with these exact numbers so they can decide whether per-field cropping (planned for
Task 15+ anyway) is expected to close the gap, or whether the plan needs to change before the
container is built.
