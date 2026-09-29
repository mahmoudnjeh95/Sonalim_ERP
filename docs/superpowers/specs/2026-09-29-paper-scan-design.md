# Paper scan: fill the shift report (and the QC report) from photos of the paper fiches

## Why

Teams still fill the paper fiches on the line — *Fiche fabrication par équipe*, *Fiche
conditionnement par équipe*, *Fiche changement bobines* — and someone re-types them into the
shift report. The scan lets a user photograph the fiches (several photos, whole or partial
pages, in any order), have the system read them locally, review every value against the
photo, and save the result into the shift report as a **draft**. Nothing is submitted by the
scan; the team submits as today.

The same machinery later reads the QC paper fiche into the QC report (phase 3, once example
photos exist).

## Decisions (agreed 2026-09-29)

1. **Local OCR only.** No image leaves the server. Engine: RapidOCR (PaddleOCR PP-OCRv5
   models on ONNX Runtime) + OpenCV, in its own container. The live server is CPU-only
   (4 vCPU Haswell with AVX2, 7.6 GB RAM of which ~3.9 GB available, no GPU), so the model
   is the light one, pages are read one at a time, and the container is capped.
2. **The scan saves drafts.** "Enregistrer" after review saves the covered sections exactly as
   if the team had typed them (`save_section`). It never submits a section.
3. **Bobines become a real shift section**, and the scanner fills it (phase 2).
4. **The packing row's film quantity is derived on the server from the Bobines section**, the
   way run inputs are derived from versements (phase 2). It is no longer typed.
5. **Overwrite is chosen per section in the review**: for each section that already holds data
   the user picks *Remplacer* or *Garder l'existant*; a confirmation lists what will be
   replaced. A submitted section gets a revision through the existing mechanism. A validated
   shift is never written.
6. **One default OF, changeable per row.** The user picks line, date, shift and one OF first;
   every run and packing row read from the photos gets that OF; the review keeps an OF
   dropdown per row.
7. **A per-tenant dictionary that learns from corrections** turns paper codes (`BSK1`,
   "Films déchet C1", "C2", "Ver") into system values.

### Open point (must be settled before the phase 2 plan)

**Is the "bobine" of the Fiche changement bobines the film roll itself?** The packing row today
has both a film pair (`film_product_id` + `film_quantity`, kg) and a "Type bobine / Bobines"
pair (`tape_product_id` + `tape_quantity`, count, items of packaging kind `bobine` — none
seeded). A roll on the sheet weighs ~87 kg on a 0,63 kg core, which reads like a film roll.

- If **yes** (working assumption below): the Bobines section derives both `film_quantity` (kg)
  and `tape_quantity` (rolls finished); the bobine's type is the film item; the separate
  "Type bobine" picker leaves the packing form so the same material is never counted twice.
- If **no**: the Bobines section derives only `tape_quantity` and `tape_product_id`; film stays
  typed. Decision 4 would then not apply.

To be checked with the plant. Phase 1 does not depend on it.

## Phasing

Each phase gets its own implementation plan.

| Phase | Content | Depends on |
|---|---|---|
| 1 | `scan` module, OCR container, fabrication + conditionnement templates, review screen, apply to shift report, dictionary, photos visible on the shift | — |
| 2 | Bobines shift section, film derivation, bobines template | Open point above |
| 3 | QC template + apply to QC report | Example QC photos |

The OCR container recognises the bobines sheet from phase 1 on (it has a printed title); until
phase 2 its page is shown as "fiche reconnue — pas encore importée".

---

## 1. What the fiches hold and where it goes

Read from the three example photos (07/09/2026, line PC). The target is the existing section
payload shape of `shift_sections.py`.

### 1.1 Fiche fabrication par équipe → production side

