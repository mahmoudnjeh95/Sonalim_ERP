-- The production IA assistant's chat history. Deliberately private per user, not
-- just per tenant: every query filters on user_id as well as tenant_id, so nobody
-- -- not even an admin -- can list or read another user's conversations. There is
-- no shared/team view of this data; it is a personal notebook, not a dashboard.
CREATE TABLE IF NOT EXISTS production.ia_assistant_conversations (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ia_assistant_conversations_user_idx
    ON production.ia_assistant_conversations (tenant_id, user_id, updated_at DESC);

-- tool_calls records which tools the assistant invoked to answer (and with what
-- arguments/results) so a past answer can be audited later without re-asking
-- Gemini -- the same reasoning as core.audit_log, applied to advice instead of
-- a mutation.
CREATE TABLE IF NOT EXISTS production.ia_assistant_messages (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES production.ia_assistant_conversations (id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    tool_calls JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ia_assistant_messages_conversation_idx
    ON production.ia_assistant_messages (tenant_id, conversation_id, created_at);
