"""rpy2 boilerplate -- R as the statistics backend.

Needs a local R install (`brew install r`) before `pip install rpy2` will build.

The pattern: keep the actual statistics in R source (R_SOURCE below, or a .R
file you source), hand it plain vectors, and convert the result back to python
primitives at the boundary. Nothing above this module should touch an R object.
"""

R_SOURCE = """
summarize <- function(scores) {
    list(
        n      = length(scores),
        mean   = mean(scores),
        median = median(scores),
        sd     = if (length(scores) > 1) sd(scores) else NA_real_
    )
}

# The eventual reason for any of this: solve the OPR least-squares system.
# design is a match x team 0/1 matrix, scores is one value per match.
opr <- function(design, scores) {
    fit <- qr.solve(design, scores)
    as.vector(fit)
}
"""

_r_pkg = None


def r_pkg():
    """Compile R_SOURCE once and hand back the namespace holding its functions."""
    global _r_pkg

    if _r_pkg is None:
        from rpy2.robjects.packages import STAP
        _r_pkg = STAP(R_SOURCE, "grimoire")

    return _r_pkg


def summarize(scores):
    """list[int] -> dict of summary statistics, computed in R."""
    import rpy2.robjects as ro

    result = r_pkg().summarize(ro.IntVector(scores))

    # Every slot in that R list is a length-1 vector; unwrap to python scalars.
    return {name: result.rx2(name)[0] for name in result.names}


def opr(design, scores):
    """design: list of equal-length 0/1 rows. scores: one value per row."""
    import rpy2.robjects as ro

    rows = len(design)
    cols = len(design[0]) if rows else 0

    # R fills matrices column-major, so feed it column by column.
    flat = [design[r][c] for c in range(cols) for r in range(rows)]
    matrix = ro.r["matrix"](ro.FloatVector(flat), nrow=rows, ncol=cols)

    return list(r_pkg().opr(matrix, ro.FloatVector(scores)))


if __name__ == "__main__":
    print(summarize([40, 55, 61, 72, 39]))