| Paper block | Paper field | Target |
|---|---|---|
| Header | Ligne PC / PL (checkbox) | cross-check against the selected work center |
| | Date, Équipe, heures (`07 H à 14H00`) | cross-check against selected date / shift; `team` header field |
| | Conducteur ligne, Agent de fabrication | header `conducteur`, `agent_fabrication` |
| Production | N° lot, Produit/Format, HD prod, HF prod | one `runs` row: `lot_number`, `start_time`, `end_time`, `of_id` = default OF |
| | Semoule: Origine, Lot, Qté (sac), Qté (T) | one `versements` row per line: `product_id` via dictionary (kind `raw_material`) from Origine, `quantity` from Qté (T) converted to the item's unit |
| | Broyage: Lot, %, Qté (sac), Qté (kg) | `rebroyat_versements` |
| | % Eau, Humidité | run `water_percentage`, `humidity_percentage` |
| Pâtes non conformes — Déchet pétrin | Heure, Format, N° lot, Qté (kg), Cause | `waste_production` lines: `category` via dictionary (kind `waste_production`) from Cause/Format, `quantity`, `lot_number`, `occurred_at`, `note` = cause text |
| Pâtes non conformes — Produit fini | Heure, Format, N° lot, Qté (kg), Cause | **packing-side** waste, category `product` (the production side refuses `finished_product_conditioning`, "one place per loss") — see 3.4 |
| Lavage des moules | N° moule, Heure, État | `mold_washes` |
| Présence personnel | Salle de contrôle, Pétrin, Semoule, Broyage | `staffing` |
| Arrêt de la production | Panne, Heure d., Heure f., Action corrective | `stops` rows — see 3.3 |
| État de silo | Début / Fin: Format, lot, Quantité %, État de la ligne | `silo` rows with `side = production`, `phase = start/end` |

### 1.2 Fiche conditionnement par équipe → packing side

| Paper block | Paper field | Target |
|---|---|---|
| Header | Ligne, Date, Équipe, heures | cross-checks, as 1.1 |
| | Machiniste, Aide machiniste | header `machiniste`, `aide_machiniste` |
| État du silo | Début / Fin | `silo` rows with `side = packing` (the silo already stores the two sides apart, so a different reading from the fabrication sheet is not a conflict) |
| Conditionnement | Format, N° lot, Date de fab, Type de condit. (500g), Type film, Qté cartons / bobine / scotch / ruban | one `packing` row: `product_id` via dictionary (kind `finished_product`), `lot_number`, `film_product_id` via dictionary (kind `film_item`), quantities; "Type de condit." is only a cross-check against the product's net weight (`packing_type` is server-derived) |
| Vérification état paquet | Heure, Film, Pds paquet, Soudure longi., Soudure vert., Imp. date, Observation | `packet_checks` |
| Déchets pâtes ou intrants | Heure, Type de déchet, Qté (kg), Cause | `waste_packing` lines, category via dictionary (kind `waste_packing`) |
| Arrêt machine | Panne, Heure d., Heure f., Action corrective | `stops` rows linked to the packing row |

### 1.3 Fiche changement bobines (phase 2)

Columns: Date, Éq., H. travail, N° machine, D. compteur, Format, Type bobine, N° lot int., H.D,
H.F, Pds bobine, Pds cyl., Déchets, Reste (poids, conf., non conf.), Machiniste. One row per
roll change → one `bobines` row (section 5). The photo is often taken rotated (the example is
turned 90°).

### 1.4 What the example photos already show the scanner must catch

- **Another shift in the same upload**: the bobines sheet is team **A**, 14H–23H; the other two
  are team **D**, 07H–14H. Pages are attributed per page (3.1), never merged blindly.
- **Paper hours ≠ system shift hours**: paper says 07–14, the system shift is 07–15. Pages are
  matched on the start hour.
- **The lot contradicts the date**: `D6249SNL` decodes (via `default_lot_number`) to team D,
  2026, day 249 = **6 September**, while both sheets say 07/09/2026 → flagged.
