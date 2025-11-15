-- up
CREATE EXTENSION IF NOT EXISTS pg_uuidv7;

-- Sets NEW.updated_at = now() if such a column exists on the table.
CREATE OR REPLACE FUNCTION set_updated_at_if_exists()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  col text := COALESCE(TG_ARGV[0], 'updated_at');
  has_col boolean;
BEGIN
  SELECT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = TG_TABLE_SCHEMA
      AND table_name   = TG_TABLE_NAME
      AND column_name  = col
  ) INTO has_col;

  IF has_col AND TG_OP = 'UPDATE' THEN
    NEW := jsonb_populate_record(NEW, jsonb_build_object(col, now()));
  END IF;

  RETURN NEW;
END;
$$;

-- Auto-attach row triggers after CREATE/ALTER TABLE (requires superuser)
CREATE OR REPLACE FUNCTION attach_updated_at_triggers_after_ddl()
RETURNS event_trigger
LANGUAGE plpgsql
AS $$
DECLARE
  obj record;
  sch text;
  tbl text;
  ident text;
  trig_name text;
BEGIN
  FOR obj IN SELECT * FROM pg_event_trigger_ddl_commands() LOOP
    -- We only care about tables (CREATE TABLE / ALTER TABLE, etc.)
    IF obj.object_type ILIKE 'table%' THEN
      ident := obj.object_identity;      -- e.g. 'public.users' or just 'users'
      sch   := obj.schema_name;

      -- Derive schema/table from object_identity if schema_name is NULL
      IF sch IS NULL OR sch = '' THEN
        -- If identity contains a dot, split; else assume current schema
        IF position('.' IN ident) > 0 THEN
          sch := split_part(ident, '.', 1);
          tbl := split_part(ident, '.', 2);
        ELSE
          sch := current_schema();
          tbl := ident;
        END IF;
      ELSE
        -- schema_name is present; extract table from identity if needed
        IF tbl IS NULL OR tbl = '' THEN
          IF position('.' IN ident) > 0 THEN
            tbl := split_part(ident, '.', 2);
          ELSE
            tbl := ident;
          END IF;
        END IF;
      END IF;

      -- Skip system schemas
      IF sch IN ('pg_catalog','information_schema') THEN
        CONTINUE;
      END IF;

      -- Only attach if the table has an 'updated_at' column
      IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = sch
          AND table_name   = tbl
          AND column_name  = 'updated_at'
      ) THEN
        trig_name := format('trg_set_%s_updated_at', tbl);

        IF NOT EXISTS (
          SELECT 1 FROM pg_trigger
          WHERE tgname = trig_name
            AND tgrelid = format('%I.%I', sch, tbl)::regclass
        ) THEN
          EXECUTE format($f$
            CREATE TRIGGER %I
            BEFORE UPDATE ON %I.%I
            FOR EACH ROW
            EXECUTE FUNCTION set_updated_at_if_exists()
          $f$, trig_name, sch, tbl);
        END IF;
      END IF;
    END IF;
  END LOOP;
END;
$$;

CREATE EVENT TRIGGER et_updated_at_auto_attach
  ON ddl_command_end
  EXECUTE FUNCTION attach_updated_at_triggers_after_ddl();

-- Tables
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255), -- nullable to allow OAuth users
    full_name VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    is_superuser BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_identities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_user_id TEXT NOT NULL,
    email VARCHAR(255),
    email_verified BOOLEAN,
    profile JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT user_identities_provider_uid UNIQUE (provider, provider_user_id),
    CONSTRAINT user_identities_user_provider UNIQUE (user_id, provider)
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    jti VARCHAR(255) UNIQUE NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    issued_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    ip_address INET,
    user_agent VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, user_agent)
);

-- Helpful FK index
CREATE INDEX IF NOT EXISTS idx_user_identities_user_id ON user_identities(user_id);

-- down
DROP INDEX IF EXISTS idx_user_identities_user_id;

DROP TABLE IF EXISTS user_sessions;
DROP TABLE IF EXISTS user_identities;
DROP TABLE IF EXISTS users;

DROP EVENT TRIGGER IF EXISTS et_updated_at_auto_attach;
DROP FUNCTION IF EXISTS attach_updated_at_triggers_after_ddl();
DROP FUNCTION IF EXISTS set_updated_at_if_exists();
