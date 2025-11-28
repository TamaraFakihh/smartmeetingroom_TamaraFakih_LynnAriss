-- =====================================================
-- USERS TABLE
-- =====================================================
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

-- =====================================================
-- ROOMS TABLE
-- =====================================================
CREATE TABLE IF NOT EXISTS rooms (
    room_id SERIAL PRIMARY KEY,
    room_name TEXT NOT NULL UNIQUE,
    capacity INT NOT NULL CHECK (capacity > 0),
    location TEXT,
    is_available BOOLEAN DEFAULT TRUE,
    is_out_of_service BOOLEAN DEFAULT FALSE
);

-- =====================================================
-- EQUIPMENT TABLE
-- =====================================================
CREATE TABLE IF NOT EXISTS equipment (
    equipment_id SERIAL PRIMARY KEY,
    equipment_name TEXT NOT NULL UNIQUE
);

-- =====================================================
-- ROOM_EQUIPMENT TABLE (Many-to-Many Relationship)
-- =====================================================
CREATE TABLE IF NOT EXISTS room_equipment (
    room_id INT NOT NULL,
    equipment_id INT NOT NULL,
    quantity INT NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (room_id, equipment_id),
    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE,
    FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id) ON DELETE CASCADE
);

-- =====================================================
-- REVIEWS TABLE
-- =====================================================
CREATE TABLE IF NOT EXISTS reviews (
    review_id SERIAL PRIMARY KEY,
    room_id INT NOT NULL,
    user_id INT NOT NULL,
    rating INT CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_flagged BOOLEAN DEFAULT FALSE,
    is_hidden BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- =====================================================
-- REPORT REASON ENUM
-- =====================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'report_reason_enum') THEN
        CREATE TYPE report_reason_enum AS ENUM (
            'Inaccurate Review',
            'Harassment / Offensive Content',
            'Misleading Information',
            'Spam / Promotional Content',
            'Personal or Private Information',
            'Unfair Rating',
            'Not Relevant to the Room'
        );
    END IF;
END $$;

-- =====================================================
-- REPORTS TABLE
-- =====================================================
CREATE TABLE IF NOT EXISTS reports (
    report_id SERIAL PRIMARY KEY,
    review_id INT NOT NULL,
    reporter_user_id INT NOT NULL,
    report_reason report_reason_enum NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (review_id) REFERENCES reviews(review_id) ON DELETE CASCADE,
    FOREIGN KEY (reporter_user_id) REFERENCES users(id) ON DELETE CASCADE
);