- **The same loss on two sheets**: fabrication "Produit fini … 75,25 à broyer" and
  conditionnement "Broyage 75,28 — produit non conforme".
- **Several stops in one line**: "Alarme silo à reprises 10h43-10h53, 12h56-12h58" → two stops.
- **A start delay written as a sentence**: "Démarrage de la production à 09h27mn" → a stop from
  the shift start to 09:27.
- **Unreadable strokes** in the conditionnement quantity cells.
- **Paper codes**: `BSK1`, `B05I`, "Films déchet C1/C2", "Ver", "Carton déchets".

---

## 2. Architecture

```
browser ──(downscaled JPEGs)──► app: scan module ──► scan.* tables (pages as bytea)
                                      ▲                    │
                                      │                    ▼ status = queued
                                      │           worker: scan reader loop (own thread)
                                      │                    │  POST /read (image bytes)
                                      │                    ▼
                                      │           ocr container (stateless, no DB)
                                      │                    │  cells + boxes + confidences
                                      │                    ▼
                                      └──── scan/domain: parse, resolve dictionary,
                                            cross-check, build proposal
review screen ──► apply ──► production ShiftReportService.update_header / save_section
                         └► qc QualityReportService (phase 3)
```

### 2.1 New module `scan` (`backend/modules/scan/`)

A bounded context of its own because it writes into two modules (production, qc) and owns
data neither of them should hold (photos, OCR results, the dictionary).

`module.json`:

```json
{
  "name": "scan",
  "version": "0.1.0",
  "depends": ["core", "production"],
  "optional_depends": ["qc"],
  "provides_api": ["ScanSessionService", "ScanAliasService"],
  "publishes_events": [],
  "subscribes_events": [],
  "migrations_path": "./migrations",
  "permissions": ["scan.use_scanner", "scan.view_scans", "scan.admin_aliases"]
}
```

- Added to `MODULE_ORDER` after `qc`.
- It reads and writes production and QC data **only** through their `api/` services
  (`ShiftReportService.list_shifts / get_shift / open_shift / update_header / save_section`,
  and the QC services in phase 3). It never touches their tables.
- No events in v1: the reading is internal work of this module (a queue table polled by the
  worker, 2.4), and applying is a synchronous command into production.

### 2.2 Tables (schema `scan`)

All carry `tenant_id`.

- **`scan.scan_sessions`**: `id`, `tenant_id`, `kind` (`shift` | `qc`), `work_center_id`,
  `report_date`, `shift`, `default_of_id`, `shift_report_id` (null until known), `status`
  (`open` | `applied` | `discarded`), `review_state jsonb` (the user's edits and per-section
  Remplacer/Garder choices, autosaved), `created_by`, `created_at`, `applied_by`, `applied_at`.
- **`scan.scan_pages`**: `id`, `tenant_id`, `session_id`, `image bytea` (the JPEG as uploaded,
  already downscaled by the browser), `width`, `height`, `status` (`queued` | `reading` | `read`
  | `unrecognized` | `failed`), `attempts`, `form_hint` (user-forced form type after an
  unrecognized read), `form_type` (`fabrication` | `conditionnement` | `bobines` | `qc`),
  `rotation`, `ocr_result jsonb` (raw cells from the OCR container), `detected_header jsonb`
  (date, team, hours, line as read), `attribution` (`this_shift` | `other_shift` | `unknown`),
  `error`, `uploaded_by`, `created_at`, `read_at`.
- **`scan.scan_aliases`**: `id`, `tenant_id`, `kind` (`raw_material` | `finished_product` |
  `waste_production` | `waste_packing` | `equipment` | `film_item` | `person` | `downtime_motif`),
  `raw_text_normalized`, `raw_text_example`, `target_value`, `created_by`, `updated_at`,
  `use_count`; unique `(tenant_id, kind, raw_text_normalized)`.
