"""FastAPI boilerplate -- the real query API goes here.

    uvicorn api:app --reload      # http://127.0.0.1:8000/docs

Right now this just re-serves what db.py already knows how to read. The /stats
route is the seam where R computation plugs in; see stats.py.
"""

from fastapi import FastAPI, HTTPException

import db
import stats


app = FastAPI(title="grimoirefrc", version="0.1.0")


@app.get("/health")
def health():
    """Cheap liveness check that also proves the db connection works."""
    try:
        db.query("SELECT 1")
    except Exception as e:
        raise HTTPException(status_code=503, detail="database unreachable: {}".format(e))

    return {"status": "ok"}


@app.get("/events")
def events():
    return {"events": db.list_events()}


@app.get("/events/{event_code}/matches")
def event_matches(event_code: str):
    matches = db.matches_as_dicts(event_code.upper())

    if not matches:
        raise HTTPException(status_code=404, detail="no matches for {}".format(event_code))

    return {"event_code": event_code.upper(), "count": len(matches), "matches": matches}


@app.get("/events/{event_code}/stats/scores")
def event_score_stats(event_code: str):
    """Example of the round trip: postgres -> python -> R -> json."""
    matches = db.matches_as_dicts(event_code.upper())

    if not matches:
        raise HTTPException(status_code=404, detail="no matches for {}".format(event_code))

    scores = [m["score_red_final"] for m in matches if m["score_red_final"] is not None]
    scores += [m["score_blue_final"] for m in matches if m["score_blue_final"] is not None]

    if not scores:
        raise HTTPException(status_code=409, detail="matches exist but none are scored")

    return {"event_code": event_code.upper(), "summary": stats.summarize(scores)}
