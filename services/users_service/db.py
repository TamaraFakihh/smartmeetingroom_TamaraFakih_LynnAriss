import psycopg2
from psycopg2.extras import RealDictCursor
from common.config import DATABASE_URL


def get_connection():
    """
    Create and return a new database connection.
    Uses DATABASE_URL from common.config.
    """
    return psycopg2.connect(DATABASE_URL)


def init_users_table():
    """
    Initialize the users table if it does not exist.
    Development convenience – in production you use migrations/schema.sql.
    """
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        first_name TEXT NOT NULL,
        last_name  TEXT NOT NULL,
        username   TEXT NOT NULL UNIQUE,
        email      TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'regular',
        CONSTRAINT chk_username_length
            CHECK (char_length(username) BETWEEN 3 AND 15),
        CONSTRAINT chk_username_chars
            CHECK (username ~ '^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$'),
        CONSTRAINT chk_username_no_double_special
            CHECK (username !~ '(\.|_|-){2,}'),
        CONSTRAINT chk_username_not_reserved
            CHECK (lower(username) NOT IN ('admin', 'root', 'support', 'system', 'null')),
        CONSTRAINT chk_email_format
            CHECK (
                email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$'
            ),
        CONSTRAINT chk_email_length
            CHECK (
                char_length(email) <= 254
                AND char_length(split_part(email, '@', 1)) <= 64
            ),
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
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(create_table_sql)
    finally:
        conn.close()


def fetch_one(query, params=None):
    """
    Helper to run a SELECT that returns a single row as a dict.
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params or ())
                return cur.fetchone()
    finally:
        conn.close()


def fetch_all(query, params=None):
    """
    Helper to run a SELECT that returns multiple rows as a list of dicts.
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params or ())
                return cur.fetchall()
    finally:
        conn.close()


def execute(query, params=None):
    """
    Helper to run INSERT/UPDATE/DELETE.
    Returns the number of affected rows.
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(query, params or ())
                return cur.rowcount
    finally:
        conn.close()