- **`scan.scan_field_outcomes`**: `id`, `tenant_id`, `session_id`, `page_id`, `form_type`,
  `field_path`, `read_text`, `proposed_value`, `final_value`, `confidence`, `flag`, `changed`
  (bool). Written on apply; it is how accuracy per field is measured.

**Why photos in Postgres (`bytea`)**: nothing in the platform stores files yet; a table keeps
tenancy, transactions and backups in one place with no shared volume between containers. A
downscaled photo is ~300–600 KB; at ~3 photos × 3 shifts × 2 lines a day that is roughly
3 GB a year against 32 GB free. Revisit (object storage) if volume grows beyond that.

### 2.3 OCR container (`ocr/`, new top-level folder)

- Own `Dockerfile` (`python:3.12-slim`), deps: `rapidocr-onnxruntime`, `opencv-python-headless`,
  `numpy`, `fastapi`, `uvicorn`. No DB access, no tenant notion, no secrets.
- One endpoint: `POST /read` (body: image bytes; optional query `form_hint`). Returns
  `{form_type, form_confidence, rotation, header: {...cells}, blocks: [{key, found, rows:
  [{cells: {field: {text, confidence, box}}}]}]}`, boxes in the uploaded image's pixel space.
  `GET /health` for compose.
- One request at a time (a process-wide lock); `OMP_NUM_THREADS=2`.
- compose service `ocr`: no published port, `mem_limit: 1536m`, `cpus: 2`, image
  `ghcr.io/smarttoolsagro/erpsonalim-ocr:${IMAGE_TAG}`; `app` and `worker` get
  `OCR_URL=http://ocr:8100`. `.github/workflows/deploy.yml` builds and pushes the third image.

**Reading a page** (template-based, because the fiches are fixed printed forms):

1. **Orientation**: EXIF is already applied by the browser; the container then runs text
   detection at 0/90/180/270° on a small copy and keeps the rotation where a known printed
   title is read.
2. **Form type**: the printed title — "FICHE FABRICATION PAR EQUIPE", "FICHE CONDITIONNEMENT
   PAR EQUIPE", "FICHE CHANGEMENT BOBINES" (QC title added in phase 3) — matched fuzzily.
   A partial photo without its title is typed by the block headers it contains (e.g.
   "ARRET DE LA PRODUCTION" and "PATES NON CONFORME" only exist on the fabrication sheet;
   "VERIFICATION D'ETAT DE PAQUET" only on conditionnement). Neither → `unrecognized`.
3. **Blocks**: each template lists its blocks by their printed grey band title and their
   printed column headers. Each block is located on its own from those anchors, which is what
   makes **partial photos** work: a photo holding only "ARRET DE LA PRODUCTION" and "ETAT DE
   SILO" yields just those two blocks (`found: true`), the others `found: false`.
4. **Cells**: rows come from the block's horizontal ruling lines (OpenCV morphology), columns
   from the x-ranges of the printed column headers. Every handwritten text box the detector
   found is assigned to the cell containing its centre. Checkboxes (PC / PL) are read as the
   ink ratio of the box beside the printed label.
5. The container returns raw text and the model's confidence per cell. **It does not interpret
   values** — parsing, units, dictionary and cross-checks are domain logic in the backend (2.5).

Templates are JSON files in `ocr/templates/` (`fabrication.json`, `conditionnement.json`,
`bobines.json`, later `qc.json`): title variants, blocks, anchor texts, columns with a field
key each. A blank copy of each fiche, photographed flat, is needed to author and test them.

### 2.4 Reading queue (worker)

A new loop in `backend/worker/main.py`, in its own thread like `run_replenishment`, so a
30-second page never delays event consumers:

1. `SELECT … FROM scan.scan_pages WHERE status = 'queued' ORDER BY created_at LIMIT 1 FOR UPDATE
   SKIP LOCKED`, set `reading`, commit.
