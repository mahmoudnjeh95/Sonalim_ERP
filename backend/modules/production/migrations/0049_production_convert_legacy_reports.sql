-- Shift report core, milestone 1 (part 3): convert existing reports.
--
-- A SQL function so tests can re-run it; safe to call repeatedly (deterministic ids
-- and ON CONFLICT DO NOTHING). It reads only production tables. It is dropped at
-- cutover, when the old tables become compatibility views.
--
-- A run reuses its old Daily report id and a packing row its old Conditionnement
-- report id, which is why posted warehouse stock needs no rewriting.
CREATE OR REPLACE FUNCTION production.convert_legacy_reports() RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
    total INTEGER;
BEGIN
    -- 1. One shift report per (tenant, line, date, shift). Legacy rows with no line
    --    or no shift cannot be grouped and are left behind.
    INSERT INTO production.shift_reports (
        id, tenant_id, work_center_id, report_date, shift, team, status, revision,
        created_by, submitted_at, validated_by, validated_at, rejection_reason, created_at, updated_at
    )
    SELECT
        upper(substr(md5(r.tenant_id || '|' || r.work_center_id || '|' || r.report_date::text || '|' || r.shift), 1, 26)),
        r.tenant_id, r.work_center_id, r.report_date, r.shift,
        min(r.team),
        CASE
            WHEN bool_and(r.status = 'validated') THEN 'validated'
            WHEN bool_or(r.status = 'rejected') THEN 'returned'
            WHEN bool_or(r.status = 'draft') THEN 'open'
            ELSE 'submitted'
        END,
        1,
        min(r.created_by),
        max(r.submitted_at),
        CASE WHEN bool_and(r.status = 'validated') THEN max(r.validated_by) END,
        CASE WHEN bool_and(r.status = 'validated') THEN max(r.validated_at) END,
        max(r.rejection_reason) FILTER (WHERE r.status = 'rejected'),
        min(r.created_at),
        max(r.updated_at)
    FROM production.production_reports r
    WHERE r.work_center_id IS NOT NULL AND r.shift IS NOT NULL
    GROUP BY r.tenant_id, r.work_center_id, r.report_date, r.shift
    ON CONFLICT DO NOTHING;

    -- 2. Runs (old Daily reports).
    INSERT INTO production.shift_runs (
        id, tenant_id, shift_report_id, of_id, equipment_id, mold_id, start_time, end_time,
        production_minutes, dough_quantity, finished_product_quantity, regrind_quantity,
        regrind_input_quantity, regrind_input_product_id, regrind_product_id, raw_material_location_id,
        water_quantity, water_percentage, semolina_flow_rate, shortfall_comment, line_order,
        created_at, updated_at
    )
    SELECT
        r.id, r.tenant_id, sr.id, r.of_id, r.equipment_id, d.mold_id, d.start_time, d.end_time,
        d.production_minutes, d.dough_quantity, d.finished_product_quantity, d.regrind_quantity,
        d.regrind_input_quantity, d.regrind_input_product_id, d.regrind_product_id, d.raw_material_location_id,
        d.water_quantity, d.water_percentage, d.semolina_flow_rate, r.shortfall_comment,
        (row_number() OVER (PARTITION BY sr.id ORDER BY d.start_time NULLS LAST, r.created_at, r.id) - 1)::int,
        r.created_at, r.updated_at
    FROM production.production_reports r
    JOIN production.daily_reports d ON d.report_id = r.id AND d.tenant_id = r.tenant_id
    JOIN production.shift_reports sr
        ON sr.tenant_id = r.tenant_id AND sr.work_center_id = r.work_center_id
       AND sr.report_date = r.report_date AND sr.shift = r.shift
    WHERE r.report_type = 'daily'
    ON CONFLICT DO NOTHING;

    -- 3. Packing rows (old Conditionnement reports). run_id is the linked Daily
    --    report only when that Daily was itself converted.
    INSERT INTO production.shift_packing_rows (
        id, tenant_id, shift_report_id, of_id, run_id, equipment_id,
        finished_product_quantity, packets_counted, film_quantity, carton_quantity, tape_quantity,
        scotch_quantity, ruban_quantity, waste_carton_quantity, machine_speed, production_minutes,
        downtime_minutes, downtime_reason, downtime_note, lot_number, dlc_date,
        film_product_id, carton_product_id, tape_product_id, scotch_product_id, ruban_product_id,
        film_supplier_id, carton_supplier_id, tape_supplier_id, scotch_supplier_id, ruban_supplier_id,
        packaging_location_id, finished_goods_location_id, snapshot_net_weight_grams,
        snapshot_packets_per_carton, shortfall_comment, line_order, created_at, updated_at
    )
    SELECT
        r.id, r.tenant_id, sr.id, r.of_id, run.id, r.equipment_id,
        c.finished_product_quantity, c.packets_counted, c.film_quantity, c.carton_quantity, c.tape_quantity,
        c.scotch_quantity, c.ruban_quantity, c.waste_carton_quantity, c.machine_speed, c.production_minutes,
        c.downtime_minutes, c.downtime_reason, c.downtime_note, c.lot_number, c.dlc_date,
        c.film_product_id, c.carton_product_id, c.tape_product_id, c.scotch_product_id, c.ruban_product_id,
        c.film_supplier_id, c.carton_supplier_id, c.tape_supplier_id, c.scotch_supplier_id, c.ruban_supplier_id,
        c.packaging_location_id, c.finished_goods_location_id, c.snapshot_net_weight_grams,
        c.snapshot_packets_per_carton, r.shortfall_comment,
        (row_number() OVER (PARTITION BY sr.id ORDER BY r.created_at, r.id) - 1)::int,
        r.created_at, r.updated_at
    FROM production.production_reports r
    JOIN production.conditionnement_reports c ON c.report_id = r.id AND c.tenant_id = r.tenant_id
    JOIN production.shift_reports sr
        ON sr.tenant_id = r.tenant_id AND sr.work_center_id = r.work_center_id
       AND sr.report_date = r.report_date AND sr.shift = r.shift
    LEFT JOIN production.shift_runs run ON run.id = c.daily_report_id
    WHERE r.report_type = 'conditionnement'
    ON CONFLICT DO NOTHING;

    -- 4. Semoule lines.
    INSERT INTO production.shift_run_semolina_lines (id, tenant_id, run_id, product_id, quantity, location_id, line_order)
    SELECT l.id, l.tenant_id, l.report_id, l.product_id, l.quantity, l.location_id, l.line_order
    FROM production.report_semolina_lines l
    JOIN production.shift_runs run ON run.id = l.report_id
    ON CONFLICT DO NOTHING;

    -- 5. Waste lines: a line of a Daily report belongs to a run, of a Conditionnement to a packing row.
    INSERT INTO production.shift_waste_lines (
        id, tenant_id, shift_report_id, section_key, run_id, packing_row_id,
        category, product_id, quantity, note, line_order
    )
    SELECT
        w.id, w.tenant_id, COALESCE(run.shift_report_id, pk.shift_report_id),
        CASE WHEN run.id IS NOT NULL THEN 'waste_production' ELSE 'waste_packing' END,
        run.id, pk.id, w.category, w.product_id, w.quantity, w.note, w.line_order
    FROM production.report_waste_lines w
    LEFT JOIN production.shift_runs run ON run.id = w.report_id
    LEFT JOIN production.shift_packing_rows pk ON pk.id = w.report_id
    WHERE run.id IS NOT NULL OR pk.id IS NOT NULL
    ON CONFLICT DO NOTHING;

    -- 6. Arrêts: minutes-only lines become stop events laid out one after another
    --    from the start of the shift window. The machine is the report's own
    --    equipment when it had one, otherwise unknown.
    INSERT INTO production.machine_stops (
        id, tenant_id, shift_report_id, run_id, packing_row_id, equipment_id,
        started_at, ended_at, downtime_type, classification, motif, note, source, line_order
    )
    SELECT
        x.id, x.tenant_id, x.shift_report_id, x.run_id, x.packing_row_id, x.equipment_id,
        x.shift_start + make_interval(mins => x.offset_minutes),
        x.shift_start + make_interval(mins => x.offset_minutes + x.minutes),
        x.downtime_type, x.classification, x.motif, x.note, 'migrated', x.line_order
    FROM (
        SELECT
            l.id, l.tenant_id, sr.id AS shift_report_id, run.id AS run_id, pk.id AS packing_row_id,
            r.equipment_id, l.minutes, l.downtime_type, l.classification, l.motif, l.note, l.line_order,
            (sr.report_date + COALESCE(sw.start_time, TIME '00:00'))::timestamptz AS shift_start,
            COALESCE(
                SUM(l.minutes) OVER (
                    PARTITION BY sr.id
                    ORDER BY (pk.id IS NOT NULL), l.report_id, l.line_order, l.id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ), 0
            )::int AS offset_minutes
        FROM production.report_downtime_lines l
        JOIN production.production_reports r ON r.id = l.report_id
        LEFT JOIN production.shift_runs run ON run.id = l.report_id
        LEFT JOIN production.shift_packing_rows pk ON pk.id = l.report_id
        JOIN production.shift_reports sr ON sr.id = COALESCE(run.shift_report_id, pk.shift_report_id)
        LEFT JOIN production.shift_windows sw ON sw.tenant_id = sr.tenant_id AND sw.shift = sr.shift
    ) x
    ON CONFLICT DO NOTHING;

    -- 7. Energy: one row per shift, the sum of its Daily reports' figures.
    INSERT INTO production.shift_energy (
        shift_report_id, tenant_id, fuel_quantity, fuel_supplier_id, gasoil_quantity,
        gasoil_supplier_id, gasoil_flow_rate, generator_hours, electricity_quantity
    )
    SELECT
        run.shift_report_id, run.tenant_id, sum(d.fuel_quantity), min(d.fuel_supplier_id),
        sum(d.gasoil_quantity), min(d.gasoil_supplier_id), max(d.gasoil_flow_rate),
        sum(d.generator_hours), sum(d.electricity_quantity)
    FROM production.daily_reports d
    JOIN production.shift_runs run ON run.id = d.report_id
    GROUP BY run.shift_report_id, run.tenant_id
    ON CONFLICT DO NOTHING;

    -- 8. Section states for the sections converted here.
    INSERT INTO production.shift_report_sections (shift_report_id, tenant_id, section_key, status, submitted_at)
    SELECT
        sr.id, sr.tenant_id, k.section_key,
        CASE
            WHEN d.has_data THEN
                CASE sr.status WHEN 'open' THEN 'draft' WHEN 'returned' THEN 'returned' ELSE 'submitted' END
            WHEN sr.status IN ('submitted', 'validated') THEN 'nothing_to_report'
            ELSE 'empty'
        END,
        sr.submitted_at
    FROM production.shift_reports sr
    CROSS JOIN (VALUES ('runs'), ('waste_production'), ('stops'), ('packing'), ('waste_packing'), ('energy'))
        AS k(section_key)
    CROSS JOIN LATERAL (
        SELECT CASE k.section_key
            WHEN 'runs' THEN EXISTS (SELECT 1 FROM production.shift_runs x WHERE x.shift_report_id = sr.id)
            WHEN 'waste_production' THEN EXISTS (
                SELECT 1 FROM production.shift_waste_lines x
                WHERE x.shift_report_id = sr.id AND x.section_key = 'waste_production')
            WHEN 'stops' THEN EXISTS (SELECT 1 FROM production.machine_stops x WHERE x.shift_report_id = sr.id)
            WHEN 'packing' THEN EXISTS (SELECT 1 FROM production.shift_packing_rows x WHERE x.shift_report_id = sr.id)
            WHEN 'waste_packing' THEN EXISTS (
                SELECT 1 FROM production.shift_waste_lines x
                WHERE x.shift_report_id = sr.id AND x.section_key = 'waste_packing')
            WHEN 'energy' THEN EXISTS (
                SELECT 1 FROM production.shift_energy x
                WHERE x.shift_report_id = sr.id
                  AND (x.fuel_quantity > 0 OR x.gasoil_quantity > 0 OR x.electricity_quantity > 0 OR x.generator_hours > 0))
        END AS has_data
    ) d
    ON CONFLICT DO NOTHING;

    -- 9. Old revisions become revisions of the runs / packing section, renumbered
    --    per (shift, section) because two Dailies of one shift each started at 1.
    INSERT INTO production.shift_section_revisions (
        id, tenant_id, shift_report_id, section_key, revision, snapshot, reason, actor_id, created_at
    )
    SELECT
        rev.id, rev.tenant_id, owner.shift_report_id, owner.section_key,
        (row_number() OVER (PARTITION BY owner.shift_report_id, owner.section_key ORDER BY rev.created_at, rev.id))::int,
        jsonb_build_object('legacy_report_id', rev.report_id, 'legacy_revision', rev.revision, 'detail', rev.detail),
        rev.reason, rev.actor_id, rev.created_at
    FROM production.report_revisions rev
    JOIN (
        SELECT id AS report_id, shift_report_id, 'runs' AS section_key FROM production.shift_runs
        UNION ALL
        SELECT id, shift_report_id, 'packing' FROM production.shift_packing_rows
    ) owner ON owner.report_id = rev.report_id
    ON CONFLICT DO NOTHING;

    UPDATE production.shift_report_sections s
    SET revision = c.n
    FROM (
        SELECT shift_report_id, section_key, count(*)::int AS n
        FROM production.shift_section_revisions
        GROUP BY shift_report_id, section_key
    ) c
    WHERE c.shift_report_id = s.shift_report_id AND c.section_key = s.section_key AND s.revision <> c.n;

    SELECT count(*) INTO total FROM production.shift_reports;
    RETURN total;
END;
$$;

SELECT production.convert_legacy_reports();
