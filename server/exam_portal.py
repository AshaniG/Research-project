#!/usr/bin/env python3
"""
exam_portal.py - A realistic "victim" web service for the DDoS-detection lab.

It serves a fictional university EXAM RESULTS PORTAL: students can be listed,
searched, and looked up by ID. This stands in for a real web application so that
when the attacker floods it, you are protecting something that looks and behaves
like a genuine service (not an empty page).

The XDP/eBPF detector runs in front of this on the SAME machine and drops flood
traffic before it reaches this server, so legitimate result look-ups keep working
during an attack — that contrast is the core experiment.

Run (on the TARGET / victim server):
    python3 server/exam_portal.py                 # listens on 0.0.0.0:8080
    python3 server/exam_portal.py 0.0.0.0 80      # custom host/port

The dataset (server/exam_results.json) is auto-generated on first run if missing;
regenerate or resize it with:
    python3 server/generate_exam_data.py -n 500

Endpoints:
    GET /                       HTML portal home (search box + stats)
    GET /student?id=S0001       HTML page for one student's results
    GET /api/results            JSON: all students
    GET /api/results?id=S0001   JSON: one student
    GET /healthz                plain-text health/uptime (for load checks)
"""
import html
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "exam_results.json")

START = time.time()
HITS = 0


def load_students():
    """Load the dataset, generating it on the fly if it doesn't exist yet."""
    if not os.path.exists(DATA_PATH):
        # Import the generator sitting next to us and build a default dataset.
        sys.path.insert(0, HERE)
        import generate_exam_data
        students = generate_exam_data.generate()
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(students, f, indent=2)
        print(f"[*] Generated dataset: {DATA_PATH} ({len(students)} students)")
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


STUDENTS = load_students()
BY_ID = {s["student_id"]: s for s in STUDENTS}


# --- HTML rendering (stdlib only, inline CSS) ----------------------------
PAGE_CSS = """
body{font-family:system-ui,Arial,sans-serif;max-width:900px;margin:2rem auto;
padding:0 1rem;color:#1a1a1a;background:#fafafa}
h1{margin-bottom:.25rem}.sub{color:#666;margin-top:0}
table{border-collapse:collapse;width:100%;margin-top:1rem;background:#fff}
th,td{border:1px solid #ddd;padding:.5rem .75rem;text-align:left}
th{background:#f0f3f7}tr:nth-child(even){background:#f7f9fb}
.card{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:1rem 1.25rem;margin:1rem 0}
a{color:#1558d6;text-decoration:none}a:hover{text-decoration:underline}
input,button{font-size:1rem;padding:.5rem}.pill{display:inline-block;background:#eef;
padding:.15rem .6rem;border-radius:1rem;font-size:.85rem}
.grade-A{color:#0a7d29;font-weight:600}.grade-B{color:#8a6d00;font-weight:600}
.grade-C{color:#b05a00}.grade-F{color:#c02525;font-weight:600}
"""


def grade_class(grade):
    return "grade-" + (grade[0] if grade else "F")


def page(title, body):
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{PAGE_CSS}</style></head>"
        f"<body>{body}</body></html>"
    ).encode()


def home_page():
    total = len(STUDENTS)
    avg_gpa = round(sum(s["gpa"] for s in STUDENTS) / total, 2) if total else 0
    sample = "".join(
        f"<tr><td><a href='/student?id={s['student_id']}'>{s['student_id']}</a></td>"
        f"<td>{html.escape(s['name'])}</td><td>{html.escape(s['program'])}</td>"
        f"<td>{s['gpa']}</td></tr>"
        for s in STUDENTS[:15]
    )
    body = f"""
    <h1>University Examination Results Portal</h1>
    <p class='sub'>Semester results look-up &nbsp;·&nbsp; (lab victim service)</p>
    <div class='card'>
      <form action='/student' method='get'>
        <label>Look up a student by ID:
          <input name='id' placeholder='e.g. S0001' required>
        </label>
        <button type='submit'>View results</button>
      </form>
    </div>
    <div class='card'>
      <span class='pill'>{total} students</span>
      <span class='pill'>average GPA {avg_gpa}</span>
      <span class='pill'>uptime {time.time() - START:.0f}s</span>
      <span class='pill'>requests served {HITS}</span>
    </div>
    <h2>Recent students</h2>
    <table><tr><th>ID</th><th>Name</th><th>Program</th><th>GPA</th></tr>{sample}</table>
    <p class='sub'>API: <a href='/api/results'>/api/results</a> · health:
      <a href='/healthz'>/healthz</a></p>
    """
    return page("Exam Results Portal", body)


def student_page(sid):
    s = BY_ID.get(sid)
    if not s:
        return None
    rows = "".join(
        f"<tr><td>{html.escape(r['code'])}</td><td>{html.escape(r['subject'])}</td>"
        f"<td>{r['marks']}</td><td class='{grade_class(r['grade'])}'>{r['grade']}</td></tr>"
        for r in s["results"]
    )
    body = f"""
    <p><a href='/'>&larr; back to portal</a></p>
    <h1>{html.escape(s['name'])}</h1>
    <p class='sub'>{html.escape(s['student_id'])} &nbsp;·&nbsp;
       {html.escape(s['index_no'])} &nbsp;·&nbsp; {html.escape(s['program'])}
       &nbsp;·&nbsp; Year {s['year']}</p>
    <div class='card'><strong>GPA: {s['gpa']}</strong></div>
    <table><tr><th>Code</th><th>Subject</th><th>Marks</th><th>Grade</th></tr>{rows}</table>
    <p class='sub'>JSON: <a href='/api/results?id={s['student_id']}'>
       /api/results?id={s['student_id']}</a></p>
    """
    return page(f"Results - {s['name']}", body)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 (http.server API name)
        global HITS
        HITS += 1
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        sid = (qs.get("id") or [None])[0]

        if path == "/":
            self._send(200, home_page())

        elif path == "/student":
            body = student_page(sid) if sid else None
            if body is None:
                self._send(404, page("Not found",
                           f"<h1>Student not found</h1>"
                           f"<p>No record for id "
                           f"'{html.escape(sid or '')}'. "
                           f"<a href='/'>Back</a></p>"))
            else:
                self._send(200, body)

        elif path == "/api/results":
            if sid:
                s = BY_ID.get(sid)
                if not s:
                    self._send(404, json.dumps({"error": "not found", "id": sid})
                               .encode(), "application/json")
                else:
                    self._send(200, json.dumps(s).encode(), "application/json")
            else:
                self._send(200, json.dumps(STUDENTS).encode(), "application/json")

        elif path == "/healthz":
            body = (f"OK - exam portal alive\nuptime: {time.time() - START:.0f}s\n"
                    f"students: {len(STUDENTS)}\nrequests served: {HITS}\n").encode()
            self._send(200, body, "text/plain; charset=utf-8")

        else:
            self._send(404, page("Not found",
                       "<h1>404</h1><p><a href='/'>Back to portal</a></p>"))

    def log_message(self, fmt, *args):
        # Stay quiet under flood load; comment out to log every hit.
        pass


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"Exam Results Portal on http://{host}:{port}/  "
          f"({len(STUDENTS)} students loaded)  (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print(f"\nServed {HITS} requests. Bye.")


if __name__ == "__main__":
    main()