2. `POST {OCR_URL}/read` (timeout 180 s).
3. Store `ocr_result`, `form_type`, `rotation`, `detected_header`, compute `attribution` (3.1),
   set `read` / `unrecognized`, commit.
4. On a connection error or timeout: back to `queued` with `attempts + 1`; the third failure
   sets `failed` with the error. The review offers "Relire" (back to `queued`, attempts reset).
5. Idle poll every 2 s.

Pages of one session are read in upload order; the proposal is rebuilt from all read pages
every time the review screen asks for it (2.5), so it never goes stale.

### 2.5 Interpretation (`scan/domain/`, pure, no DB)

Input: the read pages' OCR results, the target shift's current state, the reference lists
(products, waste categories, equipment, OFs of the line) and the dictionary. Output: a
**proposal** — the same payload shape `save_section` takes, per section — plus a **flag map**
`field_path → {level, reason_code, sources: [{page_id, box}]}`.

- **Parsers per field kind** (each returns a value and a certainty):
  - decimal: French comma, units stripped — `02,46kg` → 2.46, `0,35Kg` → 0.35, `00` → 0,
    `1,47` → 1.47.
  - time: `09h27mn` → 09:27, `14h` → 14:00, `12H18` → 12:18; a time before the shift's start
    on a night shift belongs to the next day.
  - interval list: `10h43-10h53, 12h56-12h58` → two intervals.
  - percent: `29 %` → 29 (0–100, anything else is not a percent).
  - lot: pattern `<letter><digit><3 digits><plant code>`; a short form (`D6249`) is expanded to
    the one full lot on the same page/shift that starts with it.
  - date: `07/09/26`, `07-09-26`, `Le07/09/2026`.
  - choice: fuzzy match against a closed list (line state *En marche* / *En arrêt*).
  - checkbox: ink ratio.
- **Dictionary resolution** for coded fields: exact alias (normalized: case, accents, spaces,
  O/0 and I/1 folded) → exact or fuzzy match on the reference names → unresolved.
- **Flag levels**:
  - **ok**: parsed, resolved, not contradicted.
  - **doubt (yellow)**: low OCR confidence, parser uncertainty, unresolved code, fuzzy (not
    exact) name match, or a failed cross-check (3.2). The reason is shown to the user.
  - **required (red)**: a field the system requires is empty — what `save_section` refuses
    (e.g. a run's OF, a stop's start, a waste line's category, a packing row's product) and what
    `check_ready_to_submit` will demand later.
- "Low confidence" means below the confidence the OCR model itself reports as its acceptance
  cut, not a number chosen here; the value is read from the RapidOCR configuration and recorded
  in the result. `scan.scan_field_outcomes` is how we later learn which fields are really
  misread.

---

## 3. Rules the scan applies

### 3.1 Which shift a page belongs to

Before anything is read, the user has chosen line, date and shift. Each page's header is
compared with that choice:

- date read ≠ selected date, or start hour read ≠ the selected shift's start hour, or the
  checked line ≠ the selected line → the page is **`other_shift`**: listed apart, excluded from
  the proposal, with "Ignorer" (default) or "Inclure quand même".
- For the bobines sheet the per-row Date and the Éq./H. travail columns are used the same way.
- Team letter read ≠ the shift header's team → yellow on the team (the shift keeps its team;
  a letter may simply be misread).
- Nothing readable in the header → `unknown`: included, header fields yellow.

### 3.2 Cross-checks (each tied to a recorded value, no invented tolerance)

- **Lot vs date/team**: `default_lot_number(team, date)` of the shift ≠ the lot read → lot
  yellow, reason "le lot correspond au <date décodée>, équipe <lettre>".
- **Sacs vs tonnes**: only when the raw material records a per-bag weight in its UoM
  conversions; otherwise no check.
- **Type de condit. vs product**: the packing format read (500 g) ≠ the chosen product's net
  weight → product yellow.
- **Paper silo end vs next shift's silo start**: not checked (another shift's report).

