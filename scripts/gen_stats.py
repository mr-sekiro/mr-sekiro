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
    W, H = 1000, 430
    p = []
    A = p.append
    A(f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" fill="none" xmlns="http://www.w3.org/2000/svg">')
    A(f'''<defs>
    <linearGradient id="stPanel" x1="0" y1="0" x2="{W}" y2="{H}" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#0b0e14"/><stop offset="0.5" stop-color="#0e1219"/><stop offset="1" stop-color="#0b0e14"/>
    </linearGradient>
    <radialGradient id="stFlameGlow" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#e8963f" stop-opacity="0.45"/><stop offset="1" stop-color="#e0632f" stop-opacity="0"/>
    </radialGradient>
  </defs>''')
    A('''<style>
    .tile { transform-box: fill-box; transform-origin: center; transform: scale(0.85); opacity: 0; animation: tIn 0.6s cubic-bezier(0.34,1.56,0.64,1) forwards; }
    @keyframes tIn { to { transform: scale(1); opacity: 1; } }
    .seg { transform-box: fill-box; transform-origin: left center; transform: scaleX(0); animation: sIn 1s cubic-bezier(0.22,1,0.36,1) forwards; }
    @keyframes sIn { to { transform: scaleX(1); } }
    .fade { opacity: 0; animation: fIn 0.8s ease-out forwards; }
    @keyframes fIn { to { opacity: 1; } }
    .flameO { transform-box: fill-box; transform-origin: center bottom; animation: flick 1.2s ease-in-out infinite alternate; }
    .flameI { transform-box: fill-box; transform-origin: center bottom; animation: flick 0.85s ease-in-out 0.2s infinite alternate-reverse; }
    @keyframes flick { from { transform: scaleY(1) rotate(-2deg); } to { transform: scaleY(1.18) scaleX(0.93) rotate(2deg); } }
    .glow { transform-box: fill-box; transform-origin: center; animation: gp 3s ease-in-out infinite; }
    @keyframes gp { 0%,100% { transform: scale(1); opacity: 0.8; } 50% { transform: scale(1.25); opacity: 1; } }
    .db { transform-box: fill-box; transform-origin: center; animation: dbp 2.4s ease-in-out infinite; }
    @keyframes dbp { 0%,100% { transform: scale(1); opacity: 0.8; } 50% { transform: scale(1.3); opacity: 1; } }
    .big { animation: fIn 1s ease-out 0.9s both; }
  </style>''')
    A(f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="14" fill="url(#stPanel)" stroke="#21262d"/>')
    A(f'<text x="{W-12}" y="{H-14}" text-anchor="end" font-family="{SERIF_J}" font-size="150" font-weight="700" fill="#e63946" opacity="0.03">数</text>')

    tiles = [
        ("COMMITS · ALL TIME", fmt(s["commits"])),
        ("STARS EARNED", fmt(s["stars"])),
        ("PULL REQUESTS", fmt(s["prs"])),
        ("ISSUES FILED", fmt(s["issues"])),
        ("FOLLOWERS", fmt(s["followers"])),
        ("CONTRIBUTED TO", fmt(s["contributed"])),
    ]
    tw, th, gx, gy, x0, y0 = 184, 74, 14, 16, 56, 46
    for i, (label, val) in enumerate(tiles):
        cx = x0 + (i % 3) * (tw + gx)
        cy = y0 + (i // 3) * (th + gy)
        d = 0.15 + i * 0.1
        A(f'<g class="tile" style="animation-delay:{d:.2f}s">')
        A(f'<rect x="{cx}" y="{cy}" width="{tw}" height="{th}" rx="4" fill="#10141c" stroke="#6d5a3a" stroke-width="1.5"/>')
        A(f'<rect x="{cx+4}" y="{cy+4}" width="{tw-8}" height="{th-8}" rx="2" fill="none" stroke="#a08858" stroke-width="0.8" opacity="0.35"/>')
        A(f'<rect x="{cx+tw-13}" y="{cy+7}" width="6" height="6" fill="none" stroke="#a08858" stroke-width="1.4" transform="rotate(45 {cx+tw-10} {cy+10})"/>')
        A(f'<text x="{cx+16}" y="{cy+34}" font-family="{SANS}" font-size="24" font-weight="700" fill="#f1f5f9">{val}</text>')
        A(f'<text x="{cx+16}" y="{cy+56}" font-family="{MONO}" font-size="10" letter-spacing="2.5" fill="#a08858">{label}</text>')
        A('</g>')

    # streak shrine
    sx, sy, sw, sh = 668, 46, 276, 164
    A(f'<g class="tile" style="animation-delay:0.75s">')
    A(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="4" fill="#10141c" stroke="#6d5a3a" stroke-width="1.5"/>')
    A(f'<rect x="{sx+5}" y="{sy+5}" width="{sw-10}" height="{sh-10}" rx="2" fill="none" stroke="#a08858" stroke-width="0.8" opacity="0.35"/>')
    fx, fy = sx + sw / 2, sy + 34
    A(f'<circle class="glow" cx="{fx}" cy="{fy}" r="22" fill="url(#stFlameGlow)"/>')
    A(f'<path class="flameO" d="M{fx} {fy-16} C{fx+7} {fy-8} {fx+9} {fy} {fx+6} {fy+8} C{fx+4} {fy+13} {fx+1} {fy+16} {fx} {fy+16} C{fx-1} {fy+16} {fx-4} {fy+13} {fx-6} {fy+8} C{fx-9} {fy} {fx-7} {fy-8} {fx} {fy-16}" fill="#e8963f" opacity="0.75"/>')
    A(f'<path class="flameI" d="M{fx} {fy-7} C{fx+4} {fy-2} {fx+5} {fy+4} {fx+3} {fy+10} C{fx+2} {fy+13} {fx} {fy+14} {fx} {fy+14} C{fx} {fy+14} {fx-2} {fy+13} {fx-3} {fy+10} C{fx-5} {fy+4} {fx-4} {fy-2} {fx} {fy-7}" fill="#ffe9c2"/>')
    A(f'<text x="{fx}" y="{sy+76}" text-anchor="middle" font-family="{MONO}" font-size="11" letter-spacing="3" fill="#a08858">CURRENT STREAK</text>')
    A(f'<text class="big" x="{fx}" y="{sy+118}" text-anchor="middle" font-family="{SANS}" font-size="40" font-weight="800" fill="#e63946">{s["cur_streak"]}<tspan font-size="15" font-weight="600" fill="#c9d1d9">&#160;DAYS</tspan></text>')
    A(f'<text x="{fx}" y="{sy+146}" text-anchor="middle" font-family="{MONO}" font-size="11" letter-spacing="2" fill="#e0a458">LONGEST&#160;&#160;·&#160;&#160;{s["longest_streak"]} DAYS</text>')
    A('</g>')

    # languages vitality bar
    ly = 258
    A(f'<g class="fade" style="animation-delay:0.9s">')
    A(f'<text x="56" y="{ly}" font-family="{MONO}" font-size="12" letter-spacing="3" fill="#a08858">TOP LANGUAGES&#160;&#160;<tspan font-family="{SERIF_J}" fill="#e63946" opacity="0.8">言語</tspan></text>')
    A(f'<text x="944" y="{ly}" text-anchor="end" font-family="{MONO}" font-size="10" letter-spacing="2" fill="#8b949e" opacity="0.6">BY CODE VOLUME</text>')
    A('</g>')
    bx, bw, bh, by = 56, 888, 14, ly + 14
    A(f'<rect x="{bx-2}" y="{by-2}" width="{bw+4}" height="{bh+4}" rx="3" fill="#150b0c" stroke="#6d5a3a" stroke-width="1.5"/>')
    cx = bx
    for i, (name, pct) in enumerate(s["langs"]):
        wseg = max(3.0, bw * pct)
        color = LANG_COLORS[i % len(LANG_COLORS)]
        A(f'<rect class="seg" style="animation-delay:{1.0 + i*0.15:.2f}s" x="{cx:.1f}" y="{by}" width="{wseg:.1f}" height="{bh}" fill="{color}"/>')
        cx += wseg
    lx = 56
    lyy = by + 42
    for i, (name, pct) in enumerate(s["langs"]):
        color = LANG_COLORS[i % len(LANG_COLORS)]
        label = f"{name}&#160;{pct*100:.1f}%"
        A(f'<g class="fade" style="animation-delay:{1.3 + i*0.12:.2f}s">')
        A(f'<rect x="{lx}" y="{lyy-9}" width="9" height="9" fill="{color}"/>')
        A(f'<text x="{lx+16}" y="{lyy}" font-family="{SANS}" font-size="12.5" fill="#c9d1d9">{label}</text>')
        A('</g>')
        lx += 26 + 8 * (len(name) + 6)

    # total contributions strip
    ty = 384
    A(f'<line x1="56" y1="{ty-24}" x2="944" y2="{ty-24}" stroke="#21262d" stroke-width="1"/>')
    A(f'<g class="fade" style="animation-delay:1.6s">')
    A(f'<text x="500" y="{ty+6}" text-anchor="middle" font-family="{MONO}" font-size="12" letter-spacing="3" fill="#a08858">総貢献&#160;&#160;TOTAL CONTRIBUTIONS&#160;&#160;<tspan font-family="{SANS}" font-size="26" font-weight="800" fill="#e0a458">&#160;{fmt(s["total_contrib"])}&#160;</tspan>&#160;&#160;SINCE {s["since"]}</text>')
    A('</g>')

    A(f'<circle class="db" cx="62" cy="{H-20}" r="4" fill="#ff4653"/>')
    A(f'<text class="fade" style="animation-delay:1.8s" x="944" y="{H-16}" text-anchor="end" font-family="{MONO}" font-size="10" letter-spacing="2" fill="#a08858" opacity="0.45">LAST SYNC · {s["sync"]}</text>')
    A('</svg>')
    return "\n".join(p)


if __name__ == "__main__":
    stats = fetch()
    svg = render(stats)
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(svg)
    print(f"wrote {OUT}: {json.dumps({k: v for k, v in stats.items() if k != 'langs'})}")
