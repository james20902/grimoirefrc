"""Crappy little match viewer -- stdlib only.

    python3 server.py        # then open http://localhost:8000/

Pick an event from the dropdown, hit show, get every match row for it.
"""

import html
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import db


# "pre"/"post" are the statbotics epas for the team in the column to their left.
HEADERS = ("match", "level", "#",
           "red 1", "pre", "post",
           "red 2", "pre", "post",
           "red 3", "pre", "post",
           "blue 1", "pre", "post",
           "blue 2", "pre", "post",
           "blue 3", "pre", "post",
           "red", "red auto", "red foul",
           "blue", "blue auto", "blue foul")

# Cell classes, positionally matched to db.MATCH_COLUMNS, just to tint the
# alliance columns so the table is readable. The epa cells keep their alliance
# tint but get muted text so the team numbers still carry the row.
CLASSES = ("id", "", "",
           "red", "red epa", "red epa",
           "red", "red epa", "red epa",
           "red", "red epa", "red epa",
           "blue", "blue epa", "blue epa",
           "blue", "blue epa", "blue epa",
           "blue", "blue epa", "blue epa",
           "red", "red", "red",
           "blue", "blue", "blue")

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>grimoirefrc matches</title>
<style>
body {{ font-family: monospace; margin: 2rem; }}
table {{ border-collapse: collapse; margin-top: 1rem; }}
th, td {{ border: 1px solid #999; padding: 2px 8px; text-align: right; }}
th {{ background: #eee; }}
td.id {{ text-align: left; }}
td.red {{ background: #ffe6e6; }}
td.blue {{ background: #e6e6ff; }}
td.epa {{ color: #666; }}
</style>
</head>
<body>
<h1>matches</h1>
<form method="get" action="/">
<select name="event">
{options}
</select>
<button type="submit">show</button>
</form>
{table}
</body>
</html>
"""


def render_options(events, selected):
    out = []
    for code in events:
        flag = " selected" if code == selected else ""
        out.append('<option value="{0}"{1}>{0}</option>'.format(html.escape(code), flag))
    return "\n".join(out)


def render_table(rows):
    if not rows:
        return "<p>no matches for that event</p>"

    head = "".join("<th>{}</th>".format(html.escape(h)) for h in HEADERS)

    body = []
    for row in rows:
        cells = []
        for value, css in zip(row, CLASSES):
            text = "" if value is None else html.escape(str(value))
            cells.append('<td class="{}">{}</td>'.format(css, text))
        body.append("<tr>{}</tr>".format("".join(cells)))

    return "<table>\n<tr>{}</tr>\n{}\n</table>".format(head, "\n".join(body))


def render_page(selected):
    events = db.list_events()

    if not events:
        return PAGE.format(options="", table="<p>no matches in the database yet</p>")

    # Anything not actually in the table falls back to the first event, so a
    # hand-typed query string can't put the page in a weird state.
    if selected not in events:
        selected = events[0]

    return PAGE.format(options=render_options(events, selected),
                       table=render_table(db.matches_for_event(selected)))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path != "/":
            self.send_error(404, "nothing here")
            return

        selected = parse_qs(parsed.query).get("event", [None])[0]

        try:
            page = render_page(selected)
        except Exception as e:
            self.respond(500, "<h1>db error</h1><pre>{}</pre>".format(html.escape(str(e))))
            return

        self.respond(200, page)

    def respond(self, code, body):
        encoded = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))

    print("serving on http://localhost:{}/".format(port))
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
