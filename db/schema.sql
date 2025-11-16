CREATE TABLE IF NOT EXISTS users (
    -- Primary key
    id SERIAL PRIMARY KEY,

    -- Separate names
    first_name TEXT NOT NULL,
    last_name  TEXT NOT NULL,

    -- Login identifiers
    username   TEXT NOT NULL UNIQUE,
    email      TEXT NOT NULL UNIQUE,

    -- Security
    password_hash TEXT NOT NULL,

    -- Role with default value
    role TEXT NOT NULL DEFAULT 'regular',

    -- USERNAME CONSTRAINTS

    -- length 3–15
    CONSTRAINT chk_username_length
        CHECK (char_length(username) BETWEEN 3 AND 15),

    -- allowed chars + must start/end with letter/digit:
    --   start: [A-Za-z0-9]
    --   middle: [A-Za-z0-9._-]*
    --   end: [A-Za-z0-9]
    CONSTRAINT chk_username_chars
        CHECK (username ~ '^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$'),

    -- no two special chars (. _ -) in a row
    CONSTRAINT chk_username_no_double_special
        CHECK (username !~ '(\.|_|-){2,}'),

    -- disallow reserved names (case-insensitive)
    CONSTRAINT chk_username_not_reserved
        CHECK (lower(username) NOT IN ('admin', 'root', 'support', 'system', 'null')),

    -- EMAIL CONSTRAINTS

    -- basic email format local@domain.tld
    CONSTRAINT chk_email_format
        CHECK (
            email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
        ),

    -- length: total ≤ 254, local part ≤ 64
    CONSTRAINT chk_email_length
        CHECK (
            char_length(email) <= 254
            AND char_length(split_part(email, '@', 1)) <= 64
        ),

    -- ROLE CONSTRAINTS
    CONSTRAINT chk_role_allowed
        CHECK (role IN (
            'regular',
            'admin',
            'facility_manager',
            'moderator',
            'auditor',
            'service_account'
        ))
);
