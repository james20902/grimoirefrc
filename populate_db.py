import requests
import os
import base64
import json
import sys
import psycopg2
from psycopg2.extras import execute_values


BASE_URL = "https://frc-api.firstinspires.org/v3.0/"
SEASON = 2026

# Every team entry carries an explicit "station" ("Red1" ... "Blue3"). The array
# comes back in this order in practice, but the docs never promise it, so the
# parser keys off the station string instead of the array index.
STATIONS = ("Red1", "Red2", "Red3", "Blue1", "Blue2", "Blue3")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS matches (
    match_id         TEXT PRIMARY KEY,
    season           INTEGER NOT NULL,
    event_code       TEXT NOT NULL,
    tournament_level TEXT NOT NULL,
    match_number     INTEGER NOT NULL,
    red1             INTEGER,
    red2             INTEGER,
    red3             INTEGER,
    blue1            INTEGER,
    blue2            INTEGER,
    blue3            INTEGER,
    score_red_final  INTEGER,
    score_red_auto   INTEGER,
    score_red_foul   INTEGER,
    score_blue_final INTEGER,
    score_blue_auto  INTEGER,
    score_blue_foul  INTEGER
)
"""

UPSERT_MATCHES = """
INSERT INTO matches (
    match_id, season, event_code, tournament_level, match_number,
    red1, red2, red3, blue1, blue2, blue3,
    score_red_final, score_red_auto, score_red_foul,
    score_blue_final, score_blue_auto, score_blue_foul
) VALUES %s
ON CONFLICT (match_id) DO UPDATE SET
    red1             = EXCLUDED.red1,
    red2             = EXCLUDED.red2,
    red3             = EXCLUDED.red3,
    blue1            = EXCLUDED.blue1,
    blue2            = EXCLUDED.blue2,
    blue3            = EXCLUDED.blue3,
    score_red_final  = EXCLUDED.score_red_final,
    score_red_auto   = EXCLUDED.score_red_auto,
    score_red_foul   = EXCLUDED.score_red_foul,
    score_blue_final = EXCLUDED.score_blue_final,
    score_blue_auto  = EXCLUDED.score_blue_auto,
    score_blue_foul  = EXCLUDED.score_blue_foul
"""


def auth_header():
    authorization = "{}:{}".format(os.getenv("FRC_EVENTS_API_USER"),
                                   os.getenv("FRC_EVENTS_API_TOKEN"))
    return 'Basic {}'.format(base64.b64encode(authorization.encode()).decode())


def generate_request(endpoint, params=None):
    """GET BASE_URL + endpoint and hand back the decoded json, or None on failure."""
    url = "{}{}".format(BASE_URL, endpoint)

    headers = {
        'Authorization': auth_header(),
        'If-Modified-Since': ''
    }

    try:
        response = requests.request("GET", url, headers=headers, params=params)

        if not (response.ok):
            raise Exception(f"Response not valid, code {response.status_code}: {response.reason}")

        return json.loads(response.text)
    except Exception as e:
        print("request to {} failed: {}".format(url, e))
        return None


def get_events(year):
    """Every event in a season. /v3.0/{season}/events"""
    return generate_request("{}/events?districtCode=FCH".format(year))


def get_event_matches(year, event_code, tournament_level="qual"):
    """Every match at one event. /v3.0/{season}/matches/{eventCode}

    The API namespaces matches under a season, so the year comes along for the
    ride. tournament_level is "qual" or "playoff" -- the endpoint rejects the
    request without one.
    """
    params = {'tournamentLevel': tournament_level}

    return generate_request("{}/matches/{}".format(year, event_code), params=params)


def build_match_id(season, event_code, tournament_level, match_number):
    """e.g. 2026mdbet_qm1

    The API never hands back a single combined key, so we glue one together out
    of the season, the event code, and the level/number pair. The season prefix
    keeps the id unique once more than one year is loaded.
    """
    level = "qm" if tournament_level.lower().startswith("qual") else "p"

    return "{}{}_{}{}".format(season, event_code.lower(), level, match_number)


def parse_match(season, event_code, match):
    """Flatten one API match object into a row tuple for the matches table."""
    teams = {t['station']: t['teamNumber'] for t in match.get('teams', [])}

    return (
        build_match_id(season, event_code, match['tournamentLevel'], match['matchNumber']),
        season,
        event_code.upper(),
        match['tournamentLevel'],
        match['matchNumber'],
        *(teams.get(station) for station in STATIONS),
        match.get('scoreRedFinal'),
        match.get('scoreRedAuto'),
        match.get('scoreRedFoul'),
        match.get('scoreBlueFinal'),
        match.get('scoreBlueAuto'),
        match.get('scoreBlueFoul'),
    )


def store_matches(conn, rows):
    if not rows:
        return 0

    with conn.cursor() as cur:
        execute_values(cur, UPSERT_MATCHES, rows)
    conn.commit()

    return len(rows)


def connect_db():
    return psycopg2.connect(database=os.getenv("DB_NAME"),
                            user=os.getenv("DB_USER"),
                            password=os.getenv("DB_PASSWORD"),
                            host=os.getenv("DB_HOST", "localhost"),
                            port=os.getenv("DB_PORT", "5432"))


if __name__ == "__main__":
    print("welcome to the database populator woohoo")

    for key in ("FRC_EVENTS_API_USER", "FRC_EVENTS_API_TOKEN", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        if not os.getenv(key):
            print("missing environment variable {}, exiting...".format(key))
            sys.exit(1)

    print("connecting to db")
    try:
        conn = connect_db()
        print("Database connected successfully")
    except Exception as e:
        print("Database not connected successfully")
        print("fatal error, {}, exiting...".format(e))
        sys.exit(1)

    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE)
    conn.commit()

    events = get_events(SEASON)
    if events is None:
        print("could not fetch events for {}, exiting...".format(SEASON))
        conn.close()
        sys.exit(1)

    print("found {} events in {}".format(events['eventCount'], SEASON))

    total = 0
    for e in events['Events']:
        code = e['code']
        rows = []

        # An event that never ran playoffs just 404s on the second pass, which
        # generate_request already reports and swallows.
        for level in ("qual", "playoff"):
            payload = get_event_matches(SEASON, code, tournament_level=level)
            if payload is None:
                continue

            for match in payload.get('Matches', []):
                rows.append(parse_match(SEASON, code, match))

        try:
            stored = store_matches(conn, rows)
        except Exception as ex:
            print("{}: failed to store matches: {}".format(code, ex))
            conn.rollback()
            continue

        total += stored
        print("{}: stored {} matches".format(code, stored))

    print("done, {} matches written for {}".format(total, SEASON))
    conn.close()
