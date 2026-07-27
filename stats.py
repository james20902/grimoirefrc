"""R statistics backend, and the async assembly of fit_pridge()'s `matches` arg.

Needs a local R install (`brew install r`) plus scoutR, which supplies the
lineup_design_matrix() and tf() that prior_ridge.R leans on.

Concurrency shape: only the postgres reads go off-thread (psycopg2 blocks).
Everything that touches R stays on the event loop's own thread, so R is only
ever entered one call at a time -- rpy2 is not thread safe and R's interpreter
is single threaded. Awaiting many events therefore overlaps the I/O you're
waiting on without ever overlapping the R conversions.
"""

import asyncio
import os

import db


DEFAULT_BURST = 10

R_SOURCE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prior_ridge.R")

STATION_COLUMNS = ("red1", "red2", "red3", "blue1", "blue2", "blue3")

# fit_pridge() reads its response as blue_<name> / red_<name> and defaults
# response_name to "score". Map that vocabulary onto our actual db columns.
RESPONSE_COLUMNS = {
    "score": ("score_red_final", "score_blue_final"),
    "auto": ("score_red_auto", "score_blue_auto"),
    "foul": ("score_red_foul", "score_blue_foul"),
}

LEVEL_PATTERNS = {"qual": "qual%", "playoff": "play%", "all": "%"}

# A half-populated row is useless to the model: a NULL team or NULL score rides
# into the design matrix as NA and turns the whole solve into NaN.
NOT_NULL = " AND ".join("{} IS NOT NULL".format(c) for c in STATION_COLUMNS)

_r_pkg = None


def r_context():
    """Conversion rules for any block that touches R.

    rpy2 keeps its py2rpy/rpy2py rules in a contextvars.ContextVar, so they are
    visible only in the context that imported rpy2.robjects -- not globally. An
    asyncio Task runs in a *copy* of the context, and a thread starts with none
    of it, so either can end up with no rules at all and raise instead of
    falling back to defaults. Entering this makes the rules explicit and leaves
    the R calls independent of whatever context they happen to run in.
    """
    from rpy2.robjects import default_converter
    from rpy2.robjects.conversion import localconverter

    return localconverter(default_converter)


def r_pkg():
    """Compile R_SOURCE once and hand back the namespace holding its functions."""
    global _r_pkg

    if _r_pkg is None:
        with open(R_SOURCE_PATH, "r") as f:
            from rpy2.robjects.packages import STAP
            with r_context():
                _r_pkg = STAP(f.read(), "prior_ridge")

    return _r_pkg


def frame_sql(response_name):
    """SQL for one event. Column names come from constants, never user input."""
    if response_name not in RESPONSE_COLUMNS:
        raise ValueError("unknown response_name {!r}, expected one of {}".format(
            response_name, sorted(RESPONSE_COLUMNS)))

    red_col, blue_col = RESPONSE_COLUMNS[response_name]

    return """
        SELECT {stations}, {red_col}, {blue_col}
        FROM matches
        WHERE event_code = %s
          AND tournament_level ILIKE %s
          AND {not_null}
          AND {red_col} IS NOT NULL
          AND {blue_col} IS NOT NULL
        ORDER BY match_number
    """.format(stations=", ".join(STATION_COLUMNS), red_col=red_col,
               blue_col=blue_col, not_null=NOT_NULL)


def team_key(number, team_format="tba"):
    """449 -> "frc449". fit_pridge names priors tba-style and calls tf() on them."""
    if team_format == "tba":
        return "frc{}".format(number)
    if team_format == "number":
        return str(number)

    raise ValueError("unknown team_format {!r}".format(team_format))


def columns_from_rows(rows, response_name="score", team_format="tba"):
    """Row tuples -> the column dict fit_pridge wants, still pure python."""
    columns = {name: [] for name in STATION_COLUMNS}
    columns["red_" + response_name] = []
    columns["blue_" + response_name] = []

    for row in rows:
        teams, red_score, blue_score = row[:6], row[6], row[7]

        for name, number in zip(STATION_COLUMNS, teams):
            columns[name].append(team_key(number, team_format))

        columns["red_" + response_name].append(red_score)
        columns["blue_" + response_name].append(blue_score)

    return columns


def to_r_dataframe(columns):
    """Column dict -> R data.frame. Reaches into R, so loop thread only.

    The returned data.frame stays valid outside r_context(); only further
    conversions need the rules, not the object itself.
    """
    import rpy2.robjects as ro

    data = {}
    for name, values in columns.items():
        if name in STATION_COLUMNS:
            # Character, not factor -- scoutR matches these against names(priors).
            data[name] = ro.StrVector(values)
        else:
            data[name] = ro.FloatVector([float(v) for v in values])

    # DataFrame() runs each column back through py2rpy, which is exactly the
    # call that fails with no rules in context.
    with r_context():
        return ro.DataFrame(data)


async def event_frame(event_code, response_name="score", level="qual",
                      team_format="tba"):
    """One event -> the R data.frame for fit_pridge()'s `matches` argument.

    The query is the slow part and is the only thing handed to a worker thread;
    the R conversion happens back on the calling thread.
    """
    if level not in LEVEL_PATTERNS:
        raise ValueError("unknown level {!r}, expected one of {}".format(
            level, sorted(LEVEL_PATTERNS)))

    rows = await asyncio.to_thread(db.query, frame_sql(response_name),
                                   (event_code, LEVEL_PATTERNS[level]))

    return to_r_dataframe(columns_from_rows(rows, response_name, team_format))


#' @param matches (data.frame) dataframe of matches; assumed to have `red1`,
#' `red2`, `red3`, `blue1`, etc. as team entries, and 2 columns representing
#' the response named "(red/blue)_(responseName)"
#' @param priors (numeric) vector of priors to regularize towards, named with
#' tba-legal team identifiers (i.e. "frc449")
#' @param response_name (character) name of the response vectors as they appear
#' in `matches`
#' @param grid (numeric) Grid of lambda values to consider for regularization
#' @param n_cores the number of cores on your machine to reserve for
#' calculation. If NULL, will default to the max - 1.
#' @param digits (integer) number of digits to round the result to
def fit_prior_ridge(matches, priors, response_name="score"):
    """matches data.frame + named priors vector -> {team key: coefficient}."""
    with r_context():
        result = r_pkg().fit_pridge(matches, priors, response_name=response_name)

        # fit_pridge returns a named numeric vector, one entry per team.
        return dict(zip(result.names, list(result)))


if __name__ == "__main__":
   print("do not run me alone!")
