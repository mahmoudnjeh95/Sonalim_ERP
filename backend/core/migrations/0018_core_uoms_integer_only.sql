-- Whether a quantity recorded in this unit must be a whole number.
--
-- `category` names the kind of thing being measured ("weight", "unit", ...) but
-- says nothing about whether it can be split -- 2.5 kg is a real quantity, 2.5
-- pièces never is. Today the platform's only discrete category is "unit" ("ea"),
-- so this backfills true there and false everywhere else; a future discrete
-- category, or a single discrete code inside an otherwise-continuous category,
-- can be marked this way without a code change once it exists.
ALTER TABLE core.uoms ADD COLUMN IF NOT EXISTS is_integer_only BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE core.uoms SET is_integer_only = TRUE WHERE category = 'unit' AND NOT is_integer_only;

COMMENT ON COLUMN core.uoms.is_integer_only IS
    'Whether a quantity posted in this unit must be a whole number (a carton, a pièce -- never a kg or a litre). Enforced wherever a quantity is about to post to warehouse stock.';
