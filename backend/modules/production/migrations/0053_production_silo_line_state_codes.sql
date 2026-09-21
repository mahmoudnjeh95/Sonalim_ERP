-- The silo's "état de la ligne" is now a choice, stored as a code. Older shifts typed it
-- as text; the two spellings the fiche used are turned into the codes, anything else is
-- left as typed (it still shows, and changes no machine).
UPDATE production.shift_silo_states SET line_state = 'running' WHERE lower(btrim(line_state)) = 'en marche';
UPDATE production.shift_silo_states SET line_state = 'stopped' WHERE lower(btrim(line_state)) IN ('en arrêt', 'en arret');