### 3.3 Stops

- One paper line with several intervals → one stop per interval, same panne and action.
- "Démarrage de la production à HHhMM" (a start time with no end, or a sentence naming a start)
  → a proposed stop from the shift's start to that time, yellow, motif from the dictionary
  (kind `downtime_motif`) or empty (red if the section requires it).
- `started_at` / `ended_at` = report date + time (next day for times after midnight on the
  night shift).

### 3.4 One place per loss

The production side refuses `finished_product_conditioning`. So a fabrication "Produit fini"
line is proposed as a **packing-side** waste line, category `product`. When the conditionnement
sheet of the same session also has a finished-product or broyage line for the same lot, both
are shown side by side, yellow, "probablement la même perte — n'en garder qu'une", and only the
conditionnement one is kept by default. The rule is triggered by both lines existing for the
same lot, not by how close their quantities are.

### 3.5 Several pages for the same block

Two photos of the same block (a retake, or two overlapping partial photos) → per cell, the
reading with the higher confidence wins; when they disagree the cell is yellow and both
readings are offered.

---

## 4. Review and apply

### 4.1 Screen flow (`frontend/src/features/scan/`)

Entry points: Production → shift reports list "Scanner des fiches"; a shift report page
"Importer depuis des photos" (line/date/shift preselected); later QC.

