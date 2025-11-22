import psycopg2
from psycopg2.extras import RealDictCursor
from common.config import DATABASE_URL

def get_connection():
    """
    Create and return a new database connection.
    Uses DATABASE_URL from common.config.
    """
    return psycopg2.connect(DATABASE_URL)

def init_reviews_table():
    create_reviews_table_sql = """
    CREATE TABLE IF NOT EXISTS reviews (
        review_id SERIAL PRIMARY KEY,
        room_id INT NOT NULL,
        user_id INT NOT NULL,
        rating INT CHECK (rating BETWEEN 1 AND 5), -- Rating between 1 and 5
        comment TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (room_id) REFERENCES rooms(room_id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(create_reviews_table_sql)
    finally:
        conn.close()


def create_review(room_id, user_id, rating, comment):
    """
    Insert a new review into the database.
    Validates that the rating is between 1 and 5.
    """
    if not (1 <= rating <= 5):
        raise ValueError("Rating must be between 1 and 5.")

    insert_sql = """
    INSERT INTO reviews (room_id, user_id, rating, comment)
    VALUES (%s, %s, %s, %s)
    RETURNING review_id, room_id, user_id, rating, comment, created_at;
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(insert_sql, (room_id, user_id, rating, comment))
                return cur.fetchone()
    finally:
        conn.close()

def fetch_review_by_id(review_id):
    """
    Fetch a single review by its ID.
    """
    select_sql = """
    SELECT review_id, room_id, user_id, rating, comment, created_at
    FROM reviews
    WHERE review_id = %s;
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(select_sql, (review_id,))
                return cur.fetchone()
    finally:
        conn.close()

def update_review(review_id, rating=None, comment=None):
    """
    Update an existing review's rating and/or comment.
    """
    fields = []
    values = []
    if rating is not None:
        fields.append("rating = %s")
        values.append(rating)
    if comment is not None:
        fields.append("comment = %s")
        values.append(comment)
    values.append(review_id)
    fields.append("created_at = NOW()")
    update_sql = f"""
    UPDATE reviews
    SET {', '.join(fields)}
    WHERE review_id = %s
    RETURNING review_id, room_id, user_id, rating, comment, created_at;
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(update_sql, tuple(values))
                return cur.fetchone()
    finally:
        conn.close()


def delete_review(review_id):
    """
    Delete a review by its review_id.
    """
    delete_sql = """
    DELETE FROM reviews
    WHERE review_id = %s;
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(delete_sql, (review_id,))
                return cur.rowcount  # Returns number of rows deleted
    finally:
        conn.close()

def fetch_review_by_room_id(room_id):
    """
    Fetch a single review by its ID.
    """
    select_sql = """
    SELECT review_id, room_id, user_id, rating, comment, created_at
    FROM reviews
    WHERE room_id = %s;
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(select_sql, (room_id,))
                return cur.fetchall()
    finally:
        conn.close()

def report_review(review_id, reporter_user_id, reason):
    """
    Report a review for inappropriate content.
    """
    insert_sql = """
    INSERT INTO review_reports (review_id, reporter_user_id, reason)
    VALUES (%s, %s, %s);
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(insert_sql, (review_id, reporter_user_id, reason))
                return cur.rowcount  # Returns number of rows inserted
    finally:
        conn.close()


def init_reports_table():
    """
    Initialize the reports table in the database.
    """
    create_enum_sql = """
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
    """

    create_reports_table_sql = """
    CREATE TABLE IF NOT EXISTS reports (
        report_id SERIAL PRIMARY KEY,
        review_id INT NOT NULL,
        reporter_user_id INT NOT NULL,
        report_reason report_reason_enum NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (review_id) REFERENCES reviews(review_id),
        FOREIGN KEY (reporter_user_id) REFERENCES users(id)
    );
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                # Create the ENUM type if it doesn't exist
                cur.execute(create_enum_sql)
                # Create the reports table
                cur.execute(create_reports_table_sql)
    finally:
        conn.close()


def report_review(review_id, reporter_user_id, reason):
    """
    Report a review for inappropriate content.
    """
    insert_sql = """
    INSERT INTO reports (review_id, reporter_user_id, report_reason)
    VALUES (%s, %s, %s)
    RETURNING report_id, review_id, reporter_user_id, report_reason, created_at;
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(insert_sql, (review_id, reporter_user_id, reason))
                return cur.fetchone()  
    finally:
        conn.close()