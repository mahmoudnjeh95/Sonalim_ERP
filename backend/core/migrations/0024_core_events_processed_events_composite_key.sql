-- events.processed_events was keyed on event_id alone (docker/postgres/init.sql), but
-- core.events.consumers._process checks idempotency per (event_id, consumer) -- an event
-- with two or more registered consumers (e.g. sales.order.confirmed -> finance + warehouse,
-- payroll.run.approved -> finance + hr) always fails the second consumer's own bookkeeping
-- insert with a duplicate-key error, once the first consumer has already recorded that
-- event_id. That exception rolls back the second consumer's handler along with it, forever
-- (a retry hits the same duplicate key), so any event with more than one consumer has only
-- ever been delivered to whichever consumer happens to run first.
--
-- No existing row can violate the new key: the bug above means at most one row per event_id
-- was ever successfully committed.
ALTER TABLE events.processed_events DROP CONSTRAINT processed_events_pkey;
ALTER TABLE events.processed_events ADD PRIMARY KEY (event_id, consumer);
