import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import requests
import json
import os
from urllib.parse import quote
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="The Clubhouse Pool", layout="wide", page_icon="⛳")
st_autorefresh(interval=300000, key="refresh")

# ============================================================
# LINK-PREVIEW META TAGS (iMessage / SMS / Slack / WhatsApp / X)
# ------------------------------------------------------------
# Streamlit doesn't let us touch <head> natively, so we inject Open Graph
# and Twitter Card tags from an iframe into window.parent.document.head.
# Most preview scrapers that hit *.streamlit.app won't execute JS, so the
# *primary* way the preview updates for end users is by sharing the new
# clubhousepool.golf URL (iMessage caches previews aggressively per-URL).
# Still, some scrapers (Slack, Twitter partial, in-app previews) do run JS
# or honor these dynamic tags, so it's worth the belt-and-suspenders.
# ============================================================
components.html("""
<script>
(function(){
  try {
    var d = window.parent.document;
    function upsert(attr, key, val, tag){
      tag = tag || 'meta';
      var sel = tag + '[' + attr + '="' + key + '"]';
      var el = d.querySelector(sel);
      if (!el) {
        el = d.createElement(tag);
        el.setAttribute(attr, key);
        d.head.appendChild(el);
      }
      el.setAttribute('content', val);
    }
    // Hard-set the browser tab title too (belt-and-suspenders)
    d.title = "The Clubhouse Pool";

    var TITLE = "The Clubhouse Pool";
    var DESC  = "Weekly golf pool — $10 to enter. Pick 3 golfers, lowest combined score wins. Join your friends.";
    var URL   = "https://clubhousepool.golf";
    var IMG   = "https://clubhousepool.golf/~/+/media/logo-share.png"; // placeholder, fine if 404

    // Open Graph (iMessage, WhatsApp, Slack, LinkedIn, Facebook)
    upsert('property', 'og:title',       TITLE);
    upsert('property', 'og:description', DESC);
    upsert('property', 'og:url',         URL);
    upsert('property', 'og:type',        'website');
    upsert('property', 'og:site_name',   'The Clubhouse Pool');
    upsert('property', 'og:image',       IMG);

    // Twitter / X
    upsert('name', 'twitter:card',        'summary');
    upsert('name', 'twitter:title',       TITLE);
    upsert('name', 'twitter:description', DESC);
    upsert('name', 'twitter:image',       IMG);

    // Standard description + apple-mobile-web-app-title (affects iOS home-screen)
    upsert('name', 'description', DESC);
    upsert('name', 'apple-mobile-web-app-title', TITLE);
    upsert('name', 'application-name', TITLE);
  } catch(e) {}
})();
</script>
""", height=0)

# ============================================================
# CONFIG
# ============================================================
TOURNAMENT_ID = "401811944"
ENTRY_FEE     = 10
DAILY_PCT     = 0.15
OVERALL_PCT   = 0.40

# Public URL shared by the "Invite a Friend" button.
# Now that Cloudflare is pointing clubhousepool.golf at the Streamlit app,
# this is the friendlier URL to share in text messages.
APP_URL = "https://clubhousepool.golf"

SHEET_URL = "https://docs.google.com/spreadsheets/d/1hH--Z2Ur1yN8p1R5uftC_nDF6TQz5T7Z5WJWKO6K07c/export?format=csv"

# ── Admin password (move to env var before pushing to GitHub) ──
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "fairways2026")

# ── Saved next to this script so settings survive restarts ──
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin_state.json")

# ============================================================
# ENTRY FLOW CONFIG  ← FILL THESE IN
# ============================================================
# Your Venmo handle (no @)
VENMO_HANDLE = "caden2323"

# Google Form submit endpoint
FORM_SUBMIT_URL = "https://docs.google.com/forms/d/e/1FAIpQLSeBkLpZ0lPOl29jP2BrEEU1NKC4fcv0JZ3qDjeMpwpW5kGS-g/formResponse"

# Entry IDs from your Google Form
FORM_FIELD_IDS = {
    "name":  "entry.1409538491",
    "email": "entry.655700445",
    "venmo": "entry.753893729",
    "pick1": "entry.1348718021",
    "pick2": "entry.1331079764",
    "pick3": "entry.430664969",
}

# Tier lists — update each tournament with that week's field
# Must match the options in your Google Form dropdowns EXACTLY
TIER_1 = [
    "Scottie Scheffler",
    "Cameron Young",
    "Collin Morikawa",
    "Tommy Fleetwood",
    "Russell Henley",
    "Si Woo Kim",
    "Sam Burns",
    "Chris Gotterup",
    "Patrick Cantlay",
    "Adam Scott",
    "Justin Rose",
    "Maverick McNealy",
    "Viktor Hovland",
    "Hideki Matsuyama",
    "Min Woo Lee",
    "Harris English",
]
TIER_2 = [
    "Jake Knapp",
    "Rickie Fowler",
    "Jordan Spieth",
    "Akshay Bhatia",
    "Ben Griffin",
    "Jason Day",
    "Jacob Bridgeman",
    "Shane Lowry",
    "Kurt Kitayama",
    "J.J. Spaun",
    "Nicolai Højgaard",
    "Sepp Straka",
    "Keegan Bradley",
    "Gary Woodland",
    "Justin Thomas",
    "Keith Mitchell",
    "Harry Hall",
]
TIER_3 = [
    "Sahith Theegala",
    "Samuel Stevens",
    "Alex Noren",
    "Ryan Gerard",
    "Pierceson Coody",
    "Ricky Castillo",
    "Corey Conners",
    "Nick Taylor",
    "Bud Cauley",
    "Alex Smalley",
    "Ryo Hisatsune",
    "Jordan Smith",
    "Ryan Fox",
    "Matt McCarty",
    "Daniel Berger",
    "Taylor Pendrith",
    "Sungjae Im",
]

# ============================================================
# ADMIN STATE  (load / save)
# ============================================================
DEFAULT_STATE = {
    "daily_winners":       {"Thursday":"","Friday":"","Saturday":"","Sunday":""},
    "score_overrides":     {},
    "entries_frozen":      False,
    "tournament_finished": False,
    "tournament_name":     "",
    "entry_cutoff_time":   "",   # ISO timestamp — entries submitted before this are hidden
    "disqualified":        [],   # list of venmo handles or timestamps flagged by admin
    "history":             [],
    "course_par":          0,    # 0 = auto-detect from ESPN; set manually to override
    "rank_snapshot":       {},   # {email_or_venmo: rank_int} — captured by admin for position-arrow diffs
    "rank_snapshot_time":  "",   # ISO timestamp of last snapshot
    "tournament_start":    "",   # ISO timestamp — used for tee-time countdown strip
    # Payment tracking — entry_key ("venmo|timestamp") → True means paid.
    # Unpaid entries render with a pending pill and don't count toward the pot.
    "paid_entries":        {},
    # ── Private Leagues ──
    # leagues: {CODE: {"name": str, "fee": int, "commissioner_email": str,
    #                  "created_at": iso_str, "members": [email_lower, ...]}}
    # league_memberships: {email_lower: CODE}  — one league per email at a time
    "leagues":             {},
    "league_memberships":  {},
}

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            for k, v in DEFAULT_STATE.items():
                data.setdefault(k, v)
            return data
        except:
            pass
    return dict(DEFAULT_STATE)

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)

if "admin_state" not in st.session_state:
    st.session_state.admin_state = load_state()

admin = st.session_state.admin_state

# ============================================================
# PRIVATE LEAGUES  (helpers + URL param parsing)
# ------------------------------------------------------------
# A private league is a mini-pool inside the main app.  Anyone can create
# one (self-serve), gets back a unique 6-char code, and shares the link
# `clubhousepool.golf/?league=CODE` with friends. Anyone who submits an
# entry while that URL is active is auto-added as a member of that league.
# The leaderboard, pot, and payouts all scope to the league when ?league=
# is present; otherwise the public pool renders as normal.
# ============================================================
import random as _rnd_leagues

# Ambiguous glyphs stripped (0/O, 1/I/L) for clean text-message sharing.
_LEAGUE_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

def _generate_league_code(existing_codes):
    """Return a 6-char uppercase code that isn't already in use."""
    for _ in range(200):
        code = "".join(_rnd_leagues.choice(_LEAGUE_CODE_ALPHABET) for _ in range(6))
        if code not in existing_codes:
            return code
    # Extremely unlikely to hit — fall back to longer code
    return "".join(_rnd_leagues.choice(_LEAGUE_CODE_ALPHABET) for _ in range(8))

def _normalize_league_code(raw):
    """Clean up a user-typed or URL-pasted league code → uppercase A-Z0-9."""
    if not raw:
        return ""
    return "".join(c for c in str(raw).upper() if c.isalnum())[:12]

# Reserved vanity codes — system-shadowing words + brand-protect + a small
# profanity guard. Codes are case-normalized to uppercase before this check.
_LEAGUE_RESERVED_CODES = {
    # System / routing
    "ADMIN","LOGIN","LOGOUT","API","NEW","JOIN","CREATE","DELETE","EDIT",
    "HELP","ABOUT","SETTINGS","USER","USERS","ROOT","NULL","UNDEFINED",
    "ERROR","TEST","INDEX","HOME","PUBLIC","LEAGUE","LEAGUES","CODE","CODES",
    # Brand
    "CLUBHOUSE","CLUBHOUSEPOOL","POOL",
    # Light profanity guard
    "FUCK","SHIT","BITCH","DICK","PUSSY","COCK","FAG",
    "NIGGER","RETARD","SLUT","WHORE","PORN","SEX","CUM","TWAT",
}

def _validate_vanity_code(raw, existing_codes):
    """Validate a user-typed vanity code.
    Returns (normalized_code, error_msg). If raw is blank, returns ("", None)
    meaning 'fall back to auto-generated.' If error_msg is set, the caller
    should NOT use the code."""
    code = _normalize_league_code(raw)
    if not code:
        return "", None     # blank → caller falls back to auto-gen
    if len(code) < 3:
        return code, "Custom code must be at least 3 characters."
    if len(code) > 12:
        return code, "Custom code must be 12 characters or fewer."
    if code in _LEAGUE_RESERVED_CODES:
        return code, f"'{code}' is reserved. Pick something else."
    if code in existing_codes:
        return code, f"'{code}' is already taken. Try another."
    return code, None

# ── Parse ?league=CODE URL param (early, so every subsequent section knows) ──
_current_league_code = ""
try:
    _qp_lg = st.query_params
    _lg_raw = _qp_lg.get("league", "")
    if isinstance(_lg_raw, list):
        _lg_raw = _lg_raw[0] if _lg_raw else ""
    _current_league_code = _normalize_league_code(_lg_raw)
except Exception:
    try:
        _qp_lg = st.experimental_get_query_params()
        _current_league_code = _normalize_league_code(_qp_lg.get("league", [""])[0])
    except Exception:
        _current_league_code = ""

# Resolve to the actual league record (or None if code is unknown / empty).
_leagues_store = admin.get("leagues", {}) or {}
current_league = _leagues_store.get(_current_league_code) if _current_league_code else None
# If someone visits with a bogus code, treat as public pool but remember the code
# so we can surface a friendly "League not found" message inline.
current_league_code = _current_league_code if current_league else ""
_league_code_attempted = _current_league_code  # for "not found" messaging

# Helpers the rest of the app uses to reason about league membership.
def _membership_map():
    return admin.get("league_memberships", {}) or {}

def _league_emails(code):
    """All emails that are members of this league (lowercased)."""
    if not code:
        return set()
    return {e.lower().strip() for e, c in _membership_map().items() if c == code}

def _email_league(email):
    """Which league (if any) does this email belong to? Returns code or ''."""
    if not email:
        return ""
    return _membership_map().get(email.lower().strip(), "")

def _join_league(email, code):
    """Record email → league membership. One league per email (last wins)."""
    if not email or not code:
        return
    e = email.lower().strip()
    c = _normalize_league_code(code)
    if c not in _leagues_store:
        return
    admin.setdefault("league_memberships", {})[e] = c
    # Also append to league's own members list (best-effort, de-duped)
    lg = admin["leagues"].get(c)
    if lg is not None:
        _members = lg.setdefault("members", [])
        if e not in _members:
            _members.append(e)
    save_state(admin)

def _render_join_by_code_inline(_admin):
    """'Have a league code?' expander.
    Renders as a Streamlit expander so it visually matches the
    'Start a private league' expander right next to it — both are
    rounded rows with a chevron, no mixing of buttons and dropdowns.
    Lets a friend who heard about a league verbally (no link) jump into
    it by typing the code their buddy gave them. On valid match we set
    the `league` query param and rerun, which routes them into the
    league view.
    """
    with st.expander("🔑  Have a league code? Join here", expanded=False):
        st.markdown(
            "<div style='color:#a7c9a7; font-size:0.88rem; line-height:1.5; margin-bottom:8px;'>"
            "Friend gave you a code over text or in person? Type it below "
            "and we'll drop you into their league."
            "</div>",
            unsafe_allow_html=True,
        )
        _jc1, _jc2 = st.columns([3, 1])
        with _jc1:
            _typed = st.text_input(
                "League code",
                key="join_by_code_input",
                placeholder="e.g. TIGER",
                max_chars=12,
                label_visibility="collapsed",
            )
        with _jc2:
            _go = st.button(
                "Join league",
                key="btn_do_join_by_code",
                type="primary",
                use_container_width=True,
            )

        if _go:
            _norm = _normalize_league_code(_typed or "")
            if not _norm:
                st.error("Please type a league code.")
            else:
                _all_codes = set((_admin.get("leagues") or {}).keys())
                if _norm not in _all_codes:
                    st.error(
                        f"No league found with code '{_norm}'. "
                        "Double-check the spelling with your friend."
                    )
                else:
                    # Route into the league view via query param so it sticks on refresh.
                    try:
                        st.query_params["league"] = _norm
                    except Exception:
                        try:
                            st.experimental_set_query_params(league=_norm)
                        except Exception:
                            pass
                    st.session_state.pop("join_by_code_input", None)
                    st.rerun()

def _league_entry_fee(code):
    """Return the per-entry $ fee for this league, or ENTRY_FEE for public pool."""
    if not code:
        return ENTRY_FEE
    lg = _leagues_store.get(code)
    if not lg:
        return ENTRY_FEE
    try:
        return int(lg.get("fee", ENTRY_FEE))
    except Exception:
        return ENTRY_FEE

# The fee that applies to THIS page view — league fee when scoped, else public.
ENTRY_FEE_ACTIVE = _league_entry_fee(current_league_code)