1. **Choisir le shift**: line, date, shift, default OF (the line's open OFs). The screen then
   shows the shift's state: "aucun rapport", or its status and each section's state (vide /
   brouillon / soumis / rien à signaler / renvoyé). A **validated** shift stops here: "Ce shift
   est validé ; le stock est passé. Il doit être renvoyé avant toute modification."
2. **Photos**, two ways in: **scan with the camera** — a live camera view in the page (phone
   rear camera or PC webcam), several shots in a row sent together, falling back to the phone's
   camera app when the browser cannot open the camera — or **import photos** from the device
   (several at once). The browser applies EXIF rotation and downscales to 2400 px on the long side,
   JPEG. Thumbnails with per-page status (en file, lecture…, Fabrication, Conditionnement,
   Bobines, non reconnue → "Choisir le type de fiche", autre shift, échec → "Relire"). More
   photos can be added and pages removed at any time.
3. **Vérifier**: the shift form's sections, built from the same `sectionConfig.ts` as the
   shift form (a proposal mode), only the sections the photos cover.
   - Yellow cell = doubt, with the reason on hover/tap; red border = required and empty.
   - Clicking a field opens the photo beside the form, zoomed on the field's box.
   - Coded fields show the read text next to the chosen value ("lu : BSK1").
   - Each section that already holds data shows "Déjà rempli : 3 lignes (brouillon)" and a
     **Remplacer / Garder l'existant** choice; the existing rows can be opened for comparison.
     Default: Garder l'existant, so replacing is always a deliberate click. A section with no
     existing data shows no choice and is written.
   - Counters in a sticky bar: N champs à vérifier (yellow), N obligatoires (red).
   - Edits autosave into `review_state` (debounced), so leaving the page loses nothing.
4. **Enregistrer**: a confirmation lists the sections to write and, for each one replacing
   existing data, "Remplacera 3 lignes (brouillon)" or "Remplacera une section soumise — une
   révision sera créée". Yellow fields do not block; red fields that `save_section` would
   refuse block and are listed; red fields only needed at submit do not block and remain for
   the team.

One loader for the screen (the branded loader); page reads and section blocks use skeletons.
Every string in `en` and `fr`. The sessions list (recent scans, status, user, shift) follows the
platform list rules (FilterTabs on status, column filters, column resize/visibility).

### 4.2 Apply (`ScanSessionService.apply`)

One transaction:

1. Reload the shift; refuse if validated (`SHIFT_VALIDATED`).
2. **Stale check**: for each section to write, the review recorded a fingerprint of the section
   as it was shown; if the stored section changed since, refuse with `SECTION_CHANGED` naming
   the sections, and the screen reloads the comparison.
3. Permissions: the user needs `scan.use_scanner` and, for each written section,
   `production.shift.edit.<section>` (the same keys the shift form uses).
4. `open_shift` (creates the report if none), `update_header` with the names read (only fields
   the user kept), then `save_section` per chosen section in this order: runs,
   waste_production, stops, silo, staffing, bobines (phase 2), packing, packet_checks,
   waste_packing. Any `Err` rolls everything back and is returned with its section.
5. Learn: for every coded field whose final value differs from what the dictionary resolved,
   upsert the alias `(kind, normalized read text) → final value`.
6. Write `scan_field_outcomes`, set the session `applied`, link it to `shift_report_id`,
   `record_audit(action="scan_session.applied", payload={sections_written, sections_kept,
   pages})`.

The team then opens the shift report and submits sections as usual.

### 4.3 Photos on the shift

The shift report page shows "Fiches papier (3)" when applied sessions are linked to it; the
validator can open the photos next to the data. Gated by `scan.view_scans`.

### 4.4 Dictionary screen

Scan → Dictionnaire: list of aliases (kind, text read, system value, uses, last change), with
edit and delete behind `scan.admin_aliases`, audited (`scan_alias.updated` / `.deleted`).

---

## 5. Bobines section (phase 2 — production module)

- **Table** `production.shift_bobine_changes`: `id`, `tenant_id`, `shift_report_id`,
  `line_order`, `equipment_id`, `film_product_id` (the roll's type), `internal_lot`,
  `counter_reading`, `started_at`, `ended_at`, `reel_weight`, `core_weight`, `waste_quantity`,
  `remaining_weight`, `remaining_conforming`, `remaining_non_conforming`, `machinist`, `note`.
- **Section** `bobines` in `SECTION_KEYS` (after `packing`), part `_BOBINES` in `SECTIONS`,
  permission `production.shift.edit.bobines` declared in `module.json`.
- **Existing shifts**: a migration backfills a `bobines` section row with status
  `nothing_to_report` for every shift already `submitted` or `validated`
  (`INSERT … SELECT`), so their status does not move. New shifts get it `empty` like the
  others: from then on a team either fills it or declares "rien à signaler".
- **Film derivation** (working assumption of the open point): film consumed per roll =
  `reel_weight − core_weight − remaining_weight`. On every save of `bobines` or `packing`, each
  machine's total is shared across the packing rows on that machine in proportion to their
  `packets_counted` (`split_proportionally`, as versements are shared by minutes); rolls with no
  machine are shared across all packing rows the same way. The row's `film_product_id` is the
  rolls' type; rolls of more than one type on the same machine are refused (`MIXED_FILM`), as
  mixed rebroyat is. `tape_quantity` = number of rolls. `film_quantity` and `film_product_id`
  join `serverDerived` in `sectionConfig.ts`; the "Type bobine / Bobines" picker is removed.
  Stock posting is unchanged: it already reads the packing row's film figures.

## 6. QC (phase 3)

- Session `kind = qc`: the user picks the shift; the QC report is found through
  `QualityReportService` by `shift_report_id` (created if the shift is validated and has none).
- Targets: conformity lines (per packing row: conforming / non-conforming cartons, defect
  details) and the nine parameter groups (`presse`, `pompe_vide`, `sechage`, `chaudiere`,
  `compresseurs`, `traitement_eau`, `chiller`, `additif`, `proprete_locaux`).
- Apply → `update_draft` + `save_parameters`; a submitted QC report goes through its `revise`
  path; a validated one is refused. Needs `qc.manage_quality_reports`.
- The `qc.json` template and field mapping are written once example photos exist.

## 7. API

| Method | Path | Permission |
|---|---|---|
| POST | `/scan/sessions` `{kind, work_center_id, report_date, shift, default_of_id}` | `scan.use_scanner` |
| GET | `/scan/sessions` (filters) · `/scan/sessions/{id}` (session, pages, shift state) | `scan.use_scanner` |
| POST | `/scan/sessions/{id}/pages` (multipart, several files; JPEG/PNG/WebP, ≤ 8 MB each, ≤ 20 pages per session) | `scan.use_scanner` |
| DELETE | `/scan/sessions/{id}/pages/{page_id}` | `scan.use_scanner` |
| POST | `/scan/sessions/{id}/pages/{page_id}/reread` `{form_hint?}` | `scan.use_scanner` |
| GET | `/scan/pages/{page_id}/image` | `scan.use_scanner` or `scan.view_scans` |
| GET | `/scan/sessions/{id}/proposal` (proposal + flags + existing sections + fingerprints) | `scan.use_scanner` |
| PUT | `/scan/sessions/{id}/review` (autosave `review_state`) | `scan.use_scanner` |
| POST | `/scan/sessions/{id}/apply` | `scan.use_scanner` + per-section edit permissions |
| POST | `/scan/sessions/{id}/discard` | `scan.use_scanner` |
| GET | `/scan/shifts/{shift_report_id}/pages` | `scan.view_scans` |
| GET/PATCH/DELETE | `/scan/aliases` · `/scan/aliases/{id}` | `scan.use_scanner` (read) / `scan.admin_aliases` |

Errors use `detail={"code","message","message_fr"}` like the rest of the API: `SHIFT_VALIDATED`,
`SECTION_CHANGED`, `OCR_UNAVAILABLE`, `TOO_MANY_PAGES`, `UNSUPPORTED_IMAGE`, plus anything
`save_section` returns, prefixed with its section. Every mutation is audited.

## 8. Errors and resilience

- OCR container down: pages stay `queued`, the screen says "Service de lecture indisponible —
  nouvel essai automatique"; nothing is lost.
- Unrecognized page: the user picks the fiche type; the page is re-read with `form_hint`.
- A block not found on any page: its section simply is not in the proposal.
- Two sessions on the same shift: allowed; the stale check (4.2 step 2) prevents one silently
  overwriting the other's result.
- Sessions stay until applied or discarded; no automatic purge in v1.

## 9. Testing

- **Domain unit tests** (no DB), fixtures taken from the example photos: parsers (`02,46kg`,
  `09h27mn`, `10h43-10h53, 12h56-12h58`, `D6249` expansion, `Le07/09/2026`), lot/date
  cross-check (`D6249SNL` vs 2026-09-07 → flagged), page attribution (team A 14H–23H page vs
  team D 07–15 shift → `other_shift`), one-place-per-loss pairing, stop splitting and the
  start-delay stop, dictionary normalization, proposal building from a canned OCR result of
  the three photos.
- **Integration tests** (real DB): session on a shift with no report / a draft / a submitted
  section / a validated shift; apply with Remplacer and Garder; missing section permission;
  stale section; one section refused by `save_section` → nothing written; alias learned on
  apply; audit rows.
- **OCR container tests**: form type and orientation on the example photos, and a list of key
  cells (lot, semoule quantities, % eau, humidité, stop times, waste quantities) reported as an
  accuracy score rather than hard asserts. The photos contain workers' names, so they are
  **not committed**: the tests read them from `OCR_FIXTURES_DIR` and skip when it is absent.
- **Frontend**: `tsc -b --force`, then a browser pass: upload the three example photos, see the
  bobines page flagged as another shift, correct a yellow code and see it learned on the next
  scan, replace one section and keep another, apply, open the shift report and find the draft.

## 10. Out of scope

- Reading energy (not on the paper fiches).
- Automatic submission of sections.
- Any cloud OCR/AI engine (the reader sits behind the `/read` contract, so one can be swapped
  in later without touching the review screen).
- Handwriting model training or fine-tuning.
