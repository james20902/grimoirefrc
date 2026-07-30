"""Read side of the matches table. Shared by server.py and api.py.

No ORM, no relations -- just the queries the viewer needs. populate_db.py keeps
its own connection helper so the ingest script stays standalone.
"""

import os
from contextlib import closing

import psycopg2


# Each team is followed by its own pre/post epa rather than grouping all the
# epas at the end -- the viewer renders these positionally, and a station's epa
# is only readable next to the team it belongs to.
MATCH_COLUMNS = (
    "match_id", "tournament_level", "match_number",
    "red1", "red1_pre_epa", "red1_post_epa",
    "red2", "red2_pre_epa", "red2_post_epa",
    "red3", "red3_pre_epa", "red3_post_epa",
    "blue1", "blue1_pre_epa", "blue1_post_epa",
    "blue2", "blue2_pre_epa", "blue2_post_epa",
    "blue3", "blue3_pre_epa", "blue3_post_epa",
    "score_red_final", "score_red_auto", "score_red_foul",
    "score_blue_final", "score_blue_auto", "score_blue_foul",
)

# Quals first, then playoffs, each in match order. The %% is escaped for
# psycopg2's own parameter interpolation.
MATCHES_FOR_EVENT = """
SELECT {columns}
FROM matches
WHERE event_code = %s
ORDER BY CASE WHEN tournament_level ILIKE 'qual%%' THEN 0 ELSE 1 END, match_number
""".format(columns=", ".join(MATCH_COLUMNS))

EVENT_CODES = "SELECT DISTINCT event_code FROM matches ORDER BY event_code"


def connect_db():
    return psycopg2.connect(database=os.getenv("DB_NAME"),
                            user=os.getenv("DB_USER"),
                            password=os.getenv("DB_PASSWORD"),
                            host=os.getenv("DB_HOST", "localhost"),
                            port=os.getenv("DB_PORT", "5432"))


def query(sql, params=()):
    """Run one read and hand back every row. Connection per call -- fine at this size."""
    with closing(connect_db()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def list_events():
    return [row[0] for row in query(EVENT_CODES)]


def matches_for_event(event_code):
    return query(MATCHES_FOR_EVENT, (event_code,))


def matches_as_dicts(event_code):
    """Same rows, keyed by column name -- what the json API wants."""
    return [dict(zip(MATCH_COLUMNS, row)) for row in matches_for_event(event_code)]
