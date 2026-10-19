-- Create historico_digi table
CREATE TABLE historico_digi (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL,
  pergunta TEXT NOT NULL,
  resposta TEXT NOT NULL,
  modo TEXT DEFAULT 'orientacao' CHECK (modo IN ('orientacao', 'resposta-cliente', 'bug')),
  score FLOAT DEFAULT 0 CHECK (score >= 0 AND score <= 1),
  chunks_used INT DEFAULT 0,
  processing_time_ms INT DEFAULT 0,
  pergunta_reescrita TEXT,
  fontes JSONB,
  canal TEXT,
  feedback TEXT CHECK (feedback IS NULL OR feedback IN ('positivo', 'negativo')),
  timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create index for fast user_id lookups
CREATE INDEX idx_historico_user_id ON historico_digi(user_id, timestamp DESC);

-- Enable RLS (Row Level Security) - Required for production data protection
ALTER TABLE historico_digi ENABLE ROW LEVEL SECURITY;

-- Access is server-side only. service_role bypasses RLS; public roles receive
-- no direct table privileges.
REVOKE ALL ON TABLE historico_digi FROM anon, authenticated;