# ============================================================
# STYLES
# ============================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif !important;
    background-color: #0a0f0a !important;
    color: #e8ede8 !important;
}
.stApp { background: linear-gradient(160deg,#0a0f0a 0%,#0f1a0f 60%,#0a1208 100%) !important; }
.block-container { padding: 1.5rem 1.5rem !important; max-width: 1100px; }

/* Hero-left column: collapse the default Streamlit vertical gap between
   the title block and the Join Pool button so they read as one tight unit.
   The title's visual center aligns with the stat boxes, and the Join Pool
   button lands directly at the same Y as How It Works on the right. */
.st-key-hero_left [data-testid="stVerticalBlock"] { gap: 0 !important; }
.st-key-hero_left [data-testid="element-container"] { margin-bottom: 0 !important; }
.st-key-hero_left [data-testid="element-container"]:not(:last-child) { margin-bottom: 0 !important; }

/* Title block is a normal block-level container (not centered) so the title
   anchors at the left of the hero column, directly above the Join Pool
   button. The .title-inner wrapper is an inline-block that shrink-wraps
   to the title's width, which means the subtitle + pitch (block children
   of title-inner with text-align:center) end up centered UNDER just the
   title text, not floating across the whole column. */
.title-block { padding-top: 10px; margin: 0 0 14px 0; }
.title-inner { display: inline-block; }
.main-title {
    font-family: 'Playfair Display', serif;
    font-size: clamp(1.8rem, 5vw, 3rem);
    font-weight: 900; color:#fff; letter-spacing:-1px; line-height:1;
    /* Shrink-wrap to the actual text so the JS width measurement reflects
       where "Pool" visually ends, not the full column width. */
    display: inline-block;
    width: fit-content;
    max-width: 100%;
    margin: 0;
}
/* Tournament-name subtitle: same small size as before, but now plain white
   and centered under the title text (via title-inner's inline-block wrap). */
.main-subtitle {
    font-size: 0.75rem;
    color: #ffffff;
    letter-spacing: 3px;
    text-transform: uppercase;
    margin-top: 6px;
    text-align: center;
}
/* One-line pitch under subtitle — headlines the round-winners
   differentiator. The "mp-hook" span is the emphasized phrase. */
.main-pitch {
    margin-top: 8px;
    font-size: 0.9rem;
    color: #a7c9a7;
    font-weight: 400;
    line-height: 1.45;
    max-width: 520px;
    margin-left: auto;
    margin-right: auto;
    text-align: center;
}
.main-pitch .mp-hook {
    color: #d4af37;
    font-weight: 700;
    letter-spacing: 0.2px;
}
@media (max-width: 640px) {
    .main-pitch {
        font-size: 0.82rem;
        max-width: 100%;
        margin-top: 6px;
        line-height: 1.4;
    }
}

.stat-box {
    background: linear-gradient(135deg,#141f14,#1a2a1a);
    border:1px solid #2a3d2a; border-radius:12px; padding:14px 16px; text-align:center;
}
.stat-value { font-family:'Playfair Display',serif; font-size:clamp(1.4rem,4vw,2rem); font-weight:700; color:#fff; line-height:1; }
.stat-label { font-size:0.65rem; color:#4a6b4a; text-transform:uppercase; letter-spacing:2px; margin-top:4px; }

.section-title {
    font-family:'Playfair Display',serif; font-size:clamp(1rem,3vw,1.3rem);
    color:#fff; letter-spacing:1px; margin-bottom:12px;
    border-left:3px solid #fff; padding-left:12px;
}
.section-title .section-sub {
    font-size:0.72rem; font-weight:500; color:#d4af37cc;
    letter-spacing:1.5px; text-transform:uppercase;
    margin-left:4px;
}

/* ── Private League banner (shown when ?league=CODE) ── */
.league-banner {
    background: linear-gradient(135deg, #1a2a1a, #1f3a2a);
    border: 1px solid #4ade8066;
    border-radius: 14px;
    padding: 12px 16px;
    margin: 0 0 14px 0;
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px; flex-wrap: wrap;
    box-shadow: 0 0 22px #4ade8022;
}
.league-banner .lb-left { display:flex; flex-direction:column; gap:2px; }
.league-banner .lb-eyebrow {
    font-size: 0.6rem; color:#4ade80; letter-spacing: 2.5px;
    text-transform: uppercase; font-weight: 700;
}
.league-banner .lb-name {
    font-family:'Playfair Display', serif; font-size: 1.15rem;
    color:#fff; font-weight: 700; line-height: 1.1;
}
.league-banner .lb-meta {
    display:flex; gap:10px; flex-wrap:wrap; align-items:center;
    font-size:0.72rem; color:#a7c9a7; letter-spacing:1px;
    text-transform:uppercase;
}
.league-banner .lb-meta .lb-dot { color:#2a3d2a; }
.league-banner .lb-code-box {
    background:#0c1a0c; border:1px solid #2a3d2a;
    border-radius: 8px; padding: 6px 10px;
    font-family: 'Courier New', monospace; color:#d4af37;
    font-weight: 700; letter-spacing: 3px; font-size: 0.95rem;
}

/* "Not found" warning for a bogus ?league= code */
.league-not-found {
    background: #2a1a10; border: 1px solid #a04a2a;
    border-radius: 10px; padding: 10px 14px; margin: 0 0 12px 0;
    color: #ffb991; font-size: 0.82rem;
}

/* Small "viewing public pool" return link */
.league-return-link {
    font-size: 0.7rem; color:#6b8a6b; text-decoration: none;
    padding: 4px 10px; border-radius: 8px;
    border: 1px solid #2a3d2a; background: transparent;
    transition: all 0.15s ease; white-space: nowrap;
}
.league-return-link:hover { color:#fff; border-color:#4a6b4a; }

/* ── Create-a-League CTA (sits below Join Pool) ── */
.create-league-cta {
    font-size: 0.75rem; color:#8ab08a; text-align: center;
    margin: 6px 0 0 0; letter-spacing: 0.5px;
}
.create-league-cta strong { color:#4ade80; font-weight:600; }

/* Shareable invite link box (after creating a league) */
.league-share-box {
    background: linear-gradient(135deg, #0f1a0f, #141f14);
    border: 1px solid #4ade8055;
    border-radius: 12px;
    padding: 14px 16px;
    margin-top: 12px;
}
.league-share-box .ls-title {
    font-family:'Playfair Display', serif; color:#fff;
    font-size: 1rem; margin-bottom: 6px;
}
.league-share-box .ls-code {
    font-family: 'Courier New', monospace; color:#d4af37;
    font-size: 1.3rem; font-weight: 700; letter-spacing: 4px;
    display: inline-block; padding: 6px 14px;
    background: #0a0f0a; border-radius: 8px; border: 1px solid #2a3d2a;
    margin: 4px 0 8px 0;
}
.league-share-box .ls-url {
    display: block; color:#4ade80; font-size:0.85rem;
    word-break: break-all; background: #0a0f0a;
    padding: 8px 12px; border-radius: 8px;
    border: 1px solid #2a3d2a; margin-top: 6px;
}
.league-share-box .ls-hint { font-size: 0.72rem; color:#6b8a6b; margin-top:8px; }

@media (max-width: 640px) {
    .league-banner { flex-direction: column; align-items: flex-start; }
    .league-banner .lb-code-box { align-self: flex-start; }
    .league-banner .lb-meta { font-size: 0.68rem; }
}

.entry-card {
    background:linear-gradient(135deg,#111a11,#141f14);
    border:1px solid #1e2e1e; border-radius:12px;
    padding:12px 16px; margin-bottom:8px;
    display:flex; align-items:center; gap:12px;
}
.entry-card.leader { border-color:#d4af37aa; background:linear-gradient(135deg,#141f14,#1a281a); box-shadow:0 0 18px #d4af3722; }
.entry-card.you { border-color:#4ade80aa; box-shadow:0 0 16px #4ade8033; }
.entry-card.leader.you { border-color:#d4af37aa; box-shadow:0 0 22px #4ade8044, inset 0 0 0 1px #4ade8055; }
.you-pill {
    background:linear-gradient(135deg,#4ade80,#22c55e);
    color:#052b10; font-size:0.55rem; font-weight:800;
    padding:1px 6px; border-radius:8px; letter-spacing:1.5px;
    margin-left:6px; text-transform:uppercase; vertical-align:middle;
    display:inline-block;
}
/* Pending payment pill — entry shown but not counted toward pot */
.pending-pill {
    background:#2a1e0d; color:#f5c872;
    border:1px solid #d4af3766;
    font-size:0.55rem; font-weight:800;
    padding:1px 6px; border-radius:8px; letter-spacing:1.2px;
    margin-left:6px; text-transform:uppercase; vertical-align:middle;
    display:inline-block;
}
.entry-card.pending {
    opacity:0.78;
    background:repeating-linear-gradient(135deg,#111a11,#111a11 8px,#141f14 8px,#141f14 16px);
}
.entry-card.pending:hover { opacity:0.95; }
/* Cut pill shown next to golfer names who missed the cut */
.cut-pill {
    background:#2a0d0d; color:#ff7070;
    border:1px solid #a33;
    font-size:0.52rem; font-weight:800;
    padding:1px 5px; border-radius:6px; letter-spacing:1.2px;
    margin-left:6px; text-transform:uppercase;
    display:inline-block; vertical-align:middle;
}
/* Little sub-label under the Entries stat showing paid/pending breakdown */
.stat-sub {
    font-size:0.55rem; color:#d4af37cc;
    text-transform:uppercase; letter-spacing:1.2px;
    margin-top:2px; font-weight:600;
}
.rank-badge { font-family:'Playfair Display',serif; font-size:1.2rem; font-weight:900; color:#4a6b4a; width:32px; text-align:center; flex-shrink:0; }
.rank-badge.top3 { color:#fff; }
.rank-wrap { display:flex; flex-direction:column; align-items:center; gap:2px; flex-shrink:0; }
.pos-delta {
    font-size:0.58rem; font-weight:700;
    padding:1px 5px; border-radius:6px; letter-spacing:0.3px;
    white-space:nowrap;
}
.pos-up   { background:#0e2a0e; color:#4ade80; border:1px solid #2a6a2a; }
.pos-down { background:#2a0e0e; color:#f87171; border:1px solid #6a2a2a; }
.pos-same { background:#1a1a1a; color:#6a8a6a; border:1px solid #2a3a2a; }
.pos-new  { background:#1a2a3a; color:#7cc9ff; border:1px solid #3d95ce; }
.hof-pill {
    display:inline-block; font-size:0.55rem; font-weight:800;
    padding:1px 5px; border-radius:6px; margin-left:5px;
    letter-spacing:1px; vertical-align:middle; text-transform:uppercase;
}
.hof-pill-gold   { background:#2a1f08; color:#d4af37; border:1px solid #d4af3755; }
.hof-pill-silver { background:#1a1a1a; color:#a8a29e; border:1px solid #5a554f55; }

/* Floating admin gear — tiny and unobtrusive, bottom-LEFT corner.
   Moved from bottom-right because Streamlit's "Manage app" floating button
   sits bottom-right for app owners and is impossible to reliably hide. */
.admin-gear {
    position: fixed;
    bottom: 14px; left: 14px;
    width: 32px; height: 32px;
    display: flex; align-items: center; justify-content: center;
    background: #0d160d; border: 1px solid #1e2e1e; border-radius: 50%;
    color: #4a6b4a !important;
    font-size: 14px; text-decoration: none !important;
    opacity: 0.55; transition: opacity 0.2s, transform 0.2s, color 0.2s;
    z-index: 9999;
    cursor: pointer;
}
.admin-gear:hover, .admin-gear:active {
    opacity: 1; color: #e8ede8 !important;
    transform: rotate(45deg);
}
@media (max-width: 640px) {
    .admin-gear { bottom: 12px; left: 12px; width: 32px; height: 32px; font-size: 13px; opacity: 0.7; }
}

/* Admin panel group banners — visually separate each lifecycle phase */
.admin-group {
    display:flex; align-items:center; justify-content:space-between;
    margin:22px 0 10px 0; padding:10px 14px;
    border-radius:8px; border-left:4px solid;
    font-family:'Playfair Display', serif;
}
.admin-group .g-title { font-size:1.05rem; font-weight:700; letter-spacing:0.5px; color:#fff; }
.admin-group .g-when  { font-size:0.72rem; color:#c8d8c8; letter-spacing:1.5px; text-transform:uppercase; opacity:0.85; }
.admin-group.setup  { background:linear-gradient(90deg,#1a2a1a,#0d160d); border-color:#d4af37; }
.admin-group.during { background:linear-gradient(90deg,#0d1a1f,#0d160d); border-color:#4ade80; }
.admin-group.wrap   { background:linear-gradient(90deg,#1a0d1a,#0d160d); border-color:#a78bfa; }
.admin-group.debug  { background:linear-gradient(90deg,#1a1515,#0d160d); border-color:#6b6b6b; }
.admin-phase-hint {
    background:#0f1e0f; border:1px solid #2a3d2a; border-radius:8px;
    padding:10px 14px; margin:8px 0 18px 0; color:#c8d8c8; font-size:0.88rem;
    line-height:1.5;
}
.admin-phase-hint strong { color:#d4af37; }

/* Floating "Rules" pill — clearly visible, bottom-right, next to admin gear */
.help-icon {
    position: fixed;
    bottom: 14px; right: 54px;
    display: inline-flex; align-items: center; gap: 5px;
    padding: 6px 12px;
    background: #0f1a0f; border: 1px solid #4a7a4a; border-radius: 18px;
    color: #c8d8c8 !important;
    font-size: 0.78rem; font-weight: 600; text-decoration: none !important;
    letter-spacing: 0.4px;
    opacity: 0.9; transition: opacity 0.2s, transform 0.2s, background 0.2s, color 0.2s;
    z-index: 9999;
    cursor: pointer;
    box-shadow: 0 3px 10px rgba(0,0,0,0.35);
    font-family: inherit;
}
.help-icon::before {
    content: "?";
    display: inline-flex; align-items: center; justify-content: center;
    width: 16px; height: 16px; border-radius: 50%;
    background: #4a7a4a; color: #0a0f0a; font-weight: 800;
    font-size: 0.7rem;
}
.help-icon:hover, .help-icon:active {
    opacity: 1; color: #fff !important;
    transform: translateY(-1px);
    background: #1a2a1a;
    border-color: #6a9a6a;
}
@media (max-width: 640px) {
    .help-icon { bottom: 10px; right: 44px; padding: 5px 10px; font-size: 0.72rem; }
    .help-icon::before { width: 14px; height: 14px; font-size: 0.62rem; }
}

/* Shareable "brag" card rendered after successful entry */
.brag-card {
    background: radial-gradient(circle at top left, #1a2a1a 0%, #0a0f0a 75%);
    border: 2px solid #d4af37;
    border-radius: 16px;
    padding: 22px 24px;
    margin: 14px auto;
    max-width: 420px;
    box-shadow: 0 0 30px #d4af3744, inset 0 0 24px #d4af3711;
    text-align:center;
    position:relative;
}
.brag-badge {
    position:absolute; top:-12px; left:50%; transform:translateX(-50%);
    background:linear-gradient(135deg,#d4af37,#b8860b);
    color:#1a1408; font-size:0.6rem; font-weight:900; letter-spacing:2px;
    padding:3px 12px; border-radius:14px; text-transform:uppercase;
    box-shadow: 0 2px 8px #d4af3755;
}
.brag-header {
    font-family:'Playfair Display',serif;
    font-size:1.4rem; color:#fff; font-weight:900; margin-top:6px; line-height:1.1;
}
.brag-sub { font-size:0.7rem; color:#8aad8a; letter-spacing:2px; text-transform:uppercase; margin-bottom:14px; }
.brag-picks {
    display:flex; flex-direction:column; gap:6px; margin:12px 0;
}
.brag-pick {
    background:#0d160d; border:1px solid #2a4a2a; border-radius:8px;
    padding:8px 12px; font-size:0.92rem; color:#e8ede8; font-weight:600;
    display:flex; justify-content:space-between; align-items:center;
}
.brag-pick .tier {
    font-size:0.56rem; color:#d4af37; letter-spacing:1.5px;
    font-weight:800; background:#1a1408; padding:2px 6px; border-radius:4px;
}
.brag-footer {
    font-size:0.7rem; color:#4a6b4a; margin-top:12px;
    letter-spacing:1px; text-transform:uppercase;
}
.brag-footer strong { color:#fff; font-weight:700; letter-spacing:0.5px; text-transform:none; }

/* Red pulsing dot for "live" state */
.live-dot {
    display:inline-block; width:8px; height:8px; border-radius:50%;
    background:#ef4444; box-shadow:0 0 8px #ef4444;
    margin-right:8px; vertical-align:middle;
    animation: live-pulse 1.2s ease-in-out infinite;
}
@keyframes live-pulse {
    0%,100% { opacity:1; transform:scale(1); }
    50%     { opacity:0.6; transform:scale(1.2); }
}

/* Tee-time countdown strip */
.tee-strip {
    background:linear-gradient(135deg,#141f14,#1a2a1a);
    border:1px solid #2a4a2a; border-radius:10px;
    padding:10px 16px; margin:0 0 14px 0;
    display:flex; gap:14px; align-items:center; justify-content:center; flex-wrap:wrap;
}
.tee-strip .tee-label {
    font-size:0.6rem; color:#4a6b4a; letter-spacing:2px; text-transform:uppercase;
}
.tee-strip .tee-count {
    font-family:'Playfair Display',serif; font-size:1.1rem; color:#fff; font-weight:700;
    letter-spacing:0.5px;
}
.tee-strip.urgent { border-color:#d4af37; box-shadow:0 0 14px #d4af3733; }
.tee-strip.live   { border-color:#4ade80; box-shadow:0 0 14px #4ade8033; }
.tee-strip.live .tee-count { color:#4ade80; }
@media (max-width: 640px) {
    .tee-strip { padding:8px 12px; gap:10px; }
    .tee-strip .tee-count { font-size:0.95rem; }
    .tee-strip .tee-label { font-size:0.55rem; letter-spacing:1.5px; }
}

/* "Who are you?" identify strip */
.id-strip {
    background:#0d160d; border:1px solid #1e2e1e; border-radius:10px;
    padding:10px 14px; margin:4px 0 14px 0;
    display:flex; gap:10px; align-items:center; flex-wrap:wrap;
}
.id-strip .lbl { font-size:0.65rem; color:#4a6b4a; letter-spacing:2px; text-transform:uppercase; }
.id-strip .name { font-size:0.9rem; color:#fff; font-weight:600; }
.id-strip .hint { font-size:0.72rem; color:#6a8a6a; }
.rank-stack {
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    width:62px; flex-shrink:0; gap:4px;
}
.rank-stack .medal { font-size:1.4rem; line-height:1; }
.rank-stack .rank-num-lead {
    font-family:'Playfair Display',serif; font-size:1.4rem; font-weight:900;
    color:#d4af37; line-height:1;
}
.rank-stack .money-pill {
    background:linear-gradient(135deg,#d4af37,#b8860b);
    color:#1a1408; font-size:0.7rem; font-weight:800;
    padding:2px 9px; border-radius:12px; line-height:1.2;
    box-shadow:0 2px 6px #d4af3755; white-space:nowrap;
    letter-spacing:0.3px;
}
.entry-name { font-size:0.95rem; font-weight:600; color:#e8ede8; line-height:1.1; }
.entry-venmo { font-size:0.72rem; color:#4a6b4a; margin-top:1px; }
.entry-id { min-width:130px; flex-shrink:0; }
.picks-area { flex:1; display:flex; gap:6px; flex-wrap:wrap; align-content:center; min-width:0; }
.pick-chip {
    background:#0d160d; border:1px solid #2a3d2a; border-radius:6px;
    padding:4px 10px; font-size:0.95rem; color:#c8d8c8; white-space:nowrap;
    font-weight:500;
}
.pick-chip.best { border-color:#ffffff33; background:#1a2a1a; }
.pick-score-under { color:#4ade80; font-weight:600; }
.pick-score-over  { color:#f87171; font-weight:600; }
.pick-score-even  { color:#8aad8a; font-weight:600; }

/* Sleek Rules dropdown — sits under pot/entries stats, aligned to the same width.
   Primary selector uses the Streamlit container key. */
.rules-anchor { display:none; }
.st-key-rules_container {
    width: 100% !important;
    margin: 10px 0 0 0 !important;
    padding: 0 !important;
}
.st-key-rules_container details,
.st-key-rules_container div[data-testid="stExpander"] {
    width: 100% !important;
    margin: 0 !important;
    border: 1px solid #2a3d2a !important;
    border-radius: 12px !important;
    background: linear-gradient(135deg,#141f14,#1a2a1a) !important;
    overflow: hidden !important;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.02);
}
.st-key-rules_container details > summary,
.st-key-rules_container div[data-testid="stExpander"] summary {
    padding: 14px 16px !important;
    font-size: 0.72rem !important;
    letter-spacing: 2px !important;
    text-transform: uppercase !important;
    color: #8aad8a !important;
    background: transparent !important;
    transition: background .15s, color .15s;
}
.st-key-rules_container details > summary:hover,
.st-key-rules_container div[data-testid="stExpander"] summary:hover {
    background: #0d160d !important;
    color: #e8ede8 !important;
}
.st-key-rules_container details > summary p,
.st-key-rules_container div[data-testid="stExpander"] summary p {
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    letter-spacing: 2px !important;
    text-transform: uppercase !important;
    color: inherit !important;
}

/* Tiny "Highlight me" toggle — small inline link-style button */
.highlight-me-toggle-wrap { display:none; }
div[data-testid="stVerticalBlock"] > div:has(> div > .highlight-me-toggle-wrap) + div button,
div:has(> .highlight-me-toggle-wrap) + div .stButton > button {
    background: transparent !important;
    border: 1px dashed #2a4a2a !important;
    color: #6a8a6a !important;
    font-size: 0.72rem !important;
    padding: 4px 12px !important;
    min-height: 0 !important;
    height: auto !important;
    width: auto !important;
    line-height: 1.2 !important;
    box-shadow: none !important;
    letter-spacing: 0.3px !important;
    border-radius: 14px !important;
    margin: 2px 0 8px 0 !important;
}
div[data-testid="stVerticalBlock"] > div:has(> div > .highlight-me-toggle-wrap) + div button:hover,
div:has(> .highlight-me-toggle-wrap) + div .stButton > button:hover {
    color: #e8ede8 !important;
    border-color: #4a7a4a !important;
    background: #0d160d !important;
}
.highlight-me-inline { margin: 4px 0 10px 0; }

/* Primary CTA — Join Pool (friendly green, matches How It Works styling).
   Width is measured to end right where "Pool" ends in the main title. */
.join-pool-marker { display:none; }
.st-key-open_entry,
.st-key-open_entry > div,
div:has(> .join-pool-marker) + div .stButton {
    width: auto !important;
    max-width: 100% !important;
    margin-left: 0 !important;
    margin-right: auto !important;
}
.st-key-open_entry button,
div:has(> .join-pool-marker) + div .stButton > button {
    background: linear-gradient(135deg,#141f14,#1a2a1a) !important;
    color: #8aad8a !important;
    font-family: 'Inter', 'Helvetica Neue', sans-serif !important;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    letter-spacing: 2px !important;
    text-transform: uppercase !important;
    padding: 14px 16px !important;
    min-height: 48px !important;
    width: 100% !important;
    border: 1px solid #2a3d2a !important;
    border-radius: 12px !important;
    box-shadow: none !important;
    transition: background .15s ease, border-color .15s ease, color .15s ease, transform .1s ease !important;
    margin: 0 !important;
}
.st-key-open_entry button:hover,
div:has(> .join-pool-marker) + div .stButton > button:hover {
    background: #0d160d !important;
    border-color: #4a7a4a !important;
    color: #e8ede8 !important;
    transform: translateY(-1px) !important;
}
.st-key-open_entry button:active,
div:has(> .join-pool-marker) + div .stButton > button:active {
    transform: translateY(0) !important;
    background: #111a11 !important;
}
@media (max-width: 640px) {
    .st-key-open_entry,
    .st-key-open_entry > div,
    div:has(> .join-pool-marker) + div .stButton {
        max-width: 100% !important;
    }
    .st-key-open_entry button,
    div:has(> .join-pool-marker) + div .stButton > button {
        font-size: 0.9rem !important;
        padding: 11px 18px !important;
        min-height: 42px !important;
        max-width: 100% !important;
        letter-spacing: 1.2px !important;
    }
}

/* Per-day score chips (Thu / Fri / Sat / Sun) — dedicated column on the right
   so golfer picks remain the primary focus on the left. */
.days-area {
    display:grid;
    grid-template-columns: repeat(4, minmax(40px, 1fr));
    gap:4px;
    flex-shrink:0;
    width:auto;
    padding:0 4px 0 6px;
    border-left:1px solid #1a2a1a;
    align-self:stretch;
    align-items:center;
}
.day-chip {
    background:#0a120a; border:1px solid #1e2e1e; border-radius:6px;
    padding:4px 6px; color:#6a8a6a; white-space:nowrap;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    gap:1px; line-height:1.05;
    min-width:42px;
}
.day-chip .day-lbl { color:#4a6b4a; letter-spacing:0.8px; font-size:0.52rem; text-transform:uppercase; }
.day-chip .day-val { font-weight:700; font-size:0.78rem; }
.day-chip.empty .day-val { color:#2a3a2a; font-weight:500; }
.day-chip.winner {
    border-color:#d4af37aa; background:#1a1408;
    box-shadow:0 0 8px #d4af3722;
}
.day-chip.winner .day-lbl { color:#d4af37; }
.day-chip.under .day-val { color:#4ade80; }
.day-chip.over  .day-val { color:#f87171; }
.day-chip.even  .day-val { color:#8aad8a; }
.total-score { font-family:'Playfair Display',serif; font-size:1.4rem; font-weight:700; width:48px; text-align:right; flex-shrink:0; }
.total-under { color:#4ade80; }
.total-over  { color:#f87171; }
.total-even  { color:#8aad8a; }
.payout-badge {
    background:#ffffff15; border:1px solid #ffffff44; color:#fff;
    font-size:0.68rem; font-weight:700; padding:2px 7px; border-radius:20px; letter-spacing:.5px;
}
.override-badge {
    background:#2a1a00; border:1px solid #6b4a0044; color:#fbbf24;
    font-size:0.62rem; padding:1px 5px; border-radius:10px; margin-left:3px;
}

/* Entry form */
.entry-form-wrap {
    background: linear-gradient(135deg,#111a11,#141f14);
    border:1px solid #2a4a2a; border-radius:14px; padding:18px 20px; margin: 10px 0 18px 0;
}
.entry-form-title {
    font-family:'Playfair Display',serif; font-size:1.1rem; color:#fff; margin-bottom:4px;
}
.entry-form-sub { font-size:0.72rem; color:#4a6b4a; letter-spacing:2px; text-transform:uppercase; margin-bottom:12px; }

.venmo-cta {
    background: linear-gradient(135deg, #3d95ce, #2a7cb8);
    color:#fff !important; padding:14px 26px; border-radius:10px;
    font-weight:700; font-size:1rem; text-decoration:none !important;
    letter-spacing:1px; display:inline-block; border:none; text-align:center;
    box-shadow: 0 4px 14px #2a7cb855;
}
.success-card {
    background:linear-gradient(135deg,#0e2a0e,#143514);
    border:1px solid #2a6a2a; border-radius:14px; padding:20px; margin:10px 0 18px 0;
    text-align:center;
}
.success-title { font-family:'Playfair Display',serif; font-size:1.3rem; color:#4ade80; margin-bottom:6px; }
.success-sub { font-size:0.82rem; color:#8aad8a; margin-bottom:14px; }

.profile-block {
    background:#0d160d; border:1px solid #2a4a2a; border-radius:10px;
    padding:12px 16px; margin:4px auto 16px auto; max-width:480px;
}
.profile-label { font-size:0.62rem; color:#4a6b4a; letter-spacing:2px; text-transform:uppercase; margin-bottom:8px; }
.profile-stats { display:flex; justify-content:space-around; gap:8px; flex-wrap:wrap; }
.profile-stat { text-align:center; flex:1; min-width:60px; }
.profile-stat-val { font-family:'Playfair Display',serif; font-size:1.3rem; font-weight:700; color:#fff; line-height:1; }
.profile-stat-label { font-size:0.62rem; color:#4a6b4a; text-transform:uppercase; letter-spacing:1px; margin-top:3px; }
.profile-newbie { font-size:0.82rem; color:#8aad8a; text-align:center; padding:4px 8px; }
.profile-newbie strong { color:#fff; }

/* Share / Invite — compact inline strip */
.share-inline {
    display:inline-flex; align-items:center; gap:4px; flex-wrap:wrap;
    margin:8px 0 10px 0;
    font-size:0.62rem; color:#5a7a5a;
}
.share-inline .lbl { color:#3a5a3a; letter-spacing:1.2px; text-transform:uppercase; font-size:0.5rem; margin-right:2px; }
.share-inline .share-link {
    color:#6a8a6a !important; text-decoration:none !important;
    background:transparent; border:1px solid #1e2e1e; border-radius:10px;
    padding:1px 7px; line-height:1.25;
    transition: background 0.15s, border-color 0.15s, color 0.15s;
    cursor:pointer; font-family:inherit; font-size:0.6rem; font-weight:500;
    display:inline-flex; align-items:center; gap:2px;
}
.share-inline .share-link:hover {
    color:#c8d8c8 !important; background:#0d160d;
    border-color:#4a7a4a;
}
.share-inline .divider-dot { display:none; }

/* Mobile responsive — iPhone SE (375px) and up */
@media (max-width: 640px) {
    .block-container { padding: 0.75rem 0.6rem !important; }

    /* Header */
    .main-title { letter-spacing:-0.5px; }
    .main-subtitle { letter-spacing:2px; font-size:0.68rem; }
    .stat-box { padding:10px 8px; }
    .stat-label { font-size:0.58rem; letter-spacing:1px; }
    .section-title { padding-left:10px; margin-bottom:10px; }

    /* ================================================================
       ENTRY CARD — COMPACT MOBILE LAYOUT
       Goals: (1) skinnier cards so more fit on screen, (2) pick names
       always fully visible, (3) scores right-aligned for easy scanning.
       ================================================================ */
    .entry-card {
        display: flex !important;
        flex-wrap: wrap !important;
        gap: 2px 10px !important;
        padding: 8px 12px !important;
        align-items: center !important;
    }
    /* First row: rank | name+venmo | total score */
    .rank-badge { font-size: 0.95rem !important; width: 24px !important; flex-shrink: 0; }
    .rank-stack { width: 44px !important; gap: 2px !important; flex-shrink: 0; }
    .rank-stack .medal { font-size: 1.1rem !important; }
    .rank-stack .rank-num-lead { font-size: 1rem !important; }
    .rank-stack .money-pill { font-size: 0.58rem !important; padding: 1px 6px !important; letter-spacing: 0 !important; }
    .rank-wrap { width: auto !important; flex-shrink: 0; }
    .pos-delta { font-size: 0.52rem !important; padding: 0px 4px !important; }

    .entry-id { flex: 1 1 auto !important; min-width: 0 !important; padding-left: 2px; }
    .entry-name { font-size: 0.92rem !important; line-height: 1.15 !important; }
    .entry-venmo { font-size: 0.65rem !important; margin-top: 0 !important; }

    .total-score {
        order: 2 !important;
        font-size: 1.3rem !important;
        width: auto !important;
        min-width: 44px !important;
        text-align: right !important;
        flex-shrink: 0 !important;
    }

    /* Picks area becomes a clean vertical LIST of "Name ……… Score" rows.
       No pill borders, no background — just readable text, full width. */
    .picks-area {
        flex: 0 0 100% !important;
        width: 100% !important;
        max-width: 100% !important;
        display: flex !important;
        flex-direction: column !important;
        gap: 0 !important;
        order: 3 !important;
        margin: 4px 0 0 0 !important;
        padding: 4px 0 0 0 !important;
        border-top: 1px solid #1a2a1a !important;
    }
    .pick-chip {
        background: transparent !important;
        border: none !important;
        border-radius: 0 !important;
        padding: 5px 2px !important;
        font-size: 1.05rem !important;
        white-space: normal !important;
        display: flex !important;
        justify-content: space-between !important;
        align-items: baseline !important;
        width: 100% !important;
        max-width: 100% !important;
        line-height: 1.25 !important;
        overflow: visible !important;
        text-overflow: clip !important;
    }
    .pick-chip.best { background: transparent !important; }
    .pick-chip-name {
        flex: 1 1 auto;
        min-width: 0;
        color: #e0ece0 !important;
        font-weight: 600 !important;
        font-size: 1.05rem !important;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .pick-chip.best .pick-chip-name {
        color: #fff !important;
        font-weight: 700 !important;
    }
    .pick-chip-star { margin-right: 4px; }
    .pick-chip-score,
    .pick-chip .pick-score-under,
    .pick-chip .pick-score-over,
    .pick-chip .pick-score-even {
        flex-shrink: 0 !important;
        margin-left: 10px !important;
        font-size: 1.05rem !important;
        font-weight: 700 !important;
        font-variant-numeric: tabular-nums;
    }

    /* Days row — compact single line on mobile */
    .days-area {
        flex: 0 0 100% !important;
        width: 100% !important;
        max-width: 100% !important;
        order: 4 !important;
        grid-template-columns: repeat(4, 1fr) !important;
        border-left: none !important;
        border-top: 1px dashed #1a2a1a !important;
        padding: 5px 0 0 0 !important;
        margin: 4px 0 0 0 !important;
        gap: 4px !important;
    }
    .day-chip {
        padding: 2px 3px !important;
        min-width: 0 !important;
        background: transparent !important;
        border: none !important;
        flex-direction: row !important;
        justify-content: center !important;
        align-items: baseline !important;
        gap: 4px !important;
    }
    .day-chip .day-lbl { font-size: 0.55rem !important; letter-spacing: 0.8px !important; }
    .day-chip .day-val { font-size: 0.75rem !important; font-weight: 700 !important; }
    .day-chip.winner {
        background: #1a1408 !important;
        border: 1px solid #d4af37aa !important;
        border-radius: 6px !important;
    }

    /* Winners grid — 2 cols on phones (4 days = 2x2) */
    .winners-grid { grid-template-columns: repeat(2,1fr) !important; gap:6px; }
    .winner-card { padding:10px 10px; }
    .winner-name { font-size:0.85rem; }
    .winner-payout { font-size:0.78rem; padding:3px 10px; }
    .winner-day { font-size:0.55rem; letter-spacing:1px; }

    /* Tournament Leaders + Hall of Fame rows */
    .tourney-row { padding: 8px 10px; font-size: 0.78rem; gap:8px; }
    .tourney-row span[style*="width:55px"],
    .tourney-row span[style*="width:50px"] { width:38px !important; font-size:0.7rem; }
    .tourney-row span[style*="width:80px"] { width:60px !important; font-size:0.72rem; }
    .tourney-row span[style*="width:28px"] { width:22px !important; }

    /* CTAs */
    .venmo-cta { width: 100%; padding: 14px; font-size:0.95rem; }
    .entry-form-wrap { padding:14px 14px; }
    .entry-form-title { font-size:1rem; }

    /* Rules expander content */
    div[data-testid="stExpander"] summary p { font-size:0.9rem !important; }

    /* Profile block */
    .profile-block { padding:10px 12px; }
    .profile-stat-val { font-size:1.1rem; }
    .profile-stat-label { font-size:0.56rem; }

    /* Share */
    .share-btn { min-width:0; font-size:0.78rem; padding:9px 8px; }
    .share-wrap { padding:10px 12px; }
}

/* Extra-narrow phones (<380px) */
@media (max-width: 380px) {
    .main-title { font-size:1.6rem !important; }
    .entry-card { padding: 7px 10px !important; }
    .pick-chip { font-size: 1.0rem !important; padding: 4px 2px !important; }
    .pick-chip-name { font-size: 1.0rem !important; }
    .pick-chip-score { font-size: 1.0rem !important; }
    .day-chip .day-lbl { font-size:0.5rem !important; }
    .day-chip .day-val { font-size:0.68rem !important; }
    .winners-grid { gap:5px; }
    .winner-name { font-size:0.78rem; }
    .tourney-row span[style*="width:50px"],
    .tourney-row span[style*="width:55px"] { display:none; }
}

/* ============================================================
   MOBILE-FIRST PASS — 99% of users are on phones.
   Force layout="wide" columns to stack, tighten tap targets,
   make Tournament Leaders + share row feel native.
   ============================================================ */
@media (max-width: 640px) {
    /* Force the 2/1 hero columns (and any top-level horizontal split) to
       stack vertically on phones. layout="wide" otherwise keeps them
       cramped side-by-side at 2:1 which is unreadable. */
    .block-container > div[data-testid="stVerticalBlock"] > div[data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
        gap: 10px !important;
    }
    .block-container > div[data-testid="stVerticalBlock"] > div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
    .block-container > div[data-testid="stVerticalBlock"] > div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
        flex: 1 1 100% !important;
        width: 100% !important;
        min-width: 100% !important;
    }

    /* Hero: center title + subtitle, center Join Pool button full-width */
    .st-key-hero_left .title-block { text-align: center; }
    .st-key-hero_left .main-title {
        display: block !important;
        width: 100% !important;
        max-width: 100% !important;
        font-size: clamp(2rem, 9vw, 2.6rem) !important;
        margin: 0 auto !important;
    }
    .st-key-hero_left .main-subtitle { text-align: center; }
    /* Join Pool button — full width on mobile, tall tap target */
    .st-key-open_entry,
    .st-key-open_entry > div {
        width: 100% !important;
        max-width: 100% !important;
    }
    .st-key-open_entry button {
        width: 100% !important;
        max-width: 100% !important;
        font-size: 0.95rem !important;
        padding: 14px 16px !important;
        min-height: 50px !important;
        letter-spacing: 1.5px !important;
    }

    /* Share row: center under CTA, bigger tap targets */
    .share-inline { justify-content: center !important; gap: 6px !important; margin-top: 10px !important; }
    .share-inline .share-link {
        font-size: 0.72rem !important;
        padding: 6px 10px !important;
        min-height: 30px;
    }

    /* Prize Pot / Entries stat row — equal-width, a touch more breathing room */
    .stat-box { padding: 12px 10px !important; }
    .stat-value { font-size: clamp(1.6rem, 6vw, 2rem) !important; }

    /* Rules / How It Works expander — bigger tap target, centered summary */
    .st-key-rules_container details > summary,
    .st-key-rules_container div[data-testid="stExpander"] summary {
        padding: 16px 14px !important;
        text-align: center;
    }

    /* (Entry-card / picks-area / pick-chip rules live in the earlier
       compact-list block — don't redeclare here.) */

    /* Tournament Leaders — allow tee-time pill to wrap below name on tight screens */
    .tourney-row { flex-wrap: wrap !important; padding: 9px 12px !important; gap: 6px 10px !important; }
    .tourney-pos { font-size: 0.82rem !important; width: 20px !important; }
    .tourney-name { font-size: 0.9rem !important; flex: 1 1 auto !important; min-width: 0 !important; }
    .tourney-tee { font-size: 0.68rem !important; padding: 2px 7px !important; order: 3; }
    .tourney-score-under,
    .tourney-score-over,
    .tourney-score-even { font-size: 0.92rem !important; flex-shrink: 0; }

    /* Tee-time countdown strip — center + a little more padding */
    .tee-strip { padding: 10px 12px !important; justify-content: center !important; }

    /* Identify strip — full width, centered */
    .id-strip { padding: 10px 12px !important; }
    .id-strip .name { font-size: 0.95rem !important; }

    /* Entry form tap targets — Streamlit inputs */
    .entry-form-wrap input,
    .entry-form-wrap select,
    .entry-form-wrap textarea,
    .entry-form-wrap [data-baseweb="select"] > div,
    div[data-testid="stTextInput"] input,
    div[data-testid="stSelectbox"] > div > div {
        min-height: 44px !important;
        font-size: 16px !important; /* iOS won't zoom when >=16px */
    }
    /* Submit / Cancel buttons in the form */
    div[data-testid="stFormSubmitButton"] button,
    div[data-testid="stButton"] > button {
        min-height: 44px !important;
        font-size: 0.88rem !important;
    }

    /* Venmo CTA button — already full width, keep tall for thumbs */
    .venmo-cta { padding: 16px 20px !important; font-size: 1rem !important; min-height: 50px; }

    /* Brag/share card after entry — fit phone nicely */
    .brag-card { padding: 18px 16px !important; max-width: 100% !important; }
    .brag-header { font-size: 1.2rem !important; }
    .brag-pick { padding: 7px 10px !important; font-size: 0.88rem !important; }

    /* Winners grid on phones → 2 cols (already set), tighten padding.
       Overall winner (last card) spans both columns for visual balance. */
    .winners-grid > .winner-card:last-child { grid-column: 1 / -1 !important; }
    .winner-card { padding: 9px 8px !important; }
    .winner-day { font-size: 0.52rem !important; letter-spacing: 1.2px !important; margin-bottom: 4px !important; }
    .winner-score { font-size: 0.72rem !important; }

    /* Section titles on mobile — stay prominent */
    .section-title { font-size: 1rem !important; margin-top: 6px; }

    /* Floating help / admin pills — gear is bottom-LEFT now, keep help bottom-right */
    .help-icon { bottom: 12px !important; right: 12px !important; }
    .admin-gear { bottom: 12px !important; left: 12px !important; right: auto !important; }
}

/* Very narrow phones — iPhone mini, older Android */
@media (max-width: 380px) {
    .block-container { padding: 0.6rem 0.5rem !important; }
    .st-key-hero_left .main-title { font-size: clamp(1.7rem, 8vw, 2.1rem) !important; }
    .stat-value { font-size: 1.4rem !important; }
    .stat-label { font-size: 0.52rem !important; letter-spacing: 0.8px !important; }
    .tourney-row { padding: 8px 10px !important; gap: 5px 8px !important; }
    .tourney-name { font-size: 0.85rem !important; }
    .tourney-tee { font-size: 0.62rem !important; padding: 1px 6px !important; }
}

.winners-grid { display:grid; grid-template-columns:repeat(5,1fr); gap:8px; margin-bottom:4px; }
.winner-card { background:linear-gradient(135deg,#111a11,#141f14); border:1px solid #1e2e1e; border-radius:10px; padding:12px 14px; text-align:center; }
.winner-card.has-winner { border-color:#2a4a2a; }
.winner-day { font-size:0.6rem; color:#4a6b4a; text-transform:uppercase; letter-spacing:2px; margin-bottom:5px; }
.winner-name { font-family:'Playfair Display',serif; font-size:0.95rem; font-weight:700; color:#fff; line-height:1.2; }
.winner-score { font-size:0.78rem; color:#4ade80; font-weight:600; margin-top:2px; }
.winner-payout {
    display:inline-block; margin-top:8px;
    background:linear-gradient(135deg,#1e3d1e,#2a5a2a);
    border:1px solid #4a7a4a; color:#e8ede8;
    font-size:0.88rem; font-weight:800; letter-spacing:0.5px;
    padding:4px 12px; border-radius:14px;
    box-shadow:0 2px 8px #2a5a2a33;
}
.winner-card.has-winner .winner-payout {
    background:linear-gradient(135deg,#d4af37,#b8860b);
    border-color:#d4af37; color:#1a1408;
}
.winner-live {
    display:block;
    width:fit-content;
    margin:8px auto 0 auto;
    background:#1a2a3a; border:1px solid #3d95ce; color:#7cc9ff;
    font-size:0.58rem; font-weight:800; letter-spacing:1.5px;
    padding:2px 8px; border-radius:10px; text-transform:uppercase;
    animation: pulse-live 2s ease-in-out infinite;
}
@keyframes pulse-live {
    0%,100% { opacity:1; box-shadow:0 0 0 0 #3d95ce44; }
    50%     { opacity:0.85; box-shadow:0 0 0 4px #3d95ce00; }
}
.winner-tbd { font-family:'Playfair Display',serif; font-size:1rem; color:#2a4a2a; }

/* ───────── Hall of Fame: Last Champion card (above the table) ───────── */
.last-champ {
    background: linear-gradient(135deg, #1a1408 0%, #2a1e0d 50%, #1a1408 100%);
    border: 1px solid rgba(212,175,55,0.45);
    border-radius: 12px;
    padding: 14px 18px;
    margin: 4px 0 14px 0;
    position: relative;
    overflow: hidden;
}
.last-champ::before {
    content: "";
    position: absolute; inset: 0;
    background: radial-gradient(circle at top right, rgba(212,175,55,0.18), transparent 60%);
    pointer-events: none;
}
.last-champ-label {
    font-size: 0.62rem; font-weight: 700; letter-spacing: 2px;
    color: #d4af37; text-transform: uppercase; margin-bottom: 4px;
    position: relative;
}
.last-champ-name {
    font-family: 'Playfair Display', serif;
    font-size: clamp(1.4rem, 4vw, 1.8rem);
    font-weight: 700; color: #fff; line-height: 1.1;
    position: relative;
}
.last-champ-meta {
    font-size: 0.78rem; color: #c8d8c8;
    margin-top: 6px; letter-spacing: 0.2px;
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    position: relative;
}
.last-champ-score {
    background: rgba(255,255,255,0.08);
    color: #fff; font-weight: 700;
    padding: 2px 8px; border-radius: 6px;
    font-size: 0.78rem;
}
.last-champ-winnings {
    color: #4ade80; font-weight: 700;
    background: rgba(74,222,128,0.1);
    padding: 2px 8px; border-radius: 6px;
    font-size: 0.78rem;
}
.hof-subhead {
    font-size: 0.62rem; font-weight: 700; letter-spacing: 2px;
    color: #8aad8a; text-transform: uppercase;
    margin: 2px 0 6px 2px;
}

/* ───────── Hall of Fame: cold-start "In the running" preview ───────── */
.hof-preview {
    background: linear-gradient(135deg, #0d160d, #141f14);
    border: 1px solid #2a3d2a;
    border-radius: 12px;
    padding: 14px 16px;
    margin: 4px 0 8px 0;
}
.hof-preview-label {
    font-size: 0.7rem; font-weight: 700; letter-spacing: 1.8px;
    color: #d4af37; text-transform: uppercase;
    margin-bottom: 10px;
}
.hof-preview-row {
    display: flex; align-items: center; gap: 12px;
    padding: 8px 4px; border-bottom: 1px solid #1a2a1a;
}
.hof-preview-row:last-of-type { border-bottom: none; }
.hof-preview-rank {
    font-size: 1.1rem; width: 28px; flex-shrink: 0;
}
.hof-preview-name {
    flex: 1; color: #e8ede8; font-weight: 600;
    font-size: 0.95rem;
}
.hof-preview-score {
    font-weight: 700; font-size: 0.95rem;
    font-family: 'Playfair Display', serif;
}
.hof-preview-footer {
    margin-top: 10px; padding-top: 10px;
    border-top: 1px solid #1e2e1e;
    font-size: 0.72rem; color: #8aad8a; font-style: italic;
    text-align: center; letter-spacing: 0.3px;
}

.tourney-container { background:#111a11; border:1px solid #1e2e1e; border-radius:12px; overflow:hidden; }
.tourney-row { display:flex; align-items:center; gap:14px; padding:10px 18px; border-bottom:1px solid #1a2a1a; font-size:0.88rem; }
.tourney-row:last-child { border-bottom:none; }
.tourney-pos { color:#4a6b4a; font-weight:600; width:22px; flex-shrink:0; font-size:0.78rem; }
.tourney-name { flex:1; color:#c0d4c0; }
.tourney-score-under { color:#4ade80; font-weight:700; }
.tourney-score-over  { color:#f87171; font-weight:700; }
.tourney-score-even  { color:#8aad8a; }
/* Tee-time pill — only renders when a player hasn't teed off yet. Lets you
   glance at "1:30 PM  -13" and know they're pre-round, vs just "-13" = playing. */
.tourney-tee {
    color:#d4af37;
    background:#1a1408;
    border:1px solid #d4af3744;
    border-radius:8px;
    padding:2px 8px;
    font-size:0.72rem;
    font-weight:600;
    font-family:'Inter','Helvetica Neue',sans-serif;
    letter-spacing:0.3px;
    white-space:nowrap;
    flex-shrink:0;
}

.divider { border:none; border-top:1px solid #1e2e1e; margin:20px 0; }
#MainMenu, header, footer { visibility:hidden; }
.stDeployButton,
.stAppDeployButton,
[data-testid="stDeployButton"],
[data-testid="stAppDeployButton"],
.viewerBadge_link__qRIco,
.viewerBadge_container__r5tak,
[data-testid="stStatusWidget"],
[data-testid="stAppViewBlockContainer"] > [data-testid="stToolbar"] { display:none !important; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# HELPERS
# ============================================================
def clean(x):
    if pd.isna(x): return ""
    return str(x).split(" +")[0].strip()

def fmt_score(val):
    if val == 0:  return "E"
    if val < 0:   return str(val)
    return f"+{val}"

def venmo_deep_link(amount=ENTRY_FEE, note="The Clubhouse"):
    return f"https://venmo.com/{VENMO_HANDLE}?txn=pay&amount={amount}&note={quote(note)}"

def render_share_block(variant="default"):
    """Compact inline 'Invite a friend' strip — small text-link row with share icons."""
    share_text = (
        f"Join The Clubhouse — ${ENTRY_FEE} weekly golf pool. "
        f"Pick 3 golfers, lowest combined score wins. {APP_URL}"
    )
    sms_href = f"sms:?&body={quote(share_text)}"
    x_href   = f"https://twitter.com/intent/tweet?text={quote(share_text)}"
    copy_js = (
        "const t=this.dataset.text;"
        "if(navigator.clipboard){navigator.clipboard.writeText(t).then(()=>{"
        "const o=this.innerText;this.innerText='✓ Copied';"
        "setTimeout(()=>{this.innerText=o;},1500);});}"
    )
    lbl = "Invite" if variant == "default" else "Share"
    st.markdown(
        f'<div class="share-inline">'
        f'<span class="lbl">{lbl}</span>'
        f'<a class="share-link" href="{sms_href}">💬 Text</a>'
        f'<span class="divider-dot">·</span>'
        f'<a class="share-link" href="{x_href}" target="_blank">𝕏 Post</a>'
        f'<span class="divider-dot">·</span>'
        f'<button class="share-link" type="button" data-text="{share_text}" onclick="{copy_js}">🔗 Copy link</button>'
        f'</div>',
        unsafe_allow_html=True
    )

def get_player_stats(email, history):
    """Look up a single player's cumulative stats by email. Returns None if no history."""
    if not email:
        return None
    email = email.lower().strip()
    tournaments = 0
    wins = 0
    best_finish = 999
    total_winnings = 0.0
    last_name = ""
    for t in history:
        for entry in t.get("entries", []):
            if (entry.get("email") or "").lower().strip() == email:
                tournaments += 1
                wins += entry.get("daily_wins", 0)
                if entry.get("overall_winner"):
                    wins += 1
                rank = entry.get("rank", 999)
                if rank < best_finish:
                    best_finish = rank
                total_winnings += float(entry.get("winnings", 0) or 0)
                last_name = entry.get("name", last_name)
    if tournaments == 0:
        return None
    # Overall rank on leaderboard
    lb = compute_leaderboard(history)
    rank_pos = None
    for i, p in enumerate(lb, 1):
        # match by display name + tournaments count as a proxy
        if p["display_name"] == last_name and p["tournaments"] == tournaments:
            rank_pos = i
            break
    return {
        "display_name": last_name,
        "tournaments": tournaments,
        "wins": wins,
        "best_finish": best_finish if best_finish < 999 else None,
        "total_winnings": total_winnings,
        "rank_pos": rank_pos,
    }

def compute_leaderboard(history):
    """Aggregate per-player stats across all archived tournaments, keyed by email."""
    players = {}
    for tourney in history:
        for entry in tourney.get("entries", []):
            email = (entry.get("email") or "").lower().strip()
            # Fall back to name if email missing
            if not email:
                email = "__noemail__:" + (entry.get("name", "unknown").lower().strip())
            if email not in players:
                players[email] = {
                    "display_name": entry.get("name", ""),
                    "tournaments": 0, "wins": 0, "best_finish": 999, "total_winnings": 0.0,
                }
            p = players[email]
            p["display_name"] = entry.get("name", p["display_name"])
            p["tournaments"] += 1
            p["wins"] += entry.get("daily_wins", 0)
            if entry.get("overall_winner"):
                p["wins"] += 1
            rank = entry.get("rank", 999)
            if rank < p["best_finish"]:
                p["best_finish"] = rank
            p["total_winnings"] += float(entry.get("winnings", 0) or 0)
    return sorted(
        players.values(),
        key=lambda p: (-p["total_winnings"], -p["wins"], p["best_finish"])
    )

def hof_wins_for(email, history):
    """Count (overall_wins, daily_wins) across history for a given email."""
    if not email:
        return (0, 0)
    e = email.lower().strip()
    ov, dw = 0, 0
    for t in history:
        for entry in t.get("entries", []):
            if (entry.get("email") or "").lower().strip() == e:
                if entry.get("overall_winner"):
                    ov += 1
                dw += int(entry.get("daily_wins", 0) or 0)
    return (ov, dw)

def hof_badge_html(email, history):
    """Render a small badge HTML snippet for a player based on their past wins."""
    ov, dw = hof_wins_for(email, history)
    if ov == 0 and dw == 0:
        return ""
    parts = []
    if ov >= 1:
        # Big crown for overall wins
        count_label = f'<span class="hof-count">×{ov}</span>' if ov > 1 else ""
        parts.append(f'<span class="hof-badge" title="Overall wins: {ov}">👑</span>{count_label}')
    if dw >= 3:
        # Only show round-win badge if they have real hardware
        parts.append(f'<span class="hof-badge" title="Round wins: {dw}">⭐</span><span class="hof-count">×{dw}</span>')
    return "".join(parts)

def position_delta_html(cur_rank, prev_rank):
    """Render a ↑/↓ delta pill based on current vs previous rank."""
    if prev_rank is None:
        return '<span class="pos-delta pos-new">NEW</span>'
    if cur_rank == prev_rank:
        return '<span class="pos-delta pos-same">—</span>'
    if cur_rank < prev_rank:
        # moved up (lower rank number = better)
        return f'<span class="pos-delta pos-up">↑{prev_rank - cur_rank}</span>'
    return f'<span class="pos-delta pos-down">↓{cur_rank - prev_rank}</span>'

def build_tournament_archive(tournament_name, df_display_local, daily_winners_dict, daily_payout_val, overall_payout_val, finished_flag):
    """Package current tournament state into an archive record."""
    from datetime import datetime
    overall_winner_name = df_display_local.iloc[0]["Name"] if (finished_flag and not df_display_local.empty) else None
    daily_win_counts = {}
    for day, winner in daily_winners_dict.items():
        if winner:
            daily_win_counts[winner] = daily_win_counts.get(winner, 0) + 1
    entries = []
    for i, row in df_display_local.iterrows():
        rank = i + 1
        name = row["Name"]
        daily_wins = daily_win_counts.get(name, 0)
        is_overall = (name == overall_winner_name) if overall_winner_name else False
        winnings = (daily_wins * daily_payout_val) + (overall_payout_val if is_overall else 0)
        entries.append({
            "name": name,
            "email": row.get("Email", "") if "Email" in df_display_local.columns else "",
            "venmo": row["Venmo"],
            "rank": rank,
            "total_score": int(row["Total"]),
            "picks": [p for p, _ in row["Picks"]],
            "daily_wins": daily_wins,
            "overall_winner": is_overall,
            "winnings": round(float(winnings), 2),
        })
    return {
        "tournament_name": tournament_name or f"Tournament {datetime.now().strftime('%Y-%m-%d')}",
        "archived_at": datetime.now().isoformat(),
        "daily_winners": dict(daily_winners_dict),
        "overall_winner": overall_winner_name,
        "entries": entries,
    }

def submit_to_google_form(name, email, venmo, pick1, pick2, pick3):
    """POST directly to the Google Form's formResponse endpoint.
    Returns (ok, detail) — ok is True/False, detail is a string with the reason on failure."""
    # Config sanity check
    if "REPLACE_WITH_YOUR_FORM_ID" in FORM_SUBMIT_URL:
        return False, "FORM_SUBMIT_URL is still a placeholder — fill it in at the top of app.py"
    for key, val in FORM_FIELD_IDS.items():
        if "XXXXXXXXX" in val or not val.startswith("entry."):
            return False, f"FORM_FIELD_IDS['{key}'] is still a placeholder — fill in all entry IDs"

    # Type / None guards — will catch the "formatted label accidentally passed in" case
    for label, v in [("name", name), ("email", email), ("venmo", venmo),
                     ("pick1", pick1), ("pick2", pick2), ("pick3", pick3)]:
        if v is None:
            return False, f"Field '{label}' is empty — form validation failed"
        if not isinstance(v, str):
            return False, f"Field '{label}' has non-string value ({type(v).__name__}): {v!r}"

    try:
        data = {
            FORM_FIELD_IDS["name"]:  name,
            FORM_FIELD_IDS["email"]: email,
            FORM_FIELD_IDS["venmo"]: venmo,
            FORM_FIELD_IDS["pick1"]: pick1,
            FORM_FIELD_IDS["pick2"]: pick2,
            FORM_FIELD_IDS["pick3"]: pick3,
        }
        r = requests.post(FORM_SUBMIT_URL, data=data, timeout=10)
        if r.status_code in (200, 302):
            return True, ""
        # On 400, Google usually means one of the pick values doesn't match a dropdown option
        # exactly, or a required field is missing. Dump the picks so we can diagnose.
        if r.status_code == 400:
            detail = (
                f"Google returned HTTP 400 (usually: a pick value doesn't match a Google Form dropdown option exactly). "
                f"Submitted picks — p1={pick1!r}  p2={pick2!r}  p3={pick3!r}. "
                f"Check that each golfer name in TIER_1/TIER_2/TIER_3 matches the dropdown option in your Google Form character-for-character (spaces, accents, punctuation)."
            )
            return False, detail
        return False, f"Google returned HTTP {r.status_code} — check your FORM_SUBMIT_URL and FORM_FIELD_IDS"
    except requests.exceptions.Timeout:
        return False, "Request timed out hitting Google Forms"
    except Exception as e:
        return False, f"Error: {type(e).__name__}: {e}"

# ============================================================
# LOAD SHEET
# ============================================================
@st.cache_data(ttl=30)
def load_sheet():
    try:
        df = pd.read_csv(SHEET_URL)
        df.columns = df.columns.str.strip()
        df = df.astype(str).apply(lambda col: col.str.strip())
        df = df.replace("nan","").replace("None","")
        df = df.dropna(how="all")
        df = df[(df["Pick 1"].str.len()>0)|(df["Pick 2"].str.len()>0)|(df["Pick 3"].str.len()>0)]
        return df
    except:
        return pd.DataFrame(columns=["Name","Venmo","Pick 1","Pick 2","Pick 3"])

df = load_sheet()

# ============================================================
# ESPN DATA
# ============================================================
@st.cache_data(ttl=30)
def _parse_tee_time_to_dt(value):
    """Parse any of ESPN's tee-time encodings into a timezone-aware UTC datetime.
    Returns None if the value doesn't look like a tee time."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    up = s.upper()
    # Reject obvious non-times
    if up in ("F", "CUT", "WD", "DQ", "DNS", "MC", "WDR", "RTD", "E"):
        return None
    if up.startswith("F-") or up.startswith("F "):
        return None
    try:
        n = int(up)
        if 0 <= n <= 18:
            return None
    except Exception:
        pass
    try:
        if s.startswith("-") or s.startswith("+"):
            int(s)
            return None
    except Exception:
        pass
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    # ISO (e.g. "2026-04-16T18:05Z")
    if "T" in s:
        try:
            iso = s.replace("Z", "+00:00")
            dt = _dt.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_tz.utc)
            return dt
        except Exception:
            pass
    # Java Date.toString() — e.g. "Thu Apr 16 13:50:00 PDT 2026"
    import re as _re
    m = _re.match(
        r"^([A-Za-z]{3})\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{1,2}):(\d{2}):(\d{2})\s+([A-Z]{2,4})\s+(\d{4})$",
        s,
    )
    if m:
        months = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
                  "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
        tz_offsets = {
            "UTC": 0, "GMT": 0,
            "EST": -5, "EDT": -4,
            "CST": -6, "CDT": -5,
            "MST": -7, "MDT": -6,
            "PST": -8, "PDT": -7,
            "HST": -10, "AKST": -9, "AKDT": -8,
        }
        try:
            mon = months[m.group(2)]
            day = int(m.group(3))
            hh, mm, ss = int(m.group(4)), int(m.group(5)), int(m.group(6))
            tzname = m.group(7)
            year = int(m.group(8))
            off = tz_offsets.get(tzname, 0)
            dt = _dt(year, mon, day, hh, mm, ss, tzinfo=_tz(_td(hours=off)))
            return dt.astimezone(_tz.utc)
        except Exception:
            pass
    return None

def _format_tee_time(value):
    """Best-effort convert an ESPN tee-time value into 'h:MM AM/PM' (Eastern).
    Accepts ISO timestamps, already-formatted clock strings, or noise.
    Returns '' if we can't confidently identify a real tee time."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    import re as _re
    # Already human-readable? e.g. "1:30 PM", "Starts 10:05 AM", "Tee: 10:05 AM"
    m = _re.search(r"(\d{1,2}:\d{2})\s*(AM|PM|am|pm)", s)
    if m:
        return f"{m.group(1)} {m.group(2).upper()}"
    # Try full parse (ISO or Java Date)
    dt = _parse_tee_time_to_dt(s)
    if dt is not None:
        from datetime import timezone as _tz, timedelta as _td
        try:
            dt = dt.astimezone(_tz(_td(hours=-4)))   # Eastern
        except Exception:
            pass
        h12 = dt.hour % 12 or 12
        ampm = "AM" if dt.hour < 12 else "PM"
        return f"{h12}:{dt.minute:02d} {ampm}"
    return ""

def _extract_tee_time(p):
    """Best-effort tee-time extraction for a player. Looks in the usual
    top-level fields plus digs into each round's statistics.categories.stats
    (ESPN buries tee times in a Java Date string like 'Thu Apr 16 13:50:00 PDT 2026').
    Returns the next UPCOMING tee time (earliest future) if possible, else the
    first parseable one. Returns '' if nothing usable is found."""
    from datetime import datetime as _dt, timezone as _tz
    try:
        status = p.get("status") or {}
        stype  = (status.get("type") or {})
        raw_candidates = [
            p.get("teeTime"),
            p.get("startTime"),
            status.get("teeTime"),
            status.get("startTime"),
            status.get("displayValue"),
            stype.get("detail"),
            stype.get("shortDetail"),
            stype.get("description"),
        ]
        # Linescore-level tee time fields + buried stats
        try:
            for row in (p.get("linescores") or []):
                if not isinstance(row, dict):
                    continue
                for key in ("teeTime", "startTime", "time"):
                    v = row.get(key)
                    if v: raw_candidates.append(v)
                # Dig into statistics.categories.stats (ESPN puts a Java-style
                # start datetime in a stat slot, e.g. "Thu Apr 16 13:50:00 PDT 2026").
                try:
                    cats = ((row.get("statistics") or {}).get("categories") or [])
                    for cat in cats:
                        for stat in (cat.get("stats") or []):
                            if isinstance(stat, dict):
                                raw_candidates.append(stat.get("displayValue"))
                                raw_candidates.append(stat.get("value"))
                except Exception:
                    continue
        except Exception:
            pass
        # Parse all candidates; only return future tee times (past ones
        # are irrelevant once a round is underway).
        now_utc = _dt.now(_tz.utc)
        futures = []
        for c in raw_candidates:
            dt = _parse_tee_time_to_dt(c)
            if dt is None:
                continue
            if dt >= now_utc:
                futures.append(dt)
        if futures:
            best = min(futures)             # earliest upcoming
            return _format_tee_time(best.isoformat())
    except Exception:
        pass
    return ""

def _collect_tee_fields(p):
    """Debug helper: return a dict of every candidate field we inspected
    for a given player, so the admin panel can show exactly what ESPN sent."""
    out = {}
    try:
        status = p.get("status") or {}
        stype  = (status.get("type") or {})
        out["status.type.state"]       = stype.get("state")
        out["status.displayValue"]     = status.get("displayValue")
        out["status.type.detail"]      = stype.get("detail")
        out["status.type.shortDetail"] = stype.get("shortDetail")
        out["status.type.description"] = stype.get("description")
        out["teeTime (top)"]           = p.get("teeTime")
        out["status.teeTime"]          = status.get("teeTime")
        out["status.startTime"]        = status.get("startTime")
        ls = p.get("linescores") or []
        for idx, row in enumerate(ls, 1):
            if isinstance(row, dict):
                for key in ("teeTime", "startTime", "time"):
                    if row.get(key) is not None:
                        out[f"linescores[{idx}].{key}"] = row.get(key)
    except Exception:
        pass
    return out

def list_upcoming_pga_tournaments():
    """Hit ESPN's PGA scoreboard endpoint with no event filter to get the
    current/upcoming tournament list. Returns a list of dicts:
    [{id, name, start, end, status}, ...] sorted by start date.
    Empty list on failure."""
    out = []
    try:
        # Bare scoreboard returns the current week's event(s) by default.
        # The PGA Tour schedule endpoint lists the full season.
        for url in (
            "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard",
            "https://site.web.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard?dates=2026",
        ):
            try:
                data = requests.get(url, timeout=10).json()
            except Exception:
                continue
            evs = data.get("events") or []
            for ev in evs:
                eid = str(ev.get("id") or "")
                if not eid:
                    continue
                name = ev.get("name") or ev.get("shortName") or "(unnamed)"
                start = (ev.get("date") or "")[:10]
                end_str = ""
                try:
                    end_str = (ev.get("competitions", [{}])[0].get("endDate", "") or "")[:10]
                except Exception:
                    pass
                status = ""
                try:
                    status = (ev.get("status") or {}).get("type", {}).get("description", "")
                except Exception:
                    status = ""
                # Dedupe (the two endpoints overlap)
                if any(o["id"] == eid for o in out):
                    continue
                out.append({
                    "id": eid, "name": name, "start": start,
                    "end": end_str or start, "status": status or "Scheduled"
                })
        out.sort(key=lambda x: x["start"])
    except Exception:
        pass
    return out

def update_tier_lists_in_source(t1, t2, t3):
    """Rewrite the TIER_1 / TIER_2 / TIER_3 blocks at the top of app.py.
    Each tier is a list of strings. Streamlit hot-reloads on save.
    Returns (success_bool, message_str).
    Defensive: requires all three blocks to be present and replaceable in one
    pass — won't write anything if the file shape doesn't match."""
    import re as _re_, os as _os_
    if not (isinstance(t1, list) and isinstance(t2, list) and isinstance(t3, list)):
        return (False, "Internal error: tiers must be lists.")
    if not t1 or not t2 or not t3:
        return (False, "All three tiers must have at least one player.")
    def _fmt(name):
        # Escape any double-quotes in golfer names (rare, but safe)
        return '    "' + str(name).replace('"', '\\"') + '",'
    def _block(varname, names):
        return varname + " = [\n" + "\n".join(_fmt(n) for n in names) + "\n]"
    try:
        _path = _os_.path.realpath(__file__)
        with open(_path, "r", encoding="utf-8") as _f:
            src = _f.read()
        # Each tier block matches: TIER_X = [   …any lines…   ]
        # We use a non-greedy match across lines to grab just that block.
        # Order matters — we replace TIER_3 first, then TIER_2, then TIER_1
        # so earlier replacements can't accidentally overlap into later ones.
        def _sub_one(s, varname, names):
            pattern = rf'^{varname}\s*=\s*\[[\s\S]*?^\]'
            new_block = _block(varname, names)
            return _re_.subn(pattern, new_block, s, count=1, flags=_re_.MULTILINE)
        new_src, n3 = _sub_one(src, "TIER_3", t3)
        new_src, n2 = _sub_one(new_src, "TIER_2", t2)
        new_src, n1 = _sub_one(new_src, "TIER_1", t1)
        if not (n1 == n2 == n3 == 1):
            return (False, f"Couldn't locate all three TIER blocks (matched: T1={n1} T2={n2} T3={n3}). Edit manually.")
        with open(_path, "w", encoding="utf-8") as _f:
            _f.write(new_src)
        return (True, f"✓ Updated TIER_1 ({len(t1)}), TIER_2 ({len(t2)}), TIER_3 ({len(t3)}) — app will hot-reload.")
    except Exception as _e:
        return (False, f"Write failed: {_e}")

def update_tournament_id_in_source(new_id):
    """Rewrite the `TOURNAMENT_ID = "…"` line at the top of app.py with a new
    value. Streamlit's file watcher will hot-reload the app on next rerun.
    Returns (success_bool, message_str).
    Defensive: only accepts digit-only IDs, and only rewrites if exactly one
    matching line is found (so it won't accidentally clobber unrelated code)."""
    import re as _re_, os as _os_
    new_id = str(new_id).strip()
    if not new_id.isdigit():
        return (False, "Tournament ID must be digits only.")
    try:
        _path = _os_.path.realpath(__file__)
        with open(_path, "r", encoding="utf-8") as _f:
            src = _f.read()
        new_src, n = _re_.subn(
            r'^TOURNAMENT_ID\s*=\s*"[^"]*"',
            f'TOURNAMENT_ID = "{new_id}"',
            src,
            count=1,
            flags=_re_.MULTILINE,
        )
        if n != 1:
            return (False, "Couldn't locate the TOURNAMENT_ID line in app.py — edit it manually.")
        with open(_path, "w", encoding="utf-8") as _f:
            _f.write(new_src)
        return (True, f"✓ TOURNAMENT_ID updated to {new_id} — app will hot-reload.")
    except Exception as _e:
        return (False, f"Write failed: {_e}")

def fetch_tournament_meta(event_id):
    """Hit ESPN's leaderboard endpoint and return (name, date_str, status, n_players)
    for a given event_id — used by admin's Tournament ID verifier so the operator
    can sanity-check that the constant in app.py points at the right tournament.
    Returns (None, None, None, 0) on failure."""
    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/golf/pga/leaderboard?event={event_id}"
        data = requests.get(url, timeout=10).json()
        ev = None
        # Schema varies — try common shapes
        if isinstance(data.get("events"), list) and data["events"]:
            ev = data["events"][0]
        elif data.get("name") or data.get("date"):
            ev = data
        if not ev:
            return (None, None, None, 0)
        name = ev.get("name") or ev.get("shortName") or "(unnamed)"
        date_raw = ev.get("date") or ""
        # ESPN dates are ISO; just take YYYY-MM-DD for display
        date_str = date_raw[:10] if date_raw else "?"
        status = ""
        try:
            status = (ev.get("status") or {}).get("type", {}).get("description", "") \
                  or (ev.get("competitions", [{}])[0].get("status") or {}).get("type", {}).get("description", "")
        except Exception:
            status = ""
        # Player count
        n_players = 0
        try:
            comps = ev.get("competitions", [{}])[0].get("competitors", [])
            n_players = len(comps)
        except Exception:
            pass
        return (name, date_str, status or "Unknown", n_players)
    except Exception:
        return (None, None, None, 0)

def _fetch_tee_times_leaderboard():
    """Secondary ESPN endpoint — the leaderboard API usually has richer per-player
    data including tee times, where the scoreboard endpoint doesn't. Returns a
    (tee_times_dict, raw_players_list) tuple. Both empty on failure."""
    try:
        url  = f"https://site.api.espn.com/apis/site/v2/sports/golf/pga/leaderboard?event={TOURNAMENT_ID}"
        data = requests.get(url, timeout=10).json()
        comps = []
        # Try several paths — ESPN's response schema varies
        try:    comps = data["events"][0]["competitions"][0]["competitors"]
        except: pass
        if not comps:
            try:    comps = data["competitions"][0]["competitors"]
            except: pass
        if not comps:
            try:    comps = data["competitors"]
            except: pass
        tt, raw_players = {}, []
        for p in comps:
            try:
                name = p["athlete"]["displayName"]
                raw_players.append(p)
                fmt = _extract_tee_time(p)
                if fmt:
                    tt[name] = fmt
            except Exception:
                continue
        return tt, raw_players
    except Exception:
        return {}, []

def _is_cut(p):
    """Detect if a player has missed the cut / withdrawn / been DQ'd based on ESPN status fields.
    Returns True for MC/CUT/WD/DQ. Returns False for 'Made Cut' and anything else."""
    try:
        status = p.get("status", {}) or {}
        candidates = []
        # Common locations for status text
        candidates.append(str(status.get("displayValue", "") or ""))
        t = status.get("type", {}) or {}
        candidates.append(str(t.get("description", "") or ""))
        candidates.append(str(t.get("shortDetail", "") or ""))
        candidates.append(str(t.get("detail", "") or ""))
        candidates.append(str(t.get("name", "") or ""))
        for c in candidates:
            cl = c.strip().lower()
            if not cl:
                continue
            # Explicit cut/withdraw/DQ signals — but NOT "made cut"
            if "made cut" in cl:
                continue
            if cl in ("mc", "cut", "wd", "dq"):
                return True
            if "missed cut" in cl or "withdrew" in cl or "withdrawn" in cl:
                return True
            if "disqualified" in cl:
                return True
    except Exception:
        pass
    return False

def get_scores():
    try:
        url  = f"https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard?tournamentId={TOURNAMENT_ID}"
        data = requests.get(url, timeout=10).json()
        players = data["events"][0]["competitions"][0]["competitors"]
        score_map, leaderboard, tee_times, tee_debug, cut_set = {}, [], {}, {}, set()
        for p in players:
            name = p["athlete"]["displayName"]
            raw  = p.get("score","E")
            leaderboard.append((name, raw))
            try:   val = 0 if str(raw) in ("E","") else int(raw)
            except: val = 0
            score_map[name] = val
            tt = _extract_tee_time(p)
            if tt:
                tee_times[name] = tt
            # Keep raw tee-time-relevant fields for admin debugging
            tee_debug[name] = _collect_tee_fields(p)
            # Cut detection
            if _is_cut(p):
                cut_set.add(name)
        # Fallback — try the leaderboard endpoint for any missing tee times
        lb_tt, lb_players = _fetch_tee_times_leaderboard()
        for n, v in lb_tt.items():
            if n not in tee_times:
                tee_times[n] = v
        # Merge tee debug data from leaderboard endpoint + pick up cut status
        # from lb endpoint in case scoreboard endpoint didn't have it
        for lp in lb_players:
            try:
                n = lp["athlete"]["displayName"]
                existing = tee_debug.get(n, {}) or {}
                extras = _collect_tee_fields(lp)
                # Prefix leaderboard fields so we know which endpoint they came from
                for k, v in extras.items():
                    existing[f"[lb] {k}"] = v
                tee_debug[n] = existing
                if _is_cut(lp):
                    cut_set.add(n)
            except Exception:
                continue
        # Also keep the first leaderboard-endpoint raw player around so admin
        # can inspect the full JSON if needed
        first_raw = lb_players[0] if lb_players else (players[0] if players else {})
        return score_map, leaderboard, data, tee_times, tee_debug, first_raw, cut_set
    except:
        return {}, [], {}, {}, {}, {}, set()

score_map, espn_lb, raw_data, tee_times, tee_debug, first_raw_player, cut_set = get_scores()

# Apply admin score overrides on top of ESPN data
for player, override_val in admin["score_overrides"].items():
    score_map[player] = override_val

def espn_finished(data):
    try:   return data["events"][0]["status"]["type"]["state"] == "post"
    except: return False

is_finished = admin["tournament_finished"] or espn_finished(raw_data)

# ---------------------------------------------------------------
# Per-round (daily) data for Biggest Mover
# ---------------------------------------------------------------
def extract_round_data(data, manual_par=0):
    """Returns (rounds_vs_par, current_period, course_par, state, raw_linescores).
    rounds_vs_par = {golfer_name: {1: round1_vs_par, 2: ..., 3: ..., 4: ...}}
    Only rounds with a *plausible* posted stroke count are included.
    A round N is 'final' when current_period > N or state == 'post'."""
    rounds_vs_par = {}
    raw_linescores = {}   # for debug panel
    current_period = 0
    course_par = manual_par if manual_par and manual_par > 0 else 72
    auto_par_found = False
    state = ""
    try:
        comp = data["events"][0]["competitions"][0]
        # Auto-detect course par (only if admin hasn't overridden)
        if not manual_par:
            for path in (("course","totalPar"), ("course","par"), ("par",)):
                try:
                    node = comp
                    for k in path:
                        node = node[k]
                    candidate = int(node)
                    # Sanity: par for 18 holes is typically 68-73
                    if 66 <= candidate <= 75:
                        course_par = candidate
                        auto_par_found = True
                        break
                except Exception:
                    continue
        # Current round
        try:   current_period = int(comp["status"]["period"])
        except: pass
        try:   state = comp["status"]["type"]["state"]
        except: pass
        # Per-golfer linescores
        for p in comp["competitors"]:
            try:    name = p["athlete"]["displayName"]
            except: continue
            ls = p.get("linescores", [])
            raw_linescores[name] = ls
            rd = {}
            for idx, row in enumerate(ls, 1):
                try:
                    val = row.get("value")
                    if val is None:
                        continue
                    v = int(val)
                    # ESPN sometimes gives vs-par directly, sometimes raw strokes,
                    # and sometimes 0 as a placeholder for an unfinished/unplayed round.
                    # A real vs-par of 0 (even par) is indistinguishable from a placeholder
                    # unless we know the round finished — so be defensive.
                    #   - Treat 50-100 as strokes (normal golf round)
                    #   - Treat non-zero -15..15 as vs-par
                    #   - Ignore 0 for rounds that ARE NOT clearly completed
                    #   - A round is "completed" if state == "post" or idx < current_period
                    round_completed = (state == "post") or (current_period and idx < current_period)
                    if 50 <= v <= 100:
                        rd[idx] = v - course_par   # strokes → subtract par
                    elif -15 <= v <= 15 and v != 0:
                        rd[idx] = v                # already vs-par
                    elif v == 0 and round_completed:
                        rd[idx] = 0                # actual even-par score for a completed round
                    # else: 0 for an in-progress/unplayed round, or garbage — skip
                except Exception:
                    continue
            if rd:
                rounds_vs_par[name] = rd
    except Exception:
        pass
    return rounds_vs_par, current_period, course_par, state, raw_linescores, auto_par_found

rounds_vs_par, current_period, course_par, espn_state, raw_linescores, auto_par_found = \
    extract_round_data(raw_data, manual_par=admin.get("course_par", 0))
ROUND_TO_DAY = {1: "Thursday", 2: "Friday", 3: "Saturday", 4: "Sunday"}

# ============================================================
# BUILD POOL ROWS
# ============================================================
# Apply cutoff time: hide entries submitted before the cutoff (previous tournament's entries)
cutoff_str = admin.get("entry_cutoff_time", "")
if cutoff_str and "Timestamp" in df.columns:
    try:
        df["__ts"] = pd.to_datetime(df["Timestamp"], errors="coerce")
        cutoff_dt = pd.to_datetime(cutoff_str)
        df = df[df["__ts"].isna() | (df["__ts"] >= cutoff_dt)]
    except Exception:
        pass

# Apply disqualification list (hide entries flagged by admin)
dq_set = set(admin.get("disqualified", []))
paid_map = admin.get("paid_entries", {}) or {}
rows = []
for _, row in df.iterrows():
    venmo_val = row.get("Venmo", "") if hasattr(row, "get") else row["Venmo"]
    ts_val    = str(row.get("Timestamp", "")) if "Timestamp" in df.columns else ""
    entry_key = f"{venmo_val}|{ts_val}"
    if venmo_val in dq_set or entry_key in dq_set:
        continue

    picks  = [clean(row["Pick 1"]), clean(row["Pick 2"]), clean(row["Pick 3"])]
    scores = [score_map.get(p, 0) for p in picks]
    total  = sum(scores)
    best   = scores.index(min(scores))
    email  = row["Email"] if "Email" in df.columns else ""
    paid   = bool(paid_map.get(entry_key, False))
    rows.append({"Name":row["Name"],"Email":email,"Venmo":row["Venmo"],"Timestamp":ts_val,
                 "Picks":list(zip(picks,scores)),"Total":total,"BestIndex":best,
                 "EntryKey":entry_key,"Paid":paid})

df_display = pd.DataFrame(rows).sort_values("Total").reset_index(drop=True) if rows else pd.DataFrame()

# ── Private-league filter ──
# When a league code is active (?league=CODE), scope the leaderboard + pot to
# only that league's members. The PUBLIC pool view keeps everyone visible but
# excludes league-only members so it feels like a real cross-section of "the
# default pool." Admins always see everyone (scoped filter doesn't run in the
# admin panel — that's further down the file).
_rows_unscoped = list(rows)   # full unfiltered list, used where we need totals across pool
if current_league_code:
    _lg_emails = _league_emails(current_league_code)
    rows = [r for r in rows if (r.get("Email") or "").lower().strip() in _lg_emails]
    df_display = (
        pd.DataFrame(rows).sort_values("Total").reset_index(drop=True)
        if rows else pd.DataFrame()
    )

# Pot counts only paid entries; pending entries are displayed but not included in the pot
paid_count    = sum(1 for r in rows if r.get("Paid"))
pending_count = len(rows) - paid_count
pot            = paid_count * ENTRY_FEE_ACTIVE
daily_payout   = round(pot * DAILY_PCT,   2)
overall_payout = round(pot * OVERALL_PCT, 2)

# ---------------------------------------------------------------
# Per-round delta scoring:
#   Round winner for Round N = lowest 3-pick combined DELTA for round N only.
#   (Friday's score = sum of each pick's Round-2-only vs-par, NOT cumulative.)
#
#   Implementation: compute cumulative_through_R_N  -  cumulative_through_R_(N-1).
#   That way we're immune to whether ESPN sends strokes or vs-par per round —
#   we just diff two reliable cumulative snapshots.
# ---------------------------------------------------------------
def cumulative_vs_par(name, round_num, rounds_data, score_map_local, period, state):
    """Cumulative vs-par through round_num. None if unknown.

    ESPN's score_map (each golfer's current overall vs-par) is the single
    authoritative source for a player's cumulative position in the tournament —
    it reflects live play, admin overrides, and final results. Linescores are
    per-round rows that can be noisy/incomplete (0 placeholders for unfinished
    rounds, missing rounds for cut players, etc.).

    Strategy:
      - If round_num matches the LATEST round we have data for (the live/final
        round), use score_map. That gives us the correct answer for the live
        cumulative, and for the final cumulative post-tournament.
      - Otherwise (earlier historical round), sum up rounds_data[1..round_num].
    """
    if round_num <= 0:
        return 0
    tournament_done = (state == "post")

    # Latest round that score_map reflects cumulative-through.
    # Post-tournament: the last round (use period if sane, default 4).
    # In progress: whatever round is currently being played.
    if tournament_done:
        latest = period if (period and 1 <= period <= 4) else 4
    else:
        latest = period if period else 0

    # Future round that hasn't started yet
    if not tournament_done and latest > 0 and round_num > latest:
        return None

    # Use authoritative score_map for the latest round
    if latest > 0 and round_num == latest:
        sm = score_map_local.get(name)
        if sm is not None:
            return sm
        # Fall through to linescores if score_map missing for this player

    # Historical round: sum from linescores
    rounds = rounds_data.get(name, {})
    if any(r not in rounds for r in range(1, round_num + 1)):
        return None
    return sum(rounds[r] for r in range(1, round_num + 1))

def round_delta_vs_par(name, round_num, rounds_data, score_map_local, period, state):
    """Score for round_num alone (the 'daily' delta)."""
    cum_n = cumulative_vs_par(name, round_num, rounds_data, score_map_local, period, state)
    if cum_n is None:
        return None
    if round_num == 1:
        return cum_n
    cum_prev = cumulative_vs_par(name, round_num - 1, rounds_data, score_map_local, period, state)
    if cum_prev is None:
        return None
    return cum_n - cum_prev

def compute_daily_movers(rows_local, rounds_data, score_map_local, period, state):
    out = {}
    for rnum, day in ROUND_TO_DAY.items():
        candidates = []
        for r in rows_local:
            pick_names = [p[0] for p in r["Picks"]]
            vals = []
            for pn in pick_names:
                v = round_delta_vs_par(pn, rnum, rounds_data, score_map_local, period, state)
                if v is not None:
                    vals.append(v)
            if len(vals) == 3:
                candidates.append((r["Name"], sum(vals)))
        if not candidates:
            continue
        candidates.sort(key=lambda x: x[1])
        low = candidates[0][1]
        winners = [c for c in candidates if c[1] == low]
        is_final = (state == "post") or (period > rnum)
        out[day] = {
            "name":  " / ".join(w[0] for w in winners),
            "score": low,
            "final": is_final,
            "tied":  len(winners) > 1,
        }
    return out

daily_movers = compute_daily_movers(rows, rounds_vs_par, score_map, current_period, espn_state)

# ============================================================
# TEE-TIME COUNTDOWN STRIP
# ============================================================
_tee_iso = admin.get("tournament_start", "")
if _tee_iso:
    try:
        from datetime import datetime as _dtc
        _tee_dt = _dtc.fromisoformat(_tee_iso)
        _now    = _dtc.now()
        _delta  = (_tee_dt - _now).total_seconds()
        if _delta > 0:
            # Count down
            days = int(_delta // 86400)
            hrs  = int((_delta % 86400) // 3600)
            mins = int((_delta % 3600) // 60)
            if days >= 1:
                time_str = f"{days}d {hrs}h {mins}m"
            else:
                time_str = f"{hrs}h {mins}m"
            strip_cls = "tee-strip urgent" if _delta < 6 * 3600 else "tee-strip"
            st.markdown(
                f'<div class="{strip_cls}">'
                f'<span class="tee-label">First Tee</span>'
                f'<span class="tee-count">⛳ {time_str}</span>'
                f'<span class="tee-label">until picks lock</span>'
                f'</div>',
                unsafe_allow_html=True
            )
        elif _delta > -4 * 86400:
            # Tournament in progress (within 4 days of start)
            st.markdown(
                '<div class="tee-strip live">'
                '<span class="tee-label">Status</span>'
                '<span class="tee-count">🔴 Live — tournament in progress</span>'
                '</div>',
                unsafe_allow_html=True
            )
    except Exception:
        pass

# ============================================================
# LEAGUE BANNER  (shown when ?league=CODE points to a real league)
# ============================================================
if current_league:
    _lg_name   = current_league.get("name", "Private League")
    _lg_fee    = _league_entry_fee(current_league_code)
    _lg_count  = len(_league_emails(current_league_code))
    _member_label = "member" if _lg_count == 1 else "members"
    st.markdown(
        f'<div class="league-banner">'
        f'  <div class="lb-left">'
        f'    <div class="lb-eyebrow">🔒 Private League</div>'
        f'    <div class="lb-name">{_lg_name}</div>'
        f'    <div class="lb-meta">'
        f'      <span>{_lg_count} {_member_label}</span>'
        f'      <span class="lb-dot">·</span>'
        f'      <span>${_lg_fee} to enter</span>'
        f'      <span class="lb-dot">·</span>'
        f'      <a class="league-return-link" href="?" target="_self">View public pool</a>'
        f'    </div>'
        f'  </div>'
        f'  <div class="lb-code-box">{current_league_code}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
elif _league_code_attempted:
    # User visited with a bogus code — show a soft "not found" notice and
    # continue rendering the public pool below.
    st.markdown(
        f'<div class="league-not-found">'
        f'  League code <strong>{_league_code_attempted}</strong> not found. '
        f'Showing the public pool instead. '
        f'<a class="league-return-link" href="?" target="_self">Dismiss</a>'
        f'</div>',
        unsafe_allow_html=True,
    )

# ============================================================
# HEADER
# ============================================================
col_title, col_stats = st.columns([2, 1])

with col_title:
    # Wrap the hero-left column in a keyed container so CSS can collapse
    # the default Streamlit gaps between the title and the Join Pool button.
    try:
        _hero_left = st.container(key="hero_left")
    except TypeError:
        _hero_left = st.container()

with _hero_left:
    # Hero copy is intentionally minimal: just the brand, the tournament,
    # and a single one-line value prop (the round-winners hook). The Join
    # Pool button below carries the entry fee, so we don't repeat it here.
    # The .title-inner wrapper shrink-wraps to the title's width so the
    # subtitle + pitch center UNDER the title text, not across the column.
    _tourney_name = (admin.get("tournament_name", "") or "").strip()
    _subtitle_html = (
        f'<div class="main-subtitle">{_tourney_name}</div>' if _tourney_name else ""
    )
    st.markdown(
        '<div class="title-block">'
        '<div class="title-inner">'
        '<div class="main-title">⛳ The Clubhouse Pool</div>'
        f'{_subtitle_html}'
        f'<div class="main-pitch">Pick 3 golfers · <strong class="mp-hook">multiple round winners</strong></div>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    if admin["entries_frozen"]:
        st.markdown("""
        <div style="display:inline-block; background:#1a0a0a; border:1px solid #5a2a2a;
            color:#f87171; padding:10px 22px; border-radius:8px; font-weight:600;
            font-size:0.85rem; letter-spacing:1px; text-transform:uppercase;">
            🔒 Entries Closed
        </div>""", unsafe_allow_html=True)
    else:
        # Toggle for inline entry form
        if "entry_mode" not in st.session_state:
            st.session_state.entry_mode = False
        if "entry_submitted" not in st.session_state:
            st.session_state.entry_submitted = False
        if "entry_submitted_name" not in st.session_state:
            st.session_state.entry_submitted_name = ""
        if "entry_submitted_email" not in st.session_state:
            st.session_state.entry_submitted_email = ""

        if not st.session_state.entry_mode and not st.session_state.entry_submitted:
            st.markdown('<div class="join-pool-marker"></div>', unsafe_allow_html=True)
            _cta_label = (
                f"Join {current_league.get('name','League')}  ·  ${ENTRY_FEE_ACTIVE}"
                if current_league else
                f"Join Pool  ·  ${ENTRY_FEE_ACTIVE}"
            )
            if st.button(_cta_label, key="open_entry", use_container_width=True):
                st.session_state.entry_mode = True
                st.rerun()
            # Invite-a-friend share block under the CTA
            render_share_block(variant="default")

            # League CTAs (Create / Join-by-code) intentionally live OUTSIDE
            # the hero column, grouped as sibling expanders below — that way
            # they render at the same width with the same visual pattern,
            # instead of a mismatched button-in-hero + expander-below layout.

            # Dynamically match the Join Pool button's width to the main title
            # so its right edge lands exactly where "Pool" ends.
            components.html("""
<script>
(function() {
  function align() {
    try {
      var doc = window.parent.document;
      var title = doc.querySelector('.main-title');
      if (!title) return;
      var w = Math.round(title.getBoundingClientRect().width);
      if (w < 100) return;
      var targets = [
        doc.querySelector('.st-key-open_entry'),
        doc.querySelector('.st-key-open_entry > div'),
        doc.querySelector('.st-key-open_entry button'),
      ];
      targets.forEach(function(el) {
        if (el) {
          el.style.setProperty('max-width', w + 'px', 'important');
          el.style.setProperty('width', w + 'px', 'important');
        }
      });
    } catch (e) {}
  }
  align();
  [50,150,400,900,1800].forEach(function(ms){ setTimeout(align, ms); });
  try { window.parent.addEventListener('resize', align); } catch (e) {}
  try {
    var mo = new MutationObserver(function(){ align(); });
    mo.observe(window.parent.document.body, { childList:true, subtree:true, attributes:false });
  } catch (e) {}
})();
</script>
            """, height=0)

with col_stats:
    entries_sub = ""
    if pending_count > 0 and paid_count > 0:
        entries_sub = f'<div class="stat-sub">{paid_count} paid · {pending_count} pending</div>'
    elif pending_count > 0 and paid_count == 0:
        entries_sub = '<div class="stat-sub">all pending</div>'
    # Flush-left HTML — indented f-strings inside st.markdown get misread as
    # markdown code blocks, which can leak stray </div> tags onto the page.
    _stats_html = (
        '<div style="display:flex; gap:10px; margin-top:8px;">'
        '<div class="stat-box" style="flex:1;">'
        f'<div class="stat-value">${pot}</div>'
        '<div class="stat-label">Prize Pot</div>'
        '</div>'
        '<div class="stat-box" style="flex:1;">'
        f'<div class="stat-value">{len(rows)}</div>'
        '<div class="stat-label">Entries</div>'
        f'{entries_sub}'
        '</div>'
        '</div>'
    )
    st.markdown(_stats_html, unsafe_allow_html=True)

    # Inline Rules dropdown — native expander, no page reload.
    # Wrapped in a keyed container so CSS (.st-key-rules_container) can align it
    # exactly with the Prize Pot / Entries row above.
    try:
        _rules_ctx = st.container(key="rules_container")
    except TypeError:
        # Older Streamlit (<1.36) doesn't support key= on container
        _rules_ctx = st.container()
    with _rules_ctx:
        with st.expander("📖  How It Works", expanded=False):
            st.markdown(f"""
<div style="color:#d8e0d8; font-size:0.88rem; line-height:1.55;">

<strong style="color:#fff;">The Basics</strong><br>
• <strong>${ENTRY_FEE_ACTIVE}</strong> to enter. Venmo <code>@{VENMO_HANDLE}</code> — not in until payment hits.<br>
• Pick <strong>3 golfers</strong>: one Favorite, one Contender, one Longshot.<br>
• Your <strong>score = sum of all 3 picks</strong> vs par. Low score wins.<br>

<br><strong style="color:#fff;">Payouts</strong><br>
• <strong>Round winner</strong> (lowest 3-pick total that round): <strong>{int(DAILY_PCT*100)}% of pot</strong> × 4 rounds (Thu / Fri / Sat / Sun).<br>
• <strong>Overall winner</strong> (lowest total after Sunday): <strong>{int(OVERALL_PCT*100)}% of pot</strong>.<br>
• Ties split evenly.<br>

<br><strong style="color:#fff;">The Cut Rule</strong><br>
If one of your picks gets cut, they get the <strong>cut score</strong> applied for both Saturday <em>and</em> Sunday. You're not out — but you're carrying dead weight.<br>

<br><strong style="color:#fff;">Schedule</strong><br>
• Entries open <strong>Monday night</strong> through <strong>Thursday tee-off</strong>.<br>
• Picks lock when the first group tees off Thursday.<br>
• Winners posted each round; overall payouts go out Sunday night.<br>

<br><strong style="color:#fff;">Withdrawals</strong><br>
If a pick WDs before the tournament starts, reach out — we'll swap. Once it starts, no subs.<br>

</div>
""", unsafe_allow_html=True)

# ============================================================
# INLINE ENTRY FORM
# ============================================================
if not admin["entries_frozen"]:
    # Success state (after submit)
    if st.session_state.get("entry_submitted"):
        submitted_name = st.session_state.entry_submitted_name or "You"
        submitted_email = st.session_state.get("entry_submitted_email", "")
        vlink = venmo_deep_link(ENTRY_FEE_ACTIVE, "The Clubhouse")

        # Look up this player's past history by email.
        # IMPORTANT: every HTML f-string below must be flush-left / single-line —
        # Streamlit's markdown parser treats 4+ space indents as code blocks.
        stats = get_player_stats(submitted_email, admin.get("history", []))
        if stats:
            best = f"{stats['best_finish']}" if stats['best_finish'] else "—"
            suffix = "st" if best == "1" else "nd" if best == "2" else "rd" if best == "3" else "th"
            rank_line = f' · Rank <strong>#{stats["rank_pos"]}</strong>' if stats.get("rank_pos") else ""
            profile_html = (
                f'<div class="profile-block">'
                f'<div class="profile-label">Your Clubhouse history{rank_line}</div>'
                f'<div class="profile-stats">'
                f'<div class="profile-stat"><div class="profile-stat-val">{stats["tournaments"]}</div><div class="profile-stat-label">Pools</div></div>'
                f'<div class="profile-stat"><div class="profile-stat-val">{stats["wins"]}</div><div class="profile-stat-label">Wins</div></div>'
                f'<div class="profile-stat"><div class="profile-stat-val">{best}{suffix if best != "—" else ""}</div><div class="profile-stat-label">Best</div></div>'
                f'<div class="profile-stat"><div class="profile-stat-val">${stats["total_winnings"]:.0f}</div><div class="profile-stat-label">Won</div></div>'
                f'</div>'
                f'</div>'
            )
        else:
            profile_html = (
                '<div class="profile-block">'
                '<div class="profile-newbie">🎉 <strong>Welcome to The Clubhouse!</strong> Your rank appears on the Hall of Fame once this tournament wraps.</div>'
                '</div>'
            )

        success_html = (
            f'<div class="success-card">'
            f'<div class="success-title">✅ Picks locked in, {submitted_name}</div>'
            f'<div class="success-sub">Tap below to send ${ENTRY_FEE} via Venmo. Your entry isn\'t final until payment hits.</div>'
            f'{profile_html}'
            f'<a href="{vlink}" target="_blank" class="venmo-cta">Pay ${ENTRY_FEE} via Venmo</a>'
            f'</div>'
        )
        st.markdown(success_html, unsafe_allow_html=True)

        # Shareable brag card — visual picks-lineup that users can screenshot
        _picks_submitted = st.session_state.get("entry_submitted_picks", [])
        _fullname = st.session_state.get("entry_submitted_fullname", submitted_name)
        if len(_picks_submitted) == 3:
            _tier_labels = ["Favorite", "Contender", "Longshot"]
            picks_rows = ""
            for _tier, _pick in zip(_tier_labels, _picks_submitted):
                picks_rows += f'<div class="brag-pick"><span>{_pick}</span><span class="tier">{_tier}</span></div>'
            brag_html = (
                f'<div class="brag-card">'
                f'<div class="brag-badge">⛳ The Clubhouse</div>'
                f'<div class="brag-header">{_fullname}\'s Picks</div>'
                f'<div class="brag-sub">Locked in · ${ENTRY_FEE} entry</div>'
                f'<div class="brag-picks">{picks_rows}</div>'
                f'<div class="brag-footer">Low combined score wins · <strong>{APP_URL.replace("https://","")}</strong></div>'
                f'</div>'
            )
            st.markdown(brag_html, unsafe_allow_html=True)
            st.caption("📸 Screenshot this card and share it to your group chat — start the trash talk.")

        # Come-back hook — builds anticipation so they return for each round
        st.markdown(
            '<div style="background:linear-gradient(135deg,#1a2f1a 0%,#0f1f0f 100%);'
            'border:1px solid #2d5a3d;border-radius:10px;padding:14px 16px;'
            'margin:14px 0 10px 0;color:#c7e3c7;font-size:0.95rem;line-height:1.55;">'
            '🏆 <strong style="color:#fff;">Check back each night</strong> · '
            'A new round winner gets paid Thu / Fri / Sat / Sun · '
            'plus the overall champ Sunday.'
            '</div>',
            unsafe_allow_html=True,
        )

        # Post-entry share — stoke is highest right after someone submits
        render_share_block(variant="compact")

        c1, c2 = st.columns([1, 6])
        with c1:
            if st.button("Enter another", key="reset_entry"):
                st.session_state.entry_submitted = False
                st.session_state.entry_mode = True
                st.rerun()

    # Entry form state
    elif st.session_state.get("entry_mode"):
        st.markdown('<div class="entry-form-wrap">', unsafe_allow_html=True)
        st.markdown('<div class="entry-form-title">Pick 3 Golfers</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="entry-form-sub">One from each tier — ${ENTRY_FEE} entry</div>', unsafe_allow_html=True)

        # ---- Returning user lookup ----
        with st.expander("👋 Returning? Auto-fill from your last entry", expanded=False):
            lookup_email = st.text_input("Email you used before", key="lookup_email", placeholder="you@example.com")
            if st.button("Find my info", key="btn_lookup") and lookup_email.strip():
                target = lookup_email.strip().lower()
                matched = None
                # Most recent entry in current sheet wins; fallback to history.
                # Use safe_str() because pandas can hand us float('nan') for blank
                # cells, and NaN is truthy so `or ""` wouldn't catch it.
                def _safe_lower(v):
                    try:
                        if v is None: return ""
                        # Catch NaN (which != itself)
                        if isinstance(v, float) and v != v: return ""
                        return str(v).strip().lower()
                    except Exception:
                        return ""
                for r in rows:
                    if _safe_lower(r.get("Email")) == target:
                        matched = {"name": r.get("Name","") or "", "venmo": r.get("Venmo","") or "", "email": target}
                if matched is None:
                    for t in reversed(admin.get("history", [])):
                        for e in t.get("entries", []):
                            if _safe_lower(e.get("email")) == target:
                                matched = {"name": e.get("name","") or "", "venmo": e.get("venmo","") or "", "email": target}
                                break
                        if matched: break
                if matched:
                    st.session_state.prefill_name  = matched["name"]
                    st.session_state.prefill_venmo = matched["venmo"]
                    st.session_state.prefill_email = matched["email"]
                    st.success(f"Welcome back, {matched['name']}! Fields below are pre-filled.")
                    st.rerun()
                else:
                    st.warning("No match found — fill in manually below.")

        # ---- Pick popularity counts (this week) ----
        pick_counts = {}
        for r in rows:
            for pname, _ in r["Picks"]:
                pick_counts[pname] = pick_counts.get(pname, 0) + 1
        total_entries = max(len(rows), 1)
        def label_with_pct(g):
            n = pick_counts.get(g, 0)
            if n == 0 or total_entries == 0:
                return g
            pct = round(100 * n / total_entries)
            return f"{g}  ·  {pct}% picked"

        # If we have prefill values from the "Returning?" lookup, seed session_state *before*
        # the widget is created — passing both value= and key= on st.text_input inside a form
        # can silently strand values.
        for _prefill_key, _widget_key in [("prefill_name","in_name"),
                                          ("prefill_email","in_email"),
                                          ("prefill_venmo","in_venmo")]:
            if _widget_key not in st.session_state and st.session_state.get(_prefill_key):
                st.session_state[_widget_key] = st.session_state[_prefill_key]

        with st.form("entry_form", clear_on_submit=False):
            cA, cB = st.columns(2)
            with cA:
                name_in  = st.text_input("Your name", key="in_name",
                                         placeholder="First Last")
            with cB:
                email_in = st.text_input("Email", key="in_email",
                                         placeholder="you@example.com")

            venmo_in = st.text_input("Venmo handle", key="in_venmo",
                                     placeholder="yourhandle (no @)")

            st.markdown("**Tier 1 — Favorites**")
            p1 = st.selectbox("Pick 1", TIER_1, index=None, label_visibility="collapsed",
                              key="in_p1", format_func=label_with_pct,
                              placeholder="Search or pick a favorite…")

            st.markdown("**Tier 2 — Contenders**")
            p2 = st.selectbox("Pick 2", TIER_2, index=None, label_visibility="collapsed",
                              key="in_p2", format_func=label_with_pct,
                              placeholder="Search or pick a contender…")

            st.markdown("**Tier 3 — Longshots**")
            p3 = st.selectbox("Pick 3", TIER_3, index=None, label_visibility="collapsed",
                              key="in_p3", format_func=label_with_pct,
                              placeholder="Search or pick a longshot…")

            sub_col, cancel_col = st.columns([2, 1])
            with sub_col:
                submit = st.form_submit_button(f"Submit & Pay ${ENTRY_FEE_ACTIVE} via Venmo", use_container_width=True)
            with cancel_col:
                cancel = st.form_submit_button("Cancel", use_container_width=True)

            if cancel:
                st.session_state.entry_mode = False
                st.rerun()

            if submit:
                errors = []
                if not name_in or not name_in.strip():   errors.append("Name is required.")
                if not email_in or not email_in.strip(): errors.append("Email is required.")
                elif "@" not in email_in or "." not in email_in.split("@")[-1]:
                    errors.append("Please enter a valid email address.")
                if not venmo_in or not venmo_in.strip(): errors.append("Venmo handle is required.")
                if not p1: errors.append("Pick 1 (Tier 1) is required.")
                if not p2: errors.append("Pick 2 (Tier 2) is required.")
                if not p3: errors.append("Pick 3 (Tier 3) is required.")

                if errors:
                    for e in errors:
                        st.error(e)
                else:
                    venmo_clean = venmo_in.strip().lstrip("@")
                    email_clean = email_in.strip()
                    ok, detail = submit_to_google_form(name_in.strip(), email_clean, venmo_clean, p1, p2, p3)
                    if ok:
                        st.session_state.entry_submitted = True
                        st.session_state.entry_submitted_name = name_in.strip().split()[0]
                        st.session_state.entry_submitted_fullname = name_in.strip()
                        st.session_state.entry_submitted_email = email_clean.lower()
                        st.session_state.entry_submitted_picks = [p1, p2, p3]
                        st.session_state.entry_mode = False
                        # If they submitted from inside a private-league view,
                        # auto-enroll them in that league (email-based membership).
                        if current_league_code:
                            _join_league(email_clean, current_league_code)
                        # Invalidate the sheet cache so new entry shows up
                        load_sheet.clear()
                        st.rerun()
                    else:
                        st.error(f"Submission failed — {detail}")

        st.markdown('</div>', unsafe_allow_html=True)

# ============================================================
# LEAGUES  —  Create + Join-by-code, rendered as twin expanders so the
# two CTAs look identical instead of a button+dropdown mismatch.
# Leagues are a key viral hook — seeing friends create them drives more
# invites — so they're always visible on the public pool view.
# ============================================================
if not current_league and not admin.get("entries_frozen"):
    with st.expander("🏆  Start a private league with your friends", expanded=False):
        st.markdown(
            "<div style='color:#a7c9a7; font-size:0.88rem; line-height:1.5; margin-bottom:8px;'>"
            "Run your own mini-pool inside the Clubhouse. You set the entry fee, "
            "invite your group via a shareable link, and the leaderboard filters "
            "to just your crew."
            "</div>",
            unsafe_allow_html=True,
        )

        _cl_c1, _cl_c2 = st.columns([3, 1])
        with _cl_c1:
            _cl_name = st.text_input(
                "League name",
                key="create_league_name",
                placeholder="e.g. Sunday Squad, The 19th Hole, Backyard Bros",
                max_chars=40,
            )
        with _cl_c2:
            _cl_fee = st.number_input(
                "Entry fee ($)",
                key="create_league_fee",
                min_value=1, max_value=500, value=10, step=1,
            )

        _cl_email = st.text_input(
            "Your email (league commissioner)",
            key="create_league_email",
            placeholder="you@example.com",
            help="We use this to mark you as the league's creator.",
        )

        _cl_custom_code = st.text_input(
            "Custom code (optional)",
            key="create_league_custom_code",
            placeholder="e.g. TIGER, DADSPOOL, SQUAD26",
            max_chars=12,
            help="Make it memorable so friends can join by typing the code. "
                 "3-12 letters/numbers. Leave blank for an auto-generated code.",
        )

        _cl_submit = st.button(
            "Create League",
            key="btn_create_league",
            type="primary",
            use_container_width=True,
        )

        if _cl_submit:
            _errs = []
            _nm = (_cl_name or "").strip()
            _em = (_cl_email or "").strip().lower()
            if not _nm:
                _errs.append("League name is required.")
            if not _em or "@" not in _em or "." not in _em.split("@")[-1]:
                _errs.append("A valid email is required.")

            # Validate optional vanity code BEFORE we mint anything
            _existing = set((admin.get("leagues") or {}).keys())
            _typed_code = _cl_custom_code or ""
            _vanity_code, _vanity_err = _validate_vanity_code(_typed_code, _existing)
            if _vanity_err:
                _errs.append(_vanity_err)

            if _errs:
                for _e in _errs:
                    st.error(_e)
            else:
                # Use the vanity code if one was supplied, else auto-mint
                if _vanity_code:
                    _new_code = _vanity_code
                else:
                    _new_code = _generate_league_code(_existing)

                # Persist the league
                from datetime import datetime as _dt_lg
                admin.setdefault("leagues", {})[_new_code] = {
                    "name": _nm,
                    "fee": int(_cl_fee),
                    "commissioner_email": _em,
                    "created_at": _dt_lg.now().isoformat(),
                    "members": [_em],
                }
                # Auto-join the commissioner
                admin.setdefault("league_memberships", {})[_em] = _new_code
                save_state(admin)

                # Stash for the post-create reveal
                st.session_state["last_created_league_code"] = _new_code
                st.session_state["last_created_league_name"] = _nm
                st.session_state["last_created_league_fee"]  = int(_cl_fee)
                st.rerun()

    # Post-create success block — appears once, right below the expander.
    _new_code = st.session_state.get("last_created_league_code", "")
    if _new_code:
        _lgc = _leagues_store.get(_new_code, {}) or admin.get("leagues", {}).get(_new_code, {})
        _share_url = f"{APP_URL}/?league={_new_code}"
        _nm_cre = st.session_state.get("last_created_league_name", _lgc.get("name",""))
        _fee_cre = st.session_state.get("last_created_league_fee", _lgc.get("fee", ENTRY_FEE))
        st.markdown(
            f'<div class="league-share-box">'
            f'  <div class="ls-title">🎉 League created — <em>{_nm_cre}</em></div>'
            f'  <div style="color:#a7c9a7; font-size:0.85rem;">Your league code:</div>'
            f'  <div class="ls-code">{_new_code}</div>'
            f'  <div style="color:#a7c9a7; font-size:0.85rem;">Share this link with your friends:</div>'
            f'  <code class="ls-url">{_share_url}</code>'
            f'  <div class="ls-hint">Anyone who enters from this link joins your league at ${_fee_cre}/entry. '
            f'You\'ve already been added as the first member.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        # Clear-the-reveal button
        if st.button("Got it — hide this", key="btn_dismiss_new_league"):
            for _k in ("last_created_league_code", "last_created_league_name", "last_created_league_fee"):
                st.session_state.pop(_k, None)
            st.rerun()

# Join-by-code — sibling expander to Create-a-league. Shown even when
# entries are locked (a late friend can still pull up a league's scoped
# standings by typing the code their buddy gave them).
if not current_league:
    _render_join_by_code_inline(admin)

# ============================================================
# POOL STANDINGS
# ============================================================
# In a private league, the section title reflects the league name instead
# of the generic "Pool Standings" label so the view feels scoped.
# Tournament name intentionally NOT repeated here — it's already in the
# hero subtitle, so showing it again would just add visual noise.
if current_league:
    _ps_heading = f'{current_league.get("name","League")} Standings'
else:
    _ps_heading = "Pool Standings"
st.markdown(f'<div class="section-title">{_ps_heading}</div>', unsafe_allow_html=True)

# ---- "Who are you?" identity strip (persists across rerenders via session state) ----
# Auto-seed from entry submission or returning-user lookup if we have that info.
if "my_email" not in st.session_state:
    st.session_state.my_email = (
        st.session_state.get("entry_submitted_email", "")
        or st.session_state.get("prefill_email", "")
    ).lower().strip()

my_email_cur = st.session_state.get("my_email", "").lower().strip()
my_row_preview = None
if my_email_cur and not df_display.empty:
    matches = df_display[df_display["Email"].str.lower().str.strip() == my_email_cur]
    if not matches.empty:
        my_row_preview = matches.iloc[0]

if my_row_preview is not None:
    id_html = (
        f'<div class="id-strip">'
        f'<span class="lbl">You are</span>'
        f'<span class="name">{my_row_preview["Name"]}</span>'
        f'<span class="hint">— highlighted below</span>'
        f'</div>'
    )
    st.markdown(id_html, unsafe_allow_html=True)
    if st.button("Not me — forget this", key="btn_forget_me", type="secondary"):
        st.session_state.my_email = ""
        st.rerun()
else:
    # Compact inline "Highlight me" toggle — tiny link that expands a small form.
    if "show_highlight_me" not in st.session_state:
        st.session_state.show_highlight_me = False

    if not st.session_state.show_highlight_me:
        st.markdown(
            '<div class="highlight-me-toggle-wrap"></div>',
            unsafe_allow_html=True,
        )
        if st.button("👤 Highlight me", key="btn_show_highlight", type="secondary"):
            st.session_state.show_highlight_me = True
            st.rerun()
    else:
        st.markdown('<div class="highlight-me-inline">', unsafe_allow_html=True)
        _hc1, _hc2, _hc3 = st.columns([4, 2, 1])
        with _hc1:
            _e = st.text_input(
                "Your email",
                key="id_email_input",
                placeholder="you@example.com",
                label_visibility="collapsed",
            )
        with _hc2:
            _save = st.button("Remember me", key="btn_remember_me", use_container_width=True)
        with _hc3:
            _cancel = st.button("✕", key="btn_hide_highlight", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
        if _save and _e.strip():
            st.session_state.my_email = _e.strip().lower()
            st.session_state.show_highlight_me = False
            st.rerun()
        if _cancel:
            st.session_state.show_highlight_me = False
            st.rerun()

if not df_display.empty:
    min_score = df_display["Total"].min()
    n_leaders = len(df_display[df_display["Total"] == min_score])
    # Projected overall winner's take — tied leaders split
    lead_pay  = round(overall_payout / n_leaders, 2) if n_leaders else 0
    rank_emoji = ["🥇","🥈","🥉"]

    # Position-arrow lookup: admin snapshot of previous ranks keyed by email (fallback to venmo)
    rank_snap = admin.get("rank_snapshot", {}) or {}
    def _prev_rank_for(email, venmo):
        e = (email or "").lower().strip()
        v = (venmo or "").lower().strip()
        if e and e in rank_snap:
            return int(rank_snap[e])
        if v and v in rank_snap:
            return int(rank_snap[v])
        return None

    history = admin.get("history", [])

    # Per-day winning scores — used to mark the winner chip for each day
    _day_short = {1: "THU", 2: "FRI", 3: "SAT", 4: "SUN"}
    _day_winning_score = {}
    for _rn in (1, 2, 3, 4):
        _day = ROUND_TO_DAY[_rn]
        _mv = daily_movers.get(_day)
        if _mv is not None:
            _day_winning_score[_rn] = _mv["score"]

    for i, row in df_display.iterrows():
        is_leader = (row["Total"] == min_score)
        is_top3   = (i < 3)
        total     = row["Total"]
        total_cls = "total-under" if total<0 else "total-over" if total>0 else "total-even"

        picks_html = ""
        for idx, (pname, pscore) in enumerate(row["Picks"]):
            is_best  = (idx == row["BestIndex"])
            sc_cls   = "pick-score-under" if pscore<0 else "pick-score-over" if pscore>0 else "pick-score-even"
            star     = '<span class="pick-chip-star">⭐</span>' if is_best else ""
            chip_cls = "pick-chip best" if is_best else "pick-chip"
            ov_badge = '<span class="override-badge">✎</span>' if pname in admin["score_overrides"] else ""
            # CUT pill next to golfers who missed the cut; nothing else clutters the name.
            cut_html = '<span class="cut-pill">CUT</span>' if pname in cut_set else ""
            # Wrap name in its own span so mobile CSS can use flex space-between
            # to align "Name ……… Score" on a clean list row.
            picks_html += (
                f'<div class="{chip_cls}">'
                f'<span class="pick-chip-name">{star}{pname}{ov_badge}{cut_html}</span>'
                f'<span class="{sc_cls} pick-chip-score">{fmt_score(pscore)}</span>'
                f'</div>'
            )

        # Per-day combined delta score (sum of 3 picks' deltas). None = round not yet scored.
        _pick_names = [p[0] for p in row["Picks"]]
        days_html = ""
        for _rn in (1, 2, 3, 4):
            _lbl = _day_short[_rn]
            _vals = []
            for _pn in _pick_names:
                _v = round_delta_vs_par(_pn, _rn, rounds_vs_par, score_map, current_period, espn_state)
                if _v is not None:
                    _vals.append(_v)
            if len(_vals) == 3:
                _d = sum(_vals)
                _sc_cls = "under" if _d < 0 else "over" if _d > 0 else "even"
                _win_cls = " winner" if (_rn in _day_winning_score and _d == _day_winning_score[_rn]) else ""
                days_html += (
                    f'<div class="day-chip {_sc_cls}{_win_cls}">'
                    f'<span class="day-lbl">{_lbl}</span>'
                    f'<span class="day-val">{fmt_score(_d)}</span>'
                    f'</div>'
                )
            else:
                days_html += (
                    f'<div class="day-chip empty">'
                    f'<span class="day-lbl">{_lbl}</span>'
                    f'<span class="day-val">—</span>'
                    f'</div>'
                )

        # YOU detection
        row_email = str(row.get("Email", "")).lower().strip()
        is_you    = bool(my_email_cur) and (row_email == my_email_cur)

        # Card class
        is_paid = bool(row.get("Paid", False))
        cls_bits = ["entry-card"]
        if is_leader: cls_bits.append("leader")
        if is_you:    cls_bits.append("you")
        if not is_paid: cls_bits.append("pending")
        card_cls = " ".join(cls_bits)

        # Position delta (only show if we have a snapshot)
        cur_rank = i + 1
        pos_html = ""
        if rank_snap:
            prev = _prev_rank_for(row_email, row.get("Venmo", ""))
            pos_html = position_delta_html(cur_rank, prev)

        # Rank column: leader gets rank number + money pill; top 3 get gold highlight; others plain.
        # Wrap rank + optional position-delta pill in .rank-wrap so they stack.
        # Keep every HTML line flush-left — Streamlit's markdown treats 4+ space indents as code blocks.
        if is_leader:
            inner_rank = f'<div class="rank-stack"><div class="medal">🥇</div><div class="money-pill">${lead_pay:.0f}</div></div>'
        elif is_top3:
            inner_rank = f'<div class="rank-badge top3">{rank_emoji[i]}</div>'
        else:
            inner_rank = f'<div class="rank-badge">{i+1}</div>'

        rank_html = f'<div class="rank-wrap">{inner_rank}{pos_html}</div>' if pos_html else inner_rank

        # Hall of Fame badge (only if they have history wins)
        hof_html  = hof_badge_html(row_email, history)
        you_pill  = '<span class="you-pill">YOU</span>' if is_you else ""
        pending_pill = '' if is_paid else '<span class="pending-pill" title="Payment not yet received">PENDING</span>'

        card_html = (
            f'<div class="{card_cls}">'
            f'{rank_html}'
            f'<div class="entry-id">'
            f'<div class="entry-name">{row["Name"]}{hof_html}{you_pill}{pending_pill}</div>'
            f'<div class="entry-venmo">@{row["Venmo"]}</div>'
            f'</div>'
            f'<div class="picks-area">{picks_html}</div>'
            f'<div class="days-area">{days_html}</div>'
            f'<div class="total-score {total_cls}">{fmt_score(total)}</div>'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)
else:
    if current_league:
        # League-aware empty state: show the invite URL so the commissioner
        # can text it to their group right from this screen.
        _share = f"{APP_URL}/?league={current_league_code}"
        st.markdown(
            f'<div style="text-align:center;padding:40px 20px;color:#4a6b4a;">'
            f'<div style="font-size:2rem;">🏆</div>'
            f'<div style="font-family:\'Playfair Display\',serif;font-size:1.2rem;color:#fff;margin-top:8px;">'
            f'No one in your league has entered yet'
            f'</div>'
            f'<div style="margin-top:8px;font-size:0.88rem;color:#a7c9a7;">'
            f'Send this link to your friends to get them in:'
            f'</div>'
            f'<code style="display:inline-block;margin-top:10px;padding:8px 14px;background:#0a0f0a;'
            f'border:1px solid #2a3d2a;border-radius:8px;color:#4ade80;font-size:0.9rem;">'
            f'{_share}</code>'
            f'</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div style="text-align:center;padding:48px 20px 40px 20px;color:#4a6b4a;">'
            '<div style="font-size:2.2rem;">⛳</div>'
            '<div style="font-family:\'Playfair Display\',serif;font-size:1.35rem;color:#fff;margin-top:8px;">Be the first to lock in picks</div>'
            '<div style="margin-top:10px;font-size:0.95rem;color:#a7c9a7;max-width:420px;margin-left:auto;margin-right:auto;line-height:1.55;">'
            '4 round winners get paid (Thu · Fri · Sat · Sun) plus the overall champ Sunday night.'
            '</div>'
            '</div>',
            unsafe_allow_html=True
        )

st.markdown('<hr class="divider">', unsafe_allow_html=True)

# ============================================================
# WINNERS
# ============================================================
st.markdown('<div class="section-title">Round Winners<span class="section-sub">· a new winner Thu · Fri · Sat · Sun</span></div>', unsafe_allow_html=True)

cards_html = ""
for day in ["Thursday","Friday","Saturday","Sunday"]:
    manual_name = admin["daily_winners"].get(day, "")
    mover       = daily_movers.get(day)

    # Manual override wins if set; otherwise use auto-computed daily mover.
    if manual_name:
        winner_name = manual_name
        w_rows = df_display[df_display["Name"]==winner_name] if not df_display.empty else pd.DataFrame()
        day_score_str = fmt_score(w_rows.iloc[0]["Total"]) if not w_rows.empty else ""
        is_live = False
        tie_tag = ""
    elif mover:
        winner_name = mover["name"]
        day_score_str = fmt_score(mover["score"])
        is_live = not mover["final"]
        tie_tag = " (T)" if mover["tied"] else ""
    else:
        winner_name = ""
        day_score_str = ""
        is_live = False
        tie_tag = ""

    if winner_name:
        live_pill = '<div class="winner-live">LEADING</div>' if is_live else ""
        cards_html += (
            f'<div class="winner-card has-winner">'
            f'<div class="winner-day">{day}</div>'
            f'<div class="winner-name">{winner_name}{tie_tag}</div>'
            f'<div class="winner-score">{day_score_str}</div>'
            f'<div class="winner-payout">${daily_payout}</div>'
            f'{live_pill}'
            f'</div>'
        )
    else:
        cards_html += (
            f'<div class="winner-card">'
            f'<div class="winner-day">{day}</div>'
            f'<div class="winner-tbd">—</div>'
            f'<div style="font-size:0.68rem;color:#2a4a2a;margin-top:6px;">${daily_payout}</div>'
            f'</div>'
        )

if is_finished and not df_display.empty:
    ov = df_display.iloc[0]
    cards_html += f"""
    <div class="winner-card has-winner" style="border-color:#ffffff33;">
        <div class="winner-day">Overall</div>
        <div class="winner-name">{ov['Name']}</div>
        <div class="winner-score">{fmt_score(ov['Total'])}</div>
        <div class="winner-payout">${overall_payout}</div>
    </div>"""
else:
    cards_html += f"""
    <div class="winner-card">
        <div class="winner-day">Overall</div>
        <div class="winner-tbd">—</div>
        <div style="font-size:0.68rem;color:#2a4a2a;margin-top:6px;">${overall_payout}</div>
    </div>"""

st.markdown(f'<div class="winners-grid">{cards_html}</div>', unsafe_allow_html=True)
st.markdown('<hr class="divider">', unsafe_allow_html=True)

# ============================================================
# HALL OF FAME (ALL-TIME LEADERBOARD)
# ============================================================
st.markdown('<div class="section-title">Hall of Fame</div>', unsafe_allow_html=True)

leaderboard = compute_leaderboard(admin.get("history", []))
history_list = admin.get("history", []) or []
last_tourney = history_list[-1] if history_list else None

# ───────────────────────────────────────────────────────────────
# 1) Last Champion card — show the most recent tournament winner
#    (if there's any history at all)
# ───────────────────────────────────────────────────────────────
if last_tourney and last_tourney.get("overall_winner"):
    _lc_name    = last_tourney.get("overall_winner", "")
    _lc_tourney = last_tourney.get("tournament_name", "Last Tournament")
    _lc_payout  = last_tourney.get("overall_payout", 0)
    _lc_score   = ""
    # Try to pull winner's total score from entries for flavor
    for _e in last_tourney.get("entries", []) or []:
        if (_e.get("name") or "").strip().lower() == _lc_name.strip().lower():
            _sc = _e.get("total")
            if _sc is not None:
                _lc_score = fmt_score(_sc)
            break
    _score_tag = f'<span class="last-champ-score">{_lc_score}</span>' if _lc_score else ""
    _winnings_tag = f'<span class="last-champ-winnings">+${_lc_payout:.0f}</span>' if _lc_payout else ""
    st.markdown(
        f'<div class="last-champ">'
        f'<div class="last-champ-label">👑 Last Champion</div>'
        f'<div class="last-champ-name">{_lc_name}</div>'
        f'<div class="last-champ-meta">{_lc_tourney}{_score_tag}{_winnings_tag}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

# ───────────────────────────────────────────────────────────────
# 2) All-time leaderboard (full table if history exists)
# ───────────────────────────────────────────────────────────────
if leaderboard:
    _hof_subtitle = "All-time standings"
    st.markdown(f'<div class="hof-subhead">{_hof_subtitle}</div>', unsafe_allow_html=True)
    header_html = """
    <div class="tourney-row" style="border-bottom:1px solid #2a4a2a;background:#0d160d;">
        <span style="width:28px;color:#8aad8a;font-size:0.68rem;text-transform:uppercase;letter-spacing:1px;">#</span>
        <span style="flex:2;color:#8aad8a;font-size:0.68rem;text-transform:uppercase;letter-spacing:1px;">Player</span>
        <span style="width:55px;color:#8aad8a;font-size:0.68rem;text-transform:uppercase;letter-spacing:1px;text-align:center;">Pools</span>
        <span style="width:50px;color:#8aad8a;font-size:0.68rem;text-transform:uppercase;letter-spacing:1px;text-align:center;">Wins</span>
        <span style="width:50px;color:#8aad8a;font-size:0.68rem;text-transform:uppercase;letter-spacing:1px;text-align:center;">Best</span>
        <span style="width:80px;color:#8aad8a;font-size:0.68rem;text-transform:uppercase;letter-spacing:1px;text-align:right;">Won</span>
    </div>
    """
    rows_html = ""
    for i, p in enumerate(leaderboard[:25], 1):
        medal = ["🥇","🥈","🥉"][i-1] if i <= 3 else str(i)
        best = str(p["best_finish"]) if p["best_finish"] < 999 else "—"
        name_cls_weight = "700" if i <= 3 else "500"
        name_cls_color = "#fff" if i <= 3 else "#e8ede8"
        rows_html += f"""
        <div class="tourney-row">
            <span style="width:28px;color:#4a6b4a;font-weight:600;font-size:0.82rem;">{medal}</span>
            <span style="flex:2;color:{name_cls_color};font-weight:{name_cls_weight};">{p['display_name']}</span>
            <span style="width:55px;color:#8aad8a;text-align:center;">{p['tournaments']}</span>
            <span style="width:50px;color:#fff;text-align:center;font-weight:700;">{p['wins']}</span>
            <span style="width:50px;color:#8aad8a;text-align:center;">{best}</span>
            <span style="width:80px;color:#4ade80;text-align:right;font-weight:700;">${p['total_winnings']:.0f}</span>
        </div>
        """
    st.markdown(f'<div class="tourney-container">{header_html}{rows_html}</div>', unsafe_allow_html=True)
    st.caption(f"Showing top {min(25, len(leaderboard))} of {len(leaderboard)} all-time players.")
else:
    # ─────────────────────────────────────────────────────────
    # Cold-start empty state — no archived tournaments yet.
    # Rather than "opens after Sunday", show the CURRENT WEEK's
    # top 3 as an energizing "In the running" preview so the
    # section never feels dead.
    # ─────────────────────────────────────────────────────────
    if not df_display.empty:
        preview_rows = ""
        for _i in range(min(3, len(df_display))):
            _row = df_display.iloc[_i]
            _medal = ["🥇","🥈","🥉"][_i]
            _sc_cls = "total-under" if _row["Total"] < 0 else "total-over" if _row["Total"] > 0 else "total-even"
            preview_rows += (
                f'<div class="hof-preview-row">'
                f'<span class="hof-preview-rank">{_medal}</span>'
                f'<span class="hof-preview-name">{_row["Name"]}</span>'
                f'<span class="hof-preview-score {_sc_cls}">{fmt_score(_row["Total"])}</span>'
                f'</div>'
            )
        st.markdown(
            f'<div class="hof-preview">'
            f'<div class="hof-preview-label">🏆 In the running this week</div>'
            f'{preview_rows}'
            f'<div class="hof-preview-footer">First champion gets crowned Sunday night.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="hof-empty" style="text-align:center;padding:24px 16px;color:#4a6b4a;'
            'background:#0d160d; border:1px solid #1e2e1e; border-radius:12px; margin:4px 0 8px 0;">'
            '<div style="font-size:1.6rem;">🏆</div>'
            '<div style="font-family:\'Playfair Display\',serif;font-size:1rem;color:#fff;margin-top:4px;">Be the first champion</div>'
            '<div style="font-size:0.72rem;color:#4a6b4a;margin-top:3px;letter-spacing:0.5px;">The first name etched here is yours for the taking — join before Thursday.</div>'
            '</div>',
            unsafe_allow_html=True,
        )

st.markdown('<hr class="divider">', unsafe_allow_html=True)

# ============================================================
# TOURNAMENT LEADERS
# ============================================================
st.markdown('<div class="section-title">Tournament Leaders</div>', unsafe_allow_html=True)

if espn_lb:
    lb_html = ""
    for i, (name, raw_score) in enumerate(espn_lb[:10], 1):
        s = str(raw_score)
        try:    val = 0 if s in ("E","") else int(s)
        except: val = 0
        if name in admin["score_overrides"]:
            val = admin["score_overrides"][name]
        sc_cls  = "tourney-score-under" if val<0 else "tourney-score-over" if val>0 else "tourney-score-even"
        ov_flag = " ✎" if name in admin["score_overrides"] else ""
        # Tee-time pill: only shows when the player hasn't teed off yet.
        # When they're playing or done, it's empty and the score reads solo.
        tt = tee_times.get(name, "")
        tt_html = f'<span class="tourney-tee">⏰ {tt}</span>' if tt else ''
        # Keep every HTML fragment flush-left with no newlines between tags —
        # any leading whitespace inside st.markdown gets interpreted as a
        # markdown code block and the raw HTML leaks to the page.
        lb_html += (
            f'<div class="tourney-row">'
            f'<span class="tourney-pos">{i}</span>'
            f'<span class="tourney-name">{name}{ov_flag}</span>'
            f'{tt_html}'
            f'<span class="{sc_cls}">{fmt_score(val)}</span>'
            f'</div>'
        )
    st.markdown(f'<div class="tourney-container">{lb_html}</div>', unsafe_allow_html=True)
else:
    st.markdown('<div style="color:#4a6b4a;font-size:0.9rem;padding:12px 0;">Live scores temporarily unavailable.</div>', unsafe_allow_html=True)

# ============================================================
# ADMIN PANEL — hidden unless URL contains ?admin=1
# Bookmark  https://clubhousepool.streamlit.app/?admin=1  for yourself.
# Everyone else just sees a clean page with no sign the admin controls exist.
# ============================================================
_admin_visible = False
try:
    _qp = st.query_params
    _v = _qp.get("admin", "")
    if isinstance(_v, list):
        _v = _v[0] if _v else ""
    _admin_visible = str(_v).strip() == "1"
except Exception:
    # Fallback for older Streamlit versions
    try:
        _qp = st.experimental_get_query_params()
        _admin_visible = _qp.get("admin", [""])[0] == "1"
    except Exception:
        _admin_visible = False

if _admin_visible:
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    with st.expander("🔐 Admin", expanded=False):
        pwd = st.text_input("Password", type="password", key="admin_pwd")

        if pwd == ADMIN_PASSWORD:
            st.success("✓ Logged in")

            # ── Contextual phase hint: tell the admin what to do NOW ──
            from datetime import datetime as _dt_now
            _today = _dt_now.now()
            _dow = _today.weekday()   # Mon=0 ... Sun=6
            if admin.get("tournament_finished"):
                _phase_label = "🏁 Wrap Up"
                _phase_hint  = (
                    "Tournament is marked finished. Jump to <strong>📰 Weekly Recap</strong> to copy "
                    "the summary into your group chat, then <strong>📦 Archive Tournament</strong> "
                    "to lock results into the Hall of Fame."
                )
            elif current_period and current_period >= 1 and not admin.get("tournament_finished"):
                _phase_label = "🟢 During Tournament"
                _phase_hint  = (
                    "Tournament is live. Main jobs: mark <strong>💰 Payments</strong> as Venmos come "
                    "in, capture a <strong>📸 Rank Snapshot</strong> each night (Thu/Fri/Sat), and "
                    "use <strong>✎ Score Overrides</strong> only if ESPN is wrong."
                )
            elif _dow in (0, 1, 2):   # Mon–Wed
                _phase_label = "🆕 New Tournament Setup"
                _phase_hint  = (
                    "It's early-week — time to prep the next pool. Workflow: "
                    "send the field to Claude → he updates <code>app.py</code> tiers and you mirror "
                    "them in the Google Form → set the <strong>🕐 First Tee Time</strong> "
                    "→ hit <strong>🔄 Start New Tournament</strong> to clear last week's board "
                    "(Hall of Fame stays intact)."
                )
            else:   # Thursday morning before tee-off
                _phase_label = "⏰ Pre-Tee-Off"
                _phase_hint  = (
                    "Last call before Thursday tee-off. Make sure <strong>💰 Payments</strong> are "
                    "up to date and <strong>🕐 First Tee Time</strong> is set so the countdown strip "
                    "works. Flip <strong>🔒 Entry Gate</strong> to freeze once the first group tees off."
                )
            st.markdown(
                f'<div class="admin-phase-hint">'
                f'<strong>Right now: {_phase_label}</strong><br>{_phase_hint}'
                f'</div>',
                unsafe_allow_html=True,
            )

            # ── Full weekly workflow (collapsible reference card) ──────
            # Always-visible overview so the operator can scan the whole
            # week's flow in order, regardless of what day it is. Each
            # phase below corresponds to one of the colored admin groups.
            with st.expander("📖 Full weekly workflow — every step in order", expanded=False):
                st.markdown(
                    """
<div style="font-size:0.92rem; line-height:1.7; color:#d8e8d8;">

<div style="background:#1a2a1a; border-left:3px solid #d4af37; padding:10px 14px; border-radius:6px; margin-bottom:10px;">
<strong style="color:#d4af37;">🆕 Mon – Wed · Setup</strong>
<ol style="margin:6px 0 0 18px; padding:0;">
<li>Open <strong>🆔 Tournament ID</strong> → click <strong>🔎 List upcoming PGA tournaments</strong>, then hit <strong>📌 Use this ID</strong> next to this week's event (auto-updates <code>app.py</code>).</li>
<li>Open <strong>📋 Tier-List Helper</strong> → paste this week's field (in world-rank order) → click <strong>⚡ Auto-split + update app.py</strong>. It splits evenly into 3 (remainder goes to Tier 3) and rewrites the tier blocks for you.</li>
<li>Copy each of the 3 dropdown blocks the helper shows and paste them into the matching Google Form pick-question's options.</li>
<li>Open <strong>🕐 First Tee Time</strong> and set Thursday's first group.</li>
<li>Click <strong>🔄 Start New Tournament</strong> → wipes last week's board. Hall of Fame stays intact.</li>
</ol>
</div>

<div style="background:#0d1a1f; border-left:3px solid #4ade80; padding:10px 14px; border-radius:6px; margin-bottom:10px;">
<strong style="color:#4ade80;">⏰ Thu morning · Pre-Tee-Off</strong>
<ol style="margin:6px 0 0 18px; padding:0;">
<li>Make sure all paid Venmos are marked in <strong>💰 Payments</strong>.</li>
<li>Once the first group tees off, flip <strong>🔒 Entry Gate</strong> ON to lock new entries out.</li>
</ol>
</div>

<div style="background:#0d1a1f; border-left:3px solid #4ade80; padding:10px 14px; border-radius:6px; margin-bottom:10px;">
<strong style="color:#4ade80;">🟢 Thu – Sun · During Tournament</strong>
<ol style="margin:6px 0 0 18px; padding:0;">
<li>Mark <strong>💰 Payments</strong> as Venmos come in (only paid entries count toward the pot).</li>
<li>End of each round, take a <strong>📸 Rank Snapshot</strong> so movement arrows show overnight changes.</li>
<li>Round winners auto-detect from low round-only score — only touch <strong>🏁 Round Winners (manual override)</strong> if it's wrong.</li>
</ol>
</div>

<div style="background:#1a0d1a; border-left:3px solid #a78bfa; padding:10px 14px; border-radius:6px; margin-bottom:10px;">
<strong style="color:#a78bfa;">🏁 Sun night · Wrap Up</strong>
<ol style="margin:6px 0 0 18px; padding:0;">
<li>Flip <strong>✅ Mark Tournament Finished</strong> ON — locks the Overall Champion card.</li>
<li>Click <strong>📰 Weekly Recap</strong> → copy text into the group chat.</li>
<li>Click <strong>📦 Archive Tournament</strong> → 👑 + ⭐ added to the Hall of Fame, win counts roll up by email.</li>
</ol>
<div style="font-size:0.85rem; color:#c0a8d8; margin-top:8px;">
You're now ready to loop back to <strong>🆕 Setup</strong> for next week's tournament.
</div>
</div>

<div style="font-size:0.85rem; color:#a7c9a7; padding:6px 14px;">
💡 <strong>Hall of Fame is permanent.</strong> Every <strong>🔄 Start New Tournament</strong> wipes the current board, but archived tournaments and player win counts survive forever.
</div>

</div>
                    """,
                    unsafe_allow_html=True,
                )

            # ══════════════════════════════════════════════════════════
            # 🆕 NEW TOURNAMENT SETUP (Monday)
            # ══════════════════════════════════════════════════════════
            st.markdown(
                '<div class="admin-group setup">'
                '<span class="g-title">🆕 New Tournament Setup</span>'
                '<span class="g-when">Monday</span>'
                '</div>',
                unsafe_allow_html=True,
            )
            st.caption("Run these Mon–Wed to prep for Thursday.")

            # ── Tournament ID picker — list ESPN's schedule, one click to set ──
            with st.expander(f"🆔 Tournament ID  ·  current: {TOURNAMENT_ID}", expanded=False):
                st.caption(
                    "ESPN's event ID drives scores, tee times, and the field. Each new tournament "
                    "gets a new one. Click below to pull ESPN's full PGA schedule — then hit "
                    "**📌 Use this ID** on this week's event and `app.py` updates itself."
                )

                if st.button("🔎 List upcoming PGA tournaments", key="btn_list_pga", use_container_width=True, type="primary"):
                    with st.spinner("Asking ESPN for the PGA schedule…"):
                        st.session_state["_pga_schedule"] = list_upcoming_pga_tournaments()

                _events = st.session_state.get("_pga_schedule")
                if _events is not None:
                    if not _events:
                        st.error("ESPN returned no events. The API might be down — try again in a minute.")
                    else:
                        st.success(f"Found **{len(_events)}** events. Hit **📌 Use this ID** on this week's tournament:")
                        for _i, _ev in enumerate(_events):
                            _is_match = (_ev["id"] == str(TOURNAMENT_ID))
                            _star = " ⭐" if _is_match else ""
                            _r1, _r2 = st.columns([5, 2])
                            with _r1:
                                st.markdown(
                                    f"`{_ev['id']}` — **{_ev['name']}**{_star}  \n"
                                    f"<span style='color:#a7c9a7;font-size:0.85rem;'>"
                                    f"📅 {_ev['start']} → {_ev['end']}  ·  {_ev['status']}"
                                    f"</span>",
                                    unsafe_allow_html=True,
                                )
                            with _r2:
                                if _is_match:
                                    st.markdown(
                                        "<div style='color:#4ade80;font-size:0.85rem;padding-top:6px;'>✅ active</div>",
                                        unsafe_allow_html=True,
                                    )
                                else:
                                    if st.button("📌 Use this ID", key=f"btn_use_tid_{_ev['id']}_{_i}", use_container_width=True):
                                        ok, msg = update_tournament_id_in_source(_ev["id"])
                                        if ok:
                                            st.success(msg)
                                            st.session_state.pop("_pga_schedule", None)
                                            st.rerun()
                                        else:
                                            st.error(msg)
                        st.caption("If you don't see this week's tournament in the list, send Claude the ID and he'll update it manually.")

            # ── Tier-List Helper — paste field, auto-split into 3, auto-update app.py ──
            with st.expander("📋 Tier-List Helper — paste field, auto-update tiers", expanded=False):
                st.caption(
                    "Paste this week's field below — one golfer per line (or comma-separated). "
                    "The tool strips junk (rank numbers, odds, '+' signs), splits the field "
                    "evenly into 3 tiers in the order you pasted (so paste in world-rank order), "
                    "then writes the new `TIER_1 / TIER_2 / TIER_3` blocks straight into `app.py`. "
                    "Any odd remainder goes to **Tier 3**. After it updates, paste the same names "
                    "into your Google Form's three pick-question dropdowns to keep them in sync."
                )
                _field_text = st.text_area(
                    "Paste field (one per line, or with ranks/odds — we'll clean it)",
                    height=240, key="tier_field_text",
                    placeholder="1. Scottie Scheffler +350\n2. Rory McIlroy +700\n..."
                )

                if st.button("⚡ Auto-split + update app.py", key="btn_build_tiers", type="primary", use_container_width=True):
                    import re as _re
                    lines = [ln.strip() for ln in (_field_text or "").splitlines() if ln.strip()]
                    if len(lines) == 1 and "," in lines[0]:
                        lines = [x.strip() for x in lines[0].split(",") if x.strip()]
                    cleaned = []
                    seen = set()
                    for ln in lines:
                        s = _re.sub(r"^(t?\d+[\.\)]?\s*)", "", ln, flags=_re.I)
                        s = _re.sub(r"\s*[+\-]\d+\s*$", "", s)
                        s = _re.sub(r"\s*\([^)]*\)\s*$", "", s)
                        s = _re.sub(r"\s+[A-Z]{3}\s*$", "", s)
                        s = s.strip().strip(",").strip()
                        if s and s.lower() not in seen:
                            seen.add(s.lower())
                            cleaned.append(s)
                    if not cleaned:
                        st.warning("No names parsed — check your paste.")
                    elif len(cleaned) < 6:
                        st.warning(f"Only {len(cleaned)} names parsed — that's too small to split into 3 tiers. Need at least 6.")
                    else:
                        # Even split — any remainder goes to Tier 3 (longshots)
                        # so a field of 100 becomes 33/33/34, and 101 becomes 33/33/35.
                        _N = len(cleaned)
                        _per = _N // 3
                        _sz1 = _per
                        _sz2 = _per
                        t1 = cleaned[:_sz1]
                        t2 = cleaned[_sz1:_sz1 + _sz2]
                        t3 = cleaned[_sz1 + _sz2:]   # gets the remainder
                        ok, msg = update_tier_lists_in_source(t1, t2, t3)
                        # Persist the result so it survives reruns (otherwise the
                        # copy-paste blocks vanish the moment Streamlit reruns).
                        st.session_state["_tier_split_result"] = {
                            "ok": ok, "msg": msg, "n": _N,
                            "t1": t1, "t2": t2, "t3": t3,
                        }

                # ── Persistent result panel — survives reruns so you can copy ──
                _tier_res = st.session_state.get("_tier_split_result")
                if _tier_res:
                    if _tier_res["ok"]:
                        st.success(
                            f"Parsed **{_tier_res['n']}** golfers → "
                            f"Tier 1: **{len(_tier_res['t1'])}** · "
                            f"Tier 2: **{len(_tier_res['t2'])}** · "
                            f"Tier 3: **{len(_tier_res['t3'])}**\n\n{_tier_res['msg']}"
                        )
                        st.markdown(
                            "**📋 Copy each block below and paste into the matching Google Form question.** "
                            "Each block has a copy icon in the top-right corner — click it to copy the whole list, "
                            "or click into the box and ⌘+A then ⌘+C."
                        )
                        # Render each tier full-width, one per row — much easier
                        # to read and copy than narrow side-by-side columns.
                        st.markdown(f"**Pick 1 — Tier 1 (Favorites)** · {len(_tier_res['t1'])} names")
                        st.code("\n".join(_tier_res["t1"]), language=None)
                        st.markdown(f"**Pick 2 — Tier 2 (Contenders)** · {len(_tier_res['t2'])} names")
                        st.code("\n".join(_tier_res["t2"]), language=None)
                        st.markdown(f"**Pick 3 — Tier 3 (Longshots)** · {len(_tier_res['t3'])} names")
                        st.code("\n".join(_tier_res["t3"]), language=None)
                        if st.button("✓ Done — clear these blocks", key="btn_clear_tier_result"):
                            st.session_state.pop("_tier_split_result", None)
                            st.rerun()
                    else:
                        st.error(_tier_res["msg"])
                        st.caption("Tiers were NOT written to app.py. Send Claude the field and he'll update it manually.")
                        if st.button("✓ Dismiss", key="btn_clear_tier_result_err"):
                            st.session_state.pop("_tier_split_result", None)
                            st.rerun()

            # ── Tee time / tournament start (for countdown strip) ──
            with st.expander("🕐 First Tee Time — drives the countdown strip", expanded=False):
                st.caption("Set the first tee-off time. A countdown strip appears at the top of the app until entries lock. Leave blank to hide.")
                from datetime import datetime as _dt2, date as _date2, time as _time2
                cur_start_str = admin.get("tournament_start", "")
                try:
                    _cs = _dt2.fromisoformat(cur_start_str) if cur_start_str else None
                except Exception:
                    _cs = None
                ct1, ct2 = st.columns(2)
                with ct1:
                    tee_date = st.date_input("First tee date",
                                             value=_cs.date() if _cs else _date2.today(),
                                             key="tee_date_input")
                with ct2:
                    tee_time = st.time_input("First tee time (local)",
                                             value=_cs.time() if _cs else _time2(7, 0),
                                             key="tee_time_input")
                tc1, tc2 = st.columns(2)
                if tc1.button("💾 Save tee time", key="btn_save_tee"):
                    admin["tournament_start"] = _dt2.combine(tee_date, tee_time).isoformat()
                    save_state(admin)
                    st.success("✓ Tee time saved")
                    st.rerun()
                if tc2.button("🚫 Clear tee time", key="btn_clear_tee"):
                    admin["tournament_start"] = ""
                    save_state(admin)
                    st.rerun()

            # ── Course par override ──
            with st.expander("⛳ Course Par — only if auto-detect fails", expanded=False):
                auto_par_label = f"auto-detected: {course_par}" if auto_par_found else "auto-detect failed — using fallback 72"
                st.caption(f"Used by Biggest Mover calc. Current value: **{course_par}** ({auto_par_label if not admin.get('course_par') else 'manual override'}). Set to 0 to re-auto-detect.")
                new_par = st.number_input(
                    "Manual par (0 = auto)",
                    min_value=0, max_value=80,
                    value=int(admin.get("course_par", 0)),
                    step=1, key="par_override"
                )
                if new_par != admin.get("course_par", 0):
                    admin["course_par"] = int(new_par)
                    save_state(admin)
                    st.rerun()

            # ── Start new tournament (the BIG reset — do this last) ──
            st.markdown("**🔄 Start New Tournament** _(do this last, after tiers + tee time are set)_")
            st.caption("Clears last week's entries from the board (cutoff by timestamp — nothing deleted from the sheet). Resets round winners and tournament status. **Hall of Fame is preserved** — past champions stay forever.")
            new_tourney_name = st.text_input(
                "New tournament name (optional)",
                placeholder="e.g. Cadillac Invitational 2026",
                key="new_tourney_name"
            )
            confirm_reset = st.checkbox("I understand this will hide all current entries", key="confirm_reset")
            if st.button("🔄 Start New Tournament", key="btn_new_tourney", disabled=not confirm_reset):
                from datetime import datetime as _dt
                admin["entry_cutoff_time"]   = _dt.now().isoformat()
                admin["daily_winners"]       = {"Thursday":"","Friday":"","Saturday":"","Sunday":""}
                admin["score_overrides"]     = {}
                admin["tournament_finished"] = False
                admin["entries_frozen"]      = False
                admin["disqualified"]        = []
                admin["paid_entries"]        = {}
                admin["rank_snapshot"]       = {}
                admin["rank_snapshot_time"]  = ""
                if new_tourney_name.strip():
                    admin["tournament_name"] = new_tourney_name.strip()
                save_state(admin)
                load_sheet.clear()
                st.success("✓ New tournament started — board is clean.")
                st.rerun()

            # ── Private Leagues (view / rename / delete) ──
            st.markdown("**🏆 Private Leagues**")
            _leagues_dict = admin.get("leagues", {}) or {}
            _memb = admin.get("league_memberships", {}) or {}
            if not _leagues_dict:
                st.caption("No private leagues yet. Anyone can create one from the public site.")
            else:
                st.caption(f"{len(_leagues_dict)} league(s) · {len(_memb)} total memberships.")
                for _code, _lg in sorted(_leagues_dict.items(), key=lambda x: x[1].get("created_at", "")):
                    _m = [e for e, c in _memb.items() if c == _code]
                    _paid_in_lg = 0
                    for _r in _rows_unscoped:
                        if (_r.get("Email") or "").lower().strip() in set(_m) and _r.get("Paid"):
                            _paid_in_lg += 1
                    _pot_lg = _paid_in_lg * int(_lg.get("fee", ENTRY_FEE))
                    with st.expander(
                        f"🔒 {_lg.get('name','(unnamed)')}  ·  {_code}  ·  {len(_m)} members  ·  ${_pot_lg} pot",
                        expanded=False,
                    ):
                        st.caption(
                            f"Created {_lg.get('created_at','?')[:10]} by "
                            f"**{_lg.get('commissioner_email','?')}** · ${int(_lg.get('fee',ENTRY_FEE))}/entry"
                        )
                        _share = f"{APP_URL}/?league={_code}"
                        st.code(_share, language=None)

                        if _m:
                            st.markdown("**Members**")
                            for _e in sorted(_m):
                                _c1, _c2 = st.columns([5, 1])
                                with _c1:
                                    st.markdown(f"- `{_e}`")
                                with _c2:
                                    if st.button("Remove", key=f"rm_{_code}_{_e}"):
                                        admin["league_memberships"].pop(_e, None)
                                        _lg.setdefault("members", [])
                                        if _e in _lg["members"]:
                                            _lg["members"].remove(_e)
                                        save_state(admin)
                                        st.success(f"Removed {_e}")
                                        st.rerun()
                        else:
                            st.caption("No members yet.")

                        _rc1, _rc2 = st.columns(2)
                        with _rc1:
                            _newname = st.text_input(
                                "Rename league",
                                value=_lg.get("name",""),
                                key=f"rename_{_code}",
                            )
                            if st.button("Save name", key=f"save_name_{_code}"):
                                _lg["name"] = _newname.strip() or _lg.get("name","")
                                save_state(admin)
                                st.success("Renamed.")
                                st.rerun()
                        with _rc2:
                            _newfee = st.number_input(
                                "Change fee ($)",
                                min_value=1, max_value=500,
                                value=int(_lg.get("fee", ENTRY_FEE)),
                                step=1, key=f"fee_{_code}",
                            )
                            if st.button("Save fee", key=f"save_fee_{_code}"):
                                _lg["fee"] = int(_newfee)
                                save_state(admin)
                                st.success("Fee updated.")
                                st.rerun()

                        st.markdown("---")
                        _confirm = st.checkbox(
                            f"Yes, delete league {_code} (cannot be undone)",
                            key=f"confirm_del_{_code}",
                        )
                        if st.button(f"🗑 Delete {_code}", key=f"del_{_code}", disabled=not _confirm):
                            # Remove league + all its memberships
                            for _e in list(_m):
                                admin["league_memberships"].pop(_e, None)
                            admin["leagues"].pop(_code, None)
                            save_state(admin)
                            st.success(f"Deleted league {_code}.")
                            st.rerun()

            # ══════════════════════════════════════════════════════════
            # 🟢 DURING TOURNAMENT (Thu–Sun)
            # ══════════════════════════════════════════════════════════
            st.markdown(
                '<div class="admin-group during">'
                '<span class="g-title">🟢 During Tournament</span>'
                '<span class="g-when">Thu – Sun</span>'
                '</div>',
                unsafe_allow_html=True,
            )
            st.caption("Day-to-day tournament management.")

            # ── Entry Gate — flip ON Thursday morning when the first group tees off ──
            st.markdown("**🔒 Entry Gate** _(flip ON Thursday morning at first tee)_")
            st.caption("When frozen, the Join Pool section is hidden and new entries can't be submitted. Flip this ON once the first group tees off Thursday.")
            _gate_new = st.toggle(
                "Freeze entries (signups closed)",
                value=bool(admin.get("entries_frozen", False)),
                key="gate_toggle",
            )
            if _gate_new != bool(admin.get("entries_frozen", False)):
                admin["entries_frozen"] = bool(_gate_new)
                save_state(admin)
                st.rerun()

            st.markdown("---")

            # ── Payments (mark each entry paid) ──
            st.markdown("**💰 Payments**")
            st.caption(
                f"Mark who has Venmo'd. Unpaid entries show a **PENDING** pill and don't count toward the prize pot. "
                f"Currently: **{paid_count} paid · {pending_count} pending** (${paid_count * ENTRY_FEE} in the pot)."
            )
            if df_display.empty:
                st.info("No entries yet.")
            else:
                # Quick controls
                pc1, pc2 = st.columns(2)
                if pc1.button("✓ Mark all paid", key="btn_mark_all_paid", use_container_width=True):
                    paid_dict = admin.setdefault("paid_entries", {})
                    for _, erow in df_display.iterrows():
                        k = f"{erow['Venmo']}|{erow['Timestamp']}"
                        paid_dict[k] = True
                    save_state(admin)
                    st.rerun()
                if pc2.button("✕ Mark all unpaid", key="btn_mark_all_unpaid", use_container_width=True):
                    admin["paid_entries"] = {}
                    save_state(admin)
                    st.rerun()

                st.markdown("")
                # Per-entry checkboxes — show unpaid first so you can clear the queue fast
                _df_sorted = df_display.sort_values(by="Paid", ascending=True).reset_index(drop=True) \
                    if "Paid" in df_display.columns else df_display
                for _, erow in _df_sorted.iterrows():
                    e_key = f"{erow['Venmo']}|{erow['Timestamp']}"
                    is_paid = bool(erow.get("Paid", False))
                    pcol1, pcol2 = st.columns([5, 2])
                    label = f"**{erow['Name']}** · @{erow['Venmo']}"
                    pcol1.markdown(label)
                    new_val = pcol2.checkbox("Paid", value=is_paid, key=f"paid_chk_{e_key}")
                    if new_val != is_paid:
                        paid_dict = admin.setdefault("paid_entries", {})
                        if new_val:
                            paid_dict[e_key] = True
                        else:
                            paid_dict.pop(e_key, None)
                        save_state(admin)
                        st.rerun()

            st.markdown("---")

            # ── Manage entries (delete non-payers) ──
            st.markdown("**🗑 Manage Entries**")
            st.caption("Remove an entry from the board — use for anyone who signed up but never paid. Their row stays in the sheet but won't show anywhere on the site.")
            if df_display.empty:
                st.info("No entries currently visible.")
            else:
                for _, erow in df_display.iterrows():
                    e_key = f"{erow['Venmo']}|{erow['Timestamp']}"
                    c1, c2, c3 = st.columns([4, 2, 1])
                    c1.markdown(f"**{erow['Name']}** · @{erow['Venmo']}")
                    c2.caption(erow['Timestamp'][:16] if erow['Timestamp'] else "—")
                    if c3.button("✕", key=f"dq_{e_key}"):
                        admin.setdefault("disqualified", []).append(e_key)
                        save_state(admin)
                        st.rerun()

            # Show currently DQ'd so admin can un-DQ accidentally
            if admin.get("disqualified"):
                st.markdown("**Hidden entries:**")
                for dq_key in list(admin["disqualified"]):
                    rc1, rc2 = st.columns([5, 1])
                    rc1.markdown(f"<code>{dq_key}</code>", unsafe_allow_html=True)
                    if rc2.button("↩", key=f"undq_{dq_key}", help="Restore this entry"):
                        admin["disqualified"].remove(dq_key)
                        save_state(admin)
                        st.rerun()

            st.markdown("---")

            # ── Rank snapshot (for position-arrow diffs in Pool Standings) ──
            st.markdown("**📸 Rank Snapshot**")
            st.caption("Freeze current standings as a reference point — up/down arrows in Pool Standings will show movement since this snapshot. Take one at the end of each round (Thu, Fri, Sat) and arrows will show how entries moved overnight.")
            snap_time = admin.get("rank_snapshot_time", "")
            snap_cnt  = len(admin.get("rank_snapshot", {}))
            if snap_time:
                st.info(f"Last snapshot: **{snap_time[:16].replace('T',' ')}** — {snap_cnt} entries")
            else:
                st.caption("No snapshot captured yet.")
            sc1, sc2 = st.columns(2)
            with sc1:
                if st.button("📸 Capture snapshot now", key="btn_snap_ranks"):
                    if df_display.empty:
                        st.warning("No entries to snapshot.")
                    else:
                        snap = {}
                        for i, row in df_display.iterrows():
                            key = (row.get("Email") or "").lower().strip() or (row.get("Venmo") or "").lower().strip()
                            if key:
                                snap[key] = i + 1
                        admin["rank_snapshot"] = snap
                        from datetime import datetime as _dts
                        admin["rank_snapshot_time"] = _dts.now().isoformat()
                        save_state(admin)
                        st.success(f"✓ Snapshot captured — {len(snap)} entries")
                        st.rerun()
            with sc2:
                if st.button("🗑 Clear snapshot", key="btn_clear_snap"):
                    admin["rank_snapshot"] = {}
                    admin["rank_snapshot_time"] = ""
                    save_state(admin)
                    st.rerun()

            st.markdown("---")

            # ── Round Winners override (rare — use only if auto-detect is wrong) ──
            with st.expander("🏁 Round Winners (manual override — rare)", expanded=False):
                st.caption(
                    "The app auto-picks round winners from lowest round-only 3-pick delta. "
                    "Use these only if you need to force a specific name (e.g. tiebreaker "
                    "decided by count-back or manual pick)."
                )
                _all_entry_names = sorted(df_display["Name"].tolist()) if not df_display.empty else []
                for _day in ["Thursday","Friday","Saturday","Sunday"]:
                    _cur = admin["daily_winners"].get(_day, "")
                    _options = [""] + _all_entry_names
                    _idx = _options.index(_cur) if _cur in _options else 0
                    _pick = st.selectbox(
                        f"{_day} winner (blank = auto)",
                        _options, index=_idx, key=f"dw_{_day}",
                    )
                    if _pick != _cur:
                        admin["daily_winners"][_day] = _pick
                        save_state(admin)
                        st.rerun()

            st.markdown("---")

            # ── Score Overrides (rare — only when ESPN is wrong) ──
            with st.expander("✎ Score Overrides (rare — ESPN correction)", expanded=False):
                st.caption("Override a player's cumulative score vs par. Use only if ESPN data is wrong or a player withdrew mid-round.")
                all_players = sorted(score_map.keys()) if score_map else []
                ov_player = st.selectbox("Player", [""] + all_players, key="ov_player")
                ov_score  = st.number_input("Score vs par", min_value=-30, max_value=30, value=0, step=1, key="ov_score")

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Set Override", key="btn_set") and ov_player:
                        admin["score_overrides"][ov_player] = int(ov_score)
                        save_state(admin); st.rerun()
                with c2:
                    if st.button("🗑 Remove Override", key="btn_clr") and ov_player:
                        admin["score_overrides"].pop(ov_player, None)
                        save_state(admin); st.rerun()

                if admin["score_overrides"]:
                    st.markdown("**Active overrides:**")
                    for p, v in list(admin["score_overrides"].items()):
                        rc1, rc2 = st.columns([5,1])
                        rc1.markdown(f"`{p}` → **{fmt_score(v)}**")
                        if rc2.button("✕", key=f"rm_{p}"):
                            admin["score_overrides"].pop(p, None)
                            save_state(admin); st.rerun()

            # ══════════════════════════════════════════════════════════
            # 🏁 WRAP UP (Sunday night / Monday morning)
            # ══════════════════════════════════════════════════════════
            st.markdown(
                '<div class="admin-group wrap">'
                '<span class="g-title">🏁 Wrap Up</span>'
                '<span class="g-when">Sun night – Mon</span>'
                '</div>',
                unsafe_allow_html=True,
            )
            st.caption("Close out the week: lock the winner, generate recap, archive to Hall of Fame.")

            # ── Tournament finished toggle ──
            st.markdown("**✅ Mark Tournament Finished**")
            st.caption("Flip this ON once Sunday play is over. Locks the Overall winner card and enables the recap.")
            _fin_new = st.toggle(
                "Tournament finished",
                value=bool(admin.get("tournament_finished", False)),
                key="fin_toggle",
            )
            if _fin_new != bool(admin.get("tournament_finished", False)):
                admin["tournament_finished"] = bool(_fin_new)
                save_state(admin)
                st.rerun()

            st.markdown("---")

            # ── Weekly recap (generate shareable summary text) ──
            st.markdown("**📰 Weekly Recap**")
            st.caption("Generate a plain-text recap of this week's tournament — round winners, top 3. Copy it into your group chat when the tournament ends.")
            if st.button("📋 Generate recap", key="btn_recap"):
                recap_lines = []
                tname = admin.get("tournament_name", "") or "This Week"
                recap_lines.append(f"🏆 THE CLUBHOUSE — {tname} Recap")
                recap_lines.append("")
                recap_lines.append(f"💰 Pot: ${pot}  ·  {len(rows)} entries")
                recap_lines.append("")
                recap_lines.append("🏁 Round Winners")
                for day in ["Thursday","Friday","Saturday","Sunday"]:
                    mover = daily_movers.get(day)
                    manual = admin["daily_winners"].get(day, "")
                    if manual:
                        recap_lines.append(f"  • {day}: {manual} — ${daily_payout:.2f}")
                    elif mover and mover.get("name"):
                        sc = fmt_score(mover["score"]) if mover.get("score") is not None else "—"
                        tie = " (tied)" if mover.get("tied") else ""
                        recap_lines.append(f"  • {day}: {mover['name']}{tie} ({sc}) — ${daily_payout:.2f}")
                    else:
                        recap_lines.append(f"  • {day}: —")
                recap_lines.append("")
                recap_lines.append("🥇 Top 3 Overall")
                if not df_display.empty:
                    for i in range(min(3, len(df_display))):
                        r = df_display.iloc[i]
                        medal = ["🥇","🥈","🥉"][i]
                        picks_str = ", ".join([f"{p} ({fmt_score(s)})" for p, s in r["Picks"]])
                        recap_lines.append(f"  {medal} {r['Name']} ({fmt_score(r['Total'])})")
                        recap_lines.append(f"     picks: {picks_str}")
                else:
                    recap_lines.append("  (no entries)")
                if is_finished and not df_display.empty:
                    recap_lines.append("")
                    recap_lines.append(f"👑 Overall Champion: {df_display.iloc[0]['Name']} — ${overall_payout:.2f}")
                recap_lines.append("")
                recap_lines.append(f"Join next week → {APP_URL}")
                recap_text = "\n".join(recap_lines)
                st.text_area("Copy this ↓", value=recap_text, height=360, key="recap_text_out")
                st.caption("Tip: click inside the box and press ⌘/Ctrl+A then ⌘/Ctrl+C to copy.")

            st.markdown("---")

            # ── Archive tournament ──
            st.markdown("**📦 Archive Tournament**")
            st.caption("Lock in this week's final results to the all-time Hall of Fame — the overall champ gets a 👑 and round wins add ⭐ stars. Win counts roll up by email so the same player accumulates across tournaments. Do this after Sunday once winners are set.")
            arc_name = st.text_input(
                "Tournament name",
                value=admin.get("tournament_name", ""),
                placeholder="e.g. RBC Heritage 2026",
                key="arc_name"
            )
            if st.button("📦 Archive This Tournament", key="btn_archive"):
                if not arc_name.strip():
                    st.error("Please enter a tournament name first.")
                elif df_display.empty:
                    st.error("No entries to archive.")
                else:
                    archive = build_tournament_archive(
                        arc_name.strip(), df_display, admin["daily_winners"],
                        daily_payout, overall_payout, is_finished
                    )
                    admin.setdefault("history", []).append(archive)
                    admin["tournament_name"] = arc_name.strip()
                    save_state(admin)
                    st.success(f"✓ Archived '{arc_name}' with {len(archive['entries'])} entries")
                    st.rerun()

            # List archived tournaments with delete option
            if admin.get("history"):
                st.markdown("**Archived tournaments:**")
                for i, t in enumerate(admin["history"]):
                    rc1, rc2 = st.columns([5,1])
                    winner_str = t.get("overall_winner") or "—"
                    rc1.markdown(f"`{t['tournament_name']}` — {len(t['entries'])} entries · winner: **{winner_str}**")
                    if rc2.button("✕", key=f"rm_arc_{i}"):
                        admin["history"].pop(i)
                        save_state(admin)
                        st.rerun()

            # ══════════════════════════════════════════════════════════
            # 🛠 DEBUG & UTILITIES (reach for these only if something's broken)
            # ══════════════════════════════════════════════════════════
            st.markdown(
                '<div class="admin-group debug">'
                '<span class="g-title">🛠 Debug & Utilities</span>'
                '<span class="g-when">As needed</span>'
                '</div>',
                unsafe_allow_html=True,
            )
            st.caption("Diagnostic tools and dangerous resets — only touch these if something looks wrong.")

            # ── Tee-time debug (so we can see what ESPN actually returns) ──
            with st.expander("⏰ Tee-time debug", expanded=False):
                st.caption("Shows which ESPN fields exist for each leaderboard player. "
                           "Fields tagged [lb] come from the secondary /leaderboard endpoint. "
                           "If a tee time is visible in the raw JSON below but NOT in the "
                           "'Extracted tee times' line, copy the JSON to me and I'll wire "
                           "the right field in.")
                st.markdown(f"**Extracted tee times ({len(tee_times)})**: `{tee_times}`")
                st.markdown("---")
                # Show the first 10 leaderboard players' raw tee-candidate fields
                for name, _ in espn_lb[:10]:
                    fields = tee_debug.get(name, {})
                    # Only keep non-null fields to reduce noise
                    non_null = {k: v for k, v in fields.items() if v not in (None, "", [])}
                    st.markdown(f"**{name}**")
                    if non_null:
                        for k, v in non_null.items():
                            st.caption(f"  • `{k}` = `{v}`")
                    else:
                        st.caption("  _(all tee-candidate fields empty)_")
                st.markdown("---")
                st.markdown("**Full raw JSON for the first player** (every field ESPN sends):")
                try:
                    import json as _json
                    st.code(_json.dumps(first_raw_player, indent=2, default=str)[:6000], language="json")
                except Exception as _e:
                    st.caption(f"(JSON dump failed: {_e})")

            # ── ESPN debug data ──
            with st.expander("🔍 ESPN debug data", expanded=False):
                st.markdown(f"**Current period**: {current_period} &nbsp; | &nbsp; **State**: `{espn_state or '—'}` &nbsp; | &nbsp; **Course par**: {course_par}")
                if not raw_linescores:
                    st.warning("No linescore data returned from ESPN. Check TOURNAMENT_ID.")
                else:
                    # Show debug rows for each pick of each entry
                    st.caption("Per-pick round scores (strokes → vs-par). Empty means ESPN hasn't posted that round yet or the value failed the 50–100 stroke guard.")
                    for r in rows[:10]:  # cap for readability
                        st.markdown(f"**{r['Name']}** — picks:")
                        for pname, _ in r["Picks"]:
                            ls = raw_linescores.get(pname, [])
                            raw_vals = [row.get("value") for row in ls] if ls else []
                            computed = rounds_vs_par.get(pname, {})
                            st.caption(f"• `{pname}` → raw linescores: {raw_vals} · computed vs-par: {computed}")
                        st.markdown("")

            # ── Round scoring debug — see the actual numbers used for each round's winner ──
            with st.expander("🏁 Round scoring debug", expanded=False):
                st.caption(
                    "For each entry's picks: shows cumulative vs-par through each round "
                    "(from score_map or linescores) and the per-round delta used to pick the round winner. "
                    "Use this to cross-check when Sunday / Saturday scoring looks off."
                )
                for r in rows[:15]:
                    st.markdown(f"**{r['Name']}**")
                    for pname, _psc in r["Picks"]:
                        cums = {}
                        for _rn in (1, 2, 3, 4):
                            cums[_rn] = cumulative_vs_par(pname, _rn, rounds_vs_par, score_map, current_period, espn_state)
                        deltas = {}
                        for _rn in (1, 2, 3, 4):
                            deltas[_rn] = round_delta_vs_par(pname, _rn, rounds_vs_par, score_map, current_period, espn_state)
                        st.caption(
                            f"• `{pname}` — cum: {cums} · round deltas: {deltas} · "
                            f"score_map={score_map.get(pname, '—')} · raw_linescores={[row.get('value') for row in raw_linescores.get(pname, [])]}"
                        )
                    st.markdown("")

            st.markdown("---")

            # ── Clear sheet cache ──
            if st.button("🔄 Refresh entries from sheet"):
                load_sheet.clear()
                get_scores.clear()
                st.rerun()

            st.markdown("---")

            st.caption("⚠️ **Danger zone** — wipes all admin settings (payments, snapshots, overrides, history). Use only to start fresh.")
            _reset_ok = st.checkbox("I understand this wipes EVERYTHING", key="confirm_reset_all")
            if st.button("⚠️ Reset ALL admin settings", disabled=not _reset_ok):
                st.session_state.admin_state = dict(DEFAULT_STATE)
                save_state(st.session_state.admin_state)
                st.rerun()

        elif pwd != "":
            st.error("Incorrect password.")

# Floating gear icon — always visible, low-opacity by default.
# Clicking it appends ?admin=1 to the URL which triggers the admin panel above.
# Floating help icon sits to its left and toggles the How It Works panel.
st.markdown(
    '<a href="?admin=1" class="admin-gear" title="Admin">⚙</a>',
    unsafe_allow_html=True
)

st.markdown("<br><br>", unsafe_allow_html=True)
