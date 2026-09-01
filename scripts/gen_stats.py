#!/usr/bin/env python3
"""Generate the Sekiro-themed statistics panel (assets/stats.svg) from live GitHub data.

Usage: GITHUB_TOKEN=... python3 scripts/gen_stats.py <login> <out.svg>
Stdlib only, so it runs bare on GitHub Actions runners.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

LOGIN = sys.argv[1] if len(sys.argv) > 1 else "mr-sekiro"
OUT = sys.argv[2] if len(sys.argv) > 2 else "assets/stats.svg"
TOKEN = os.environ["GITHUB_TOKEN"]

SANS = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"
MONO = "'Cascadia Code', Consolas, 'Courier New', monospace"
SERIF_J = "'Yu Mincho', 'Hiragino Mincho ProN', 'Noto Serif CJK JP', serif"

LANG_COLORS = ["#e63946", "#b3242c", "#e0a458", "#a08858", "#8b949e", "#5c6570"]


def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json",
                 "User-Agent": "mr-sekiro-profile"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.loads(r.read())
    if "errors" in out:
        raise RuntimeError(out["errors"])
    return out["data"]


def rest_count(q):
    req = urllib.request.Request(
        "https://api.github.com/search/issues?per_page=1&q=" + urllib.parse.quote(q),
        headers={"Authorization": f"bearer {TOKEN}", "Accept": "application/vnd.github+json",
                 "User-Agent": "mr-sekiro-profile"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()).get("total_count", 0)
    except Exception:
        return 0


def fetch():
    created = gql("query($l:String!){user(login:$l){createdAt}}", {"l": LOGIN})["user"]["createdAt"]
    first_year = int(created[:4])
    now = datetime.now(timezone.utc)

    year_aliases = []
    for y in range(first_year, now.year + 1):
        frm = f"{y}-01-01T00:00:00Z"
        to = f"{y + 1}-01-01T00:00:00Z" if y < now.year else now.strftime("%Y-%m-%dT%H:%M:%SZ")
        year_aliases.append(
            f'y{y}: contributionsCollection(from: "{frm}", to: "{to}") {{'
            "totalCommitContributions restrictedContributionsCount totalPullRequestContributions totalIssueContributions "
            "contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } } }"
        )
    q = f"""
    query($l:String!) {{
      user(login:$l) {{
        followers {{ totalCount }}
        contributionsCollection {{
          totalPullRequestContributions
          totalIssueContributions
          totalRepositoriesWithContributedCommits
        }}
        repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC) {{
          nodes {{
            stargazerCount
            languages(first: 10, orderBy: {{field: SIZE, direction: DESC}}) {{
              edges {{ size node {{ name }} }}
            }}
          }}
        }}
        {' '.join(year_aliases)}
      }}
    }}"""
    u = gql(q, {"l": LOGIN})["user"]

    commits = 0
    prs = 0
    issues = 0
    total_contrib = 0
    days = {}
    first_active = None
    for y in range(first_year, now.year + 1):
        c = u[f"y{y}"]
        commits += c["totalCommitContributions"] + c["restrictedContributionsCount"]
        prs += c["totalPullRequestContributions"]
        issues += c["totalIssueContributions"]
        total_contrib += c["contributionCalendar"]["totalContributions"]
        for wk in c["contributionCalendar"]["weeks"]:
            for d in wk["contributionDays"]:
                days[d["date"]] = days.get(d["date"], 0) + d["contributionCount"]
                if d["contributionCount"] > 0 and first_active is None:
                    first_active = d["date"]

    # streaks
    today = now.date()
    cur = 0
    probe = today
    if days.get(probe.isoformat(), 0) == 0:
        probe = probe - timedelta(days=1)
    while days.get(probe.isoformat(), 0) > 0:
        cur += 1
        probe = probe - timedelta(days=1)
    longest, run = 0, 0
    d0 = date.fromisoformat(min(days)) if days else today
    d = d0
    while d <= today:
        if days.get(d.isoformat(), 0) > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
        d += timedelta(days=1)

    stars = sum(n["stargazerCount"] for n in u["repositories"]["nodes"])
    langs = {}
    for n in u["repositories"]["nodes"]:
        for e in n["languages"]["edges"]:
            langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]
    total_size = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1])[:5]
    lang_rows = [(name, size / total_size) for name, size in top]
    other = 1.0 - sum(p for _, p in lang_rows)
    if other > 0.004:
        lang_rows.append(("Other", other))

    prs = max(prs, rest_count(f"author:{LOGIN} type:pr"))
    issues = max(issues, rest_count(f"author:{LOGIN} type:issue"))

    since = datetime.strptime(first_active, "%Y-%m-%d").strftime("%b %Y").upper() if first_active else "-"
    cc = u["contributionsCollection"]
    return {
        "commits": commits,
        "stars": stars,
        "prs": prs,
        "issues": issues,
        "followers": u["followers"]["totalCount"],
        "contributed": cc["totalRepositoriesWithContributedCommits"],
        "cur_streak": cur,
        "longest_streak": longest,
        "total_contrib": total_contrib,
        "since": since,
        "langs": lang_rows,
        "sync": now.strftime("%Y-%m-%d %H:%M UTC"),
    }


def fmt(n):
    return f"{n:,}"


def render(s):
    W, H = 1000, 470
    p = []
    A = p.append
    A(f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" fill="none" xmlns="http://www.w3.org/2000/svg">')
    A(f"""<defs>
    <linearGradient id="stPanel" x1="0" y1="0" x2="0" y2="{H}" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#0b0e14"/><stop offset="0.6" stop-color="#0e1219"/><stop offset="1" stop-color="#0b0e14"/>
    </linearGradient>
    <linearGradient id="numGrad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#e63946"/><stop offset="1" stop-color="#e0a458"/>
    </linearGradient>
    <radialGradient id="stFlameGlow" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#e8963f" stop-opacity="0.5"/><stop offset="1" stop-color="#e0632f" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="beadGrad" cx="0.5" cy="0.38" r="0.75">
      <stop offset="0" stop-color="#181f2b"/><stop offset="1" stop-color="#0d1117"/>
    </radialGradient>
    <linearGradient id="coinGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#e8c983"/><stop offset="1" stop-color="#b9954e"/>
    </linearGradient>
    <linearGradient id="vRule" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#30363d" stop-opacity="0"/><stop offset="0.5" stop-color="#30363d"/><stop offset="1" stop-color="#30363d" stop-opacity="0"/>
    </linearGradient>
    <filter id="stMist" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="14"/></filter>
    <clipPath id="stFrame"><rect width="{W}" height="{H}" rx="14"/></clipPath>
  </defs>""")
    A("""<style>
    .cord { stroke-dasharray: 1100; stroke-dashoffset: 1100; animation: cordDraw 1.6s cubic-bezier(0.4,0,0.2,1) 0.2s forwards; }
    @keyframes cordDraw { to { stroke-dashoffset: 0; } }
    .bead { transform-box: fill-box; transform-origin: center; transform: scale(0); animation: bIn 0.55s cubic-bezier(0.34,1.56,0.64,1) forwards; }
    @keyframes bIn { to { transform: scale(1); } }
    .fade { opacity: 0; animation: fIn 0.8s ease-out forwards; }
    @keyframes fIn { to { opacity: 1; } }
    .seg { transform-box: fill-box; transform-origin: left center; transform: scaleX(0); animation: sIn 1s cubic-bezier(0.22,1,0.36,1) forwards; }
    @keyframes sIn { to { transform: scaleX(1); } }
    .flameO { transform-box: fill-box; transform-origin: center bottom; animation: flick 1.2s ease-in-out infinite alternate; }
    .flameM { transform-box: fill-box; transform-origin: center bottom; animation: flick 0.9s ease-in-out 0.22s infinite alternate-reverse; }
    .flameI { transform-box: fill-box; transform-origin: center bottom; animation: flick 0.7s ease-in-out 0.1s infinite alternate; }
    @keyframes flick { from { transform: scaleY(1) rotate(-2deg); } to { transform: scaleY(1.15) scaleX(0.94) rotate(2deg); } }
    .glow { transform-box: fill-box; transform-origin: center; animation: gp 3s ease-in-out infinite; }
    @keyframes gp { 0%,100% { transform: scale(1); opacity: 0.8; } 50% { transform: scale(1.25); opacity: 1; } }
    .db { transform-box: fill-box; transform-origin: center; animation: dbp 2.4s ease-in-out infinite; }
    @keyframes dbp { 0%,100% { transform: scale(1); opacity: 0.8; } 50% { transform: scale(1.3); opacity: 1; } }
    .mist1 { animation: drift 28s ease-in-out infinite alternate; }
    .mist2 { animation: drift 36s ease-in-out infinite alternate-reverse; }
    @keyframes drift { from { transform: translateX(-45px); } to { transform: translateX(60px); } }
    .ember { animation: rise ease-in infinite; opacity: 0; }
    @keyframes rise { 0% { transform: translateY(0); opacity: 0; } 12% { opacity: 0.85; } 100% { transform: translateY(-110px); opacity: 0; } }
    .em1 { animation-duration: 6s; } .em2 { animation-duration: 7.5s; animation-delay: 2.4s; }
    .em3 { animation-duration: 5.5s; animation-delay: 4s; } .em4 { animation-duration: 8s; animation-delay: 1.2s; }
    .coin { transform-box: fill-box; transform-origin: center; animation: coinIn 0.7s cubic-bezier(0.34,1.56,0.64,1) 1.5s both, coinSpin 9s linear 2.5s infinite; }
    @keyframes coinIn { from { transform: scale(0) rotate(-120deg); opacity: 0; } to { transform: scale(1) rotate(0deg); opacity: 1; } }
    @keyframes coinSpin { 0%,82% { transform: rotate(0deg); } 92% { transform: rotate(180deg); } 100% { transform: rotate(360deg); } }
  </style>""")
    A('<g clip-path="url(#stFrame)">')
    A(f'<rect width="{W}" height="{H}" fill="url(#stPanel)"/>')
    A(f'<path d="M0 430 L140 400 L300 424 L500 396 L690 422 L850 402 L1000 420 L1000 {H} L0 {H} Z" fill="#0d1119"/>')
    A('<g class="mist1" filter="url(#stMist)"><ellipse cx="280" cy="420" rx="220" ry="20" fill="#8b949e" opacity="0.05"/></g>')
    A('<g class="mist2" filter="url(#stMist)"><ellipse cx="720" cy="440" rx="240" ry="22" fill="#8b949e" opacity="0.04"/></g>')
    A(f'<text x="{W-14}" y="120" text-anchor="end" font-family="{SERIF_J}" font-size="140" font-weight="700" fill="#e63946" opacity="0.035">数</text>')

    for cls, x, y, col in [("em1", 150, 452, "#e63946"), ("em2", 420, 458, "#e0a458"),
                           ("em3", 640, 455, "#e63946"), ("em4", 880, 452, "#e0a458")]:
        A(f'<g transform="translate({x},{y})"><circle class="ember {cls}" r="1.7" fill="{col}"/></g>')

    beads = [
        (fmt(s["commits"]), "COMMITS"),
        (fmt(s["stars"]), "STARS"),
        (fmt(s["prs"]), "PULL REQUESTS"),
        (fmt(s["issues"]), "ISSUES"),
        (fmt(s["followers"]), "FOLLOWERS"),
        (fmt(s["contributed"]), "CONTRIBUTED TO"),
    ]
    xs = [110, 266, 422, 578, 734, 890]
    dy = [0, 16, 25, 25, 16, 0]
    ys = [72 + d for d in dy]
    cord = f"M20 52 C 60 56, 85 {ys[0]-4} {xs[0]} {ys[0]}"
    for i in range(1, 6):
        mx = (xs[i-1] + xs[i]) / 2
        my = max(ys[i-1], ys[i]) + 12
        cord += f" Q {mx} {my} {xs[i]} {ys[i]}"
    cord += f" C 915 {ys[5]-4}, 940 56, 980 52"
    A(f'<path class="cord" d="{cord}" stroke="#6d5a3a" stroke-width="2" fill="none" opacity="0.8"/>')
    for i, ((val, label), x, y) in enumerate(zip(beads, xs, ys)):
        d = 0.35 + i * 0.13
        A(f'<g class="bead" style="animation-delay:{d:.2f}s">')
        A(f'<circle cx="{x}" cy="{y}" r="36" fill="url(#beadGrad)" stroke="#6d5a3a" stroke-width="2.5"/>')
        A(f'<circle cx="{x}" cy="{y}" r="29" fill="none" stroke="#a08858" stroke-width="1" opacity="0.4"/>')
        A(f'<rect x="{x-4}" y="{y-42}" width="8" height="8" fill="#10141c" stroke="#a08858" stroke-width="1.6" transform="rotate(45 {x} {y-38})"/>')
        fs = 19 if len(val) < 5 else 16.5
        A(f'<text x="{x}" y="{y+7}" text-anchor="middle" font-family="{SANS}" font-size="{fs}" font-weight="800" fill="#f1f5f9">{val}</text>')
        A('</g>')
        A(f'<g class="fade" style="animation-delay:{d+0.15:.2f}s">')
        A(f'<text x="{x}" y="{y+62}" text-anchor="middle" font-family="{MONO}" font-size="10" letter-spacing="2.5" fill="#a08858">{label}</text>')
        A('</g>')

    fy = 250
    A(f'<rect x="499" y="{fy-46}" width="1.5" height="108" fill="url(#vRule)"/>')

    fx = 218
    A(f'<circle class="glow" cx="{fx}" cy="{fy-8}" r="30" fill="url(#stFlameGlow)"/>')
    A(f'<path class="flameO" d="M{fx} {fy-32} C{fx+9} {fy-21} {fx+12} {fy-11} {fx+8} {fy-1} C{fx+5} {fy+6} {fx+2} {fy+10} {fx} {fy+10} C{fx-2} {fy+10} {fx-5} {fy+6} {fx-8} {fy-1} C{fx-12} {fy-11} {fx-9} {fy-21} {fx} {fy-32}" fill="#e8963f" opacity="0.65"/>')
    A(f'<path class="flameM" d="M{fx} {fy-22} C{fx+6} {fy-14} {fx+7} {fy-6} {fx+4} {fy+2} C{fx+2} {fy+7} {fx} {fy+9} {fx} {fy+9} C{fx} {fy+9} {fx-2} {fy+7} {fx-4} {fy+2} C{fx-7} {fy-6} {fx-6} {fy-14} {fx} {fy-22}" fill="#e0632f"/>')
    A(f'<path class="flameI" d="M{fx} {fy-12} C{fx+3} {fy-7} {fx+4} {fy-1} {fx+2} {fy+4} C{fx+1} {fy+7} {fx} {fy+8} {fx} {fy+8} C{fx} {fy+8} {fx-1} {fy+7} {fx-2} {fy+4} C{fx-4} {fy-1} {fx-3} {fy-7} {fx} {fy-12}" fill="#ffe9c2"/>')
    A('<g class="fade" style="animation-delay:1.2s">')
    A(f'<text x="{fx+42}" y="{fy-2}" font-family="{SANS}" font-size="44" font-weight="800" fill="url(#numGrad)">{s["cur_streak"]}<tspan font-size="15" font-weight="600" fill="#c9d1d9" dx="8">DAY STREAK</tspan></text>')
    A(f'<text x="{fx+44}" y="{fy+28}" font-family="{MONO}" font-size="11.5" letter-spacing="2" fill="#e0a458">LONGEST&#160;&#160;·&#160;&#160;{s["longest_streak"]} DAYS</text>')
    A('</g>')
    A(f'<g class="fade" style="animation-delay:1.35s"><text x="{fx-36}" y="{fy+28}" font-family="{MONO}" font-size="10" letter-spacing="2.5" fill="#a08858">回生</text></g>')

    cx0 = 590
    A('<g class="coin">')
    A(f'<circle cx="{cx0}" cy="{fy-6}" r="26" fill="url(#coinGrad)"/>')
    A(f'<circle cx="{cx0}" cy="{fy-6}" r="26" fill="none" stroke="#8a7040" stroke-width="2"/>')
    A(f'<circle cx="{cx0}" cy="{fy-6}" r="21" fill="none" stroke="#8a7040" stroke-width="0.8" opacity="0.6"/>')
    A(f'<rect x="{cx0-7}" y="{fy-13}" width="14" height="14" fill="#0e1219"/>')
    A('</g>')
    A('<g class="fade" style="animation-delay:1.5s">')
    A(f'<text x="{cx0+44}" y="{fy-2}" font-family="{SANS}" font-size="40" font-weight="800" fill="#e0a458">{fmt(s["total_contrib"])}<tspan font-size="14" font-weight="600" fill="#c9d1d9" dx="8">CONTRIBUTIONS</tspan></text>')
    A(f'<text x="{cx0+46}" y="{fy+28}" font-family="{MONO}" font-size="11.5" letter-spacing="2" fill="#8b949e">SINCE {s["since"]}&#160;&#160;·&#160;&#160;総貢献</text>')
    A('</g>')

    ly = 352
    A('<g class="fade" style="animation-delay:1.1s">')
    A(f'<text x="56" y="{ly}" font-family="{MONO}" font-size="12" letter-spacing="3" fill="#a08858">TOP LANGUAGES&#160;&#160;<tspan font-family="{SERIF_J}" fill="#e63946" opacity="0.8">言語</tspan></text>')
    A(f'<text x="944" y="{ly}" text-anchor="end" font-family="{MONO}" font-size="10" letter-spacing="2" fill="#8b949e" opacity="0.6">BY CODE VOLUME</text>')
    A('</g>')
    bx, bw, bh, by = 56, 888, 15, ly + 14
    A(f'<rect x="{bx-3}" y="{by-3}" width="{bw+6}" height="{bh+6}" rx="3" fill="#150b0c" stroke="#6d5a3a" stroke-width="1.5"/>')
    cx = bx
    for i, (name, pct) in enumerate(s["langs"]):
        wseg = max(3.0, bw * pct)
        color = LANG_COLORS[i % len(LANG_COLORS)]
        A(f'<rect class="seg" style="animation-delay:{1.2 + i*0.15:.2f}s" x="{cx:.1f}" y="{by}" width="{wseg:.1f}" height="{bh}" fill="{color}"/>')
        cx += wseg
    A(f'<rect x="{bx}" y="{by}" width="{bw}" height="4" fill="#ffffff" opacity="0.08"/>')
    A(f'<rect x="{bx-8}" y="{by+bh/2-4}" width="8" height="8" fill="none" stroke="#a08858" stroke-width="1.6" transform="rotate(45 {bx-4} {by+bh/2})"/>')
    A(f'<rect x="{bx+bw}" y="{by+bh/2-4}" width="8" height="8" fill="none" stroke="#a08858" stroke-width="1.6" transform="rotate(45 {bx+bw+4} {by+bh/2})"/>')
    lx = 56
    lyy = by + 44
    for i, (name, pct) in enumerate(s["langs"]):
        color = LANG_COLORS[i % len(LANG_COLORS)]
        label = f"{name}&#160;{pct*100:.1f}%"
        A(f'<g class="fade" style="animation-delay:{1.5 + i*0.12:.2f}s">')
        A(f'<rect x="{lx}" y="{lyy-9}" width="9" height="9" fill="{color}"/>')
        A(f'<text x="{lx+16}" y="{lyy}" font-family="{SANS}" font-size="12.5" fill="#c9d1d9">{label}</text>')
        A('</g>')
        lx += 26 + 8 * (len(name) + 6)

    A(f'<circle class="db" cx="62" cy="{H-22}" r="4" fill="#ff4653"/>')
    A(f'<text class="fade" style="animation-delay:1.9s" x="944" y="{H-18}" text-anchor="end" font-family="{MONO}" font-size="10" letter-spacing="2" fill="#a08858" opacity="0.5">LAST SYNC · {s["sync"]}</text>')
    A('</g>')
    A(f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="14" stroke="#21262d"/>')
    A('</svg>')
    return "\n".join(p)


if __name__ == "__main__":
    stats = fetch()
    svg = render(stats)
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(svg)
    print(f"wrote {OUT}: {json.dumps({k: v for k, v in stats.items() if k != 'langs'})}")
