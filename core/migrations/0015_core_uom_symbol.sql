-- What a unit looks like next to a number.
--
-- `code` is an identifier: short, ASCII, unique per tenant, and the thing every
-- import and API call keys on. It was also, until now, what the screens printed —
-- which is how a French plant ended up reading "5 ea" for five packets. The two
-- jobs are different and a single column could not do both without either
-- breaking integrations or lying to the reader.
--
-- `symbol` is the printed form. It carries no uniqueness rule: two units may
-- legitimately print the same way, and forcing them apart would be inventing a
-- distinction the reader does not make.
ALTER TABLE core.uoms ADD COLUMN IF NOT EXISTS symbol TEXT;

-- Seed the conventional forms. Codes outside this list keep printing as the code,
-- which is the honest fallback: a made-up symbol is worse than a technical one.
UPDATE core.uoms SET symbol = CASE lower(code)
        WHEN 'ea' THEN 'pièce'
        WHEN 'unit' THEN 'pièce'
        WHEN 'pcs' THEN 'pièce'
        WHEN 'kg' THEN 'kg'
        WHEN 'g' THEN 'g'
        WHEN 'ton' THEN 't'
        WHEN 't' THEN 't'
        WHEN 'l' THEN 'L'
        WHEN 'ml' THEN 'mL'
        WHEN 'm' THEN 'm'
        WHEN 'cm' THEN 'cm'
        WHEN 'mm' THEN 'mm'
        WHEN 'm2' THEN 'm²'
        WHEN 'm3' THEN 'm³'
        WHEN 'h' THEN 'h'
        WHEN 'kwh' THEN 'kWh'
        ELSE code
    END
WHERE symbol IS NULL;

COMMENT ON COLUMN core.uoms.symbol IS
    'How the unit prints next to a quantity ("pièce", "kg", "t"). Falls back to code when unset. Never used as a key.';
