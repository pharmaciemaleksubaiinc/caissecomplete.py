# caisse200+.py
# Registre — Caisse & Boîte (Échange)
# FULL rewrite (report style + fixed borders + +/- in RETRAIT)
# - Auth
# - Mode dropdown (Ouverture normale / Fermeture non effectuée)
# - Report-like condensed grid with continuous borders (NO interrupted lines)
# - RETRAIT editable IN-table with [-] [value] [+] (ATM vibe)
# - Boîte headers: OPEN / AJOUTÉ / RETRAIT (en change) / RESTANT
# - No st.data_editor, no nested-columns error, no reset-to-0 "enter" bug
# - Receipts + daily save

import os
import json
import hashlib
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components


# ================== CONFIG ==================
st.set_page_config(page_title="Registre — Caisse & Boîte", layout="wide")
TZ = ZoneInfo("America/Toronto")

BASE_DIR = "data"
DIR_CAISSE = os.path.join(BASE_DIR, "records_caisse")
DIR_BOITE = os.path.join(BASE_DIR, "records_boite")
os.makedirs(DIR_CAISSE, exist_ok=True)
os.makedirs(DIR_BOITE, exist_ok=True)

# ================== STYLE (REPORT LOOK + REAL BORDERS) ==================
st.markdown(
    """
<style>
/* Density */
.main .block-container { padding-top: 0.55rem !important; padding-bottom: 0.8rem !important; max-width: 1600px !important; }
h1,h2,h3 { margin-bottom: 0.2rem !important; }
div[data-testid="stElementContainer"] { margin-bottom: 0.14rem !important; }
div[data-testid="stVerticalBlock"] { gap: 0.12rem !important; }

/* --- Cell boxing done the RIGHT way ---
   We drop a tiny sentinel span inside each "cell".
   Then we style the Streamlit column vertical block that "has" that sentinel.
   That way the border wraps BOTH markdown + widgets, without broken lines.
*/
div[data-testid="stVerticalBlock"]:has(span.rep-cell-sentinel) {
  border: 1px solid #2a2a2a !important;
  padding: 6px 8px !important;
  background: #fff;
  overflow: hidden;
}
div[data-testid="stVerticalBlock"]:has(span.rep-head-sentinel) {
  background: #f3f3f3 !important;
  font-weight: 900;
  text-align: center;
}

/* Head text */
.rep-head-text { font-size: 13px; font-weight: 900; text-align:center; }

/* Denom + numbers */
.rep-denom { font-size: 13px; font-weight: 850; }
.rep-num { font-size: 13px; font-weight: 900; text-align:center; }

/* RETRAIT cell tint */
div[data-testid="stVerticalBlock"].rep-retrait-cell {
  background: rgba(30,136,229,0.08) !important;
}

/* Number inputs: make them look like plain typed cells */
div[data-testid="stNumberInput"] { margin-bottom: 0 !important; }
div[data-testid="stNumberInput"] label { display:none !important; }
div[data-testid="stNumberInput"] input{
  height: 1.55rem !important;
  padding: 0 !important;
  border: 0 !important;
  background: transparent !important;
  box-shadow: none !important;
  font-weight: 900 !important;
  text-align: center !important;
}
div[data-testid="stNumberInput"] button { display:none !important; } /* hide default +/- */

/* Focus ring */
div[data-testid="stNumberInput"] input:focus{
  outline: none !important;
  box-shadow: inset 0 0 0 2px rgba(30,136,229,0.35) !important;
  border-radius: 6px !important;
}

/* Small +/- buttons for RETRAIT */
button[kind="secondary"].rep-mini-btn {
  padding: 0.15rem 0.35rem !important;
  border-radius: 6px !important;
  font-weight: 950 !important;
  min-height: 1.55rem !important;
  line-height: 1.0 !important;
}
div[data-testid="stButton"] { margin: 0 !important; }

/* Tight divider */
.hr-tight { margin: 0.35rem 0 0.55rem 0; border: 0; border-top: 1px solid rgba(0,0,0,0.15); }
</style>
""",
    unsafe_allow_html=True,
)

# ================== DENOMS ==================
DENOMS = {
    "Billet 100 $": 10000,
    "Billet 50 $": 5000,
    "Billet 20 $": 2000,
    "Billet 10 $": 1000,
    "Billet 5 $": 500,
    "Pièce 2 $": 200,
    "Pièce 1 $": 100,
    "Pièce 0,25 $": 25,
    "Pièce 0,10 $": 10,
    "Pièce 0,05 $": 5,
    "Rouleau 2 $ (25) — 50 $": 5000,
    "Rouleau 1 $ (25) — 25 $": 2500,
    "Rouleau 0,25 $ (40) — 10 $": 1000,
    "Rouleau 0,10 $ (50) — 5 $": 500,
    "Rouleau 0,05 $ (40) — 2 $": 200,
}

BILLS_BIG = ["Billet 100 $", "Billet 50 $", "Billet 20 $"]
BILLS_SMALL = ["Billet 10 $", "Billet 5 $"]
COINS = ["Pièce 2 $", "Pièce 1 $", "Pièce 0,25 $", "Pièce 0,10 $", "Pièce 0,05 $"]
ROLLS = [
    "Rouleau 2 $ (25) — 50 $",
    "Rouleau 1 $ (25) — 25 $",
    "Rouleau 0,25 $ (40) — 10 $",
    "Rouleau 0,10 $ (50) — 5 $",
    "Rouleau 0,05 $ (40) — 2 $",
]
DISPLAY_ORDER = BILLS_BIG + BILLS_SMALL + COINS + ROLLS

# ================== HELPERS ==================
def cents_to_str(c: int) -> str:
    return f"{c/100:.2f} $"

def total_cents(counts: dict) -> int:
    return sum(int(counts.get(k, 0)) * DENOMS[k] for k in DENOMS)

def sub_counts(a: dict, b: dict) -> dict:
    return {k: int(a.get(k, 0)) - int(b.get(k, 0)) for k in DENOMS}

def add_counts(a: dict, b: dict) -> dict:
    return {k: int(a.get(k, 0)) + int(b.get(k, 0)) for k in DENOMS}

def clamp_locked(locked: dict, avail: dict) -> dict:
    out = {}
    for k, v in (locked or {}).items():
        v = int(v)
        if v < 0:
            v = 0
        mx = int(avail.get(k, 0))
        if v > mx:
            v = mx
        out[k] = v
    return out

def take_greedy(remaining: int, keys_order: list, avail: dict, out: dict, locked: dict) -> int:
    for k in keys_order:
        if remaining <= 0:
            break
        if k in locked:
            continue
        v = DENOMS[k]
        can_take = int(avail.get(k, 0)) - int(out.get(k, 0))
        if can_take < 0:
            can_take = 0
        take = min(remaining // v, can_take)
        if take > 0:
            out[k] = int(out.get(k, 0)) + int(take)
            remaining -= int(take) * v
    return remaining

def suggest(amount_cents: int, allowed: list, avail: dict, locked: dict, priority: list):
    out = {k: 0 for k in DENOMS}
    for k, q in (locked or {}).items():
        out[k] = int(q)

    remaining = amount_cents - total_cents(out)
    if remaining < 0:
        return out, remaining

    allowed_set = set(allowed)
    prio = [k for k in priority if k in allowed_set]
    remaining = take_greedy(remaining, prio, avail, out, locked or {})
    return out, remaining

def hash_payload(obj: dict) -> str:
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def save_json(path: str, payload: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def load_json(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_text(path: str, txt: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt)

def load_text(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def list_dates(folder: str):
    files = sorted([f for f in os.listdir(folder) if f.endswith("_state.json")])
    return [f.replace("_state.json", "") for f in files]

def caisse_paths(d: date):
    ds = d.isoformat()
    return (
        os.path.join(DIR_CAISSE, f"{ds}_state.json"),
        os.path.join(DIR_CAISSE, f"{ds}_receipt.html"),
    )

def boite_paths(d: date):
    ds = d.isoformat()
    return (
        os.path.join(DIR_BOITE, f"{ds}_state.json"),
        os.path.join(DIR_BOITE, f"{ds}_receipt.html"),
    )

def receipt_html(title: str, meta: dict, headers: list, rows: list) -> str:
    meta_html = "".join([f"<div><b>{k}:</b> {v}</div>" for k, v in meta.items()])
    thead = "".join([f"<th>{h}</th>" for h in headers])
    body = ""
    for r in rows:
        tds = []
        for i, h in enumerate(headers):
            val = r.get(h, "")
            if i == 0:
                tds.append(f"<td><b>{val}</b></td>")
            else:
                tds.append(f"<td style='text-align:center'><b>{val}</b></td>")
        body += "<tr>" + "".join(tds) + "</tr>"

    return f"""
    <html><head><meta charset="utf-8"/><title>{title}</title>
    <style>
      body{{font-family:Arial,sans-serif;padding:18px;color:#111}}
      .top{{display:flex;justify-content:space-between;gap:16px}}
      .meta{{font-size:13px;opacity:.95}}
      table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:14px}}
      th,td{{border:1px solid #222;padding:6px}}
      th{{background:#f0f0f0;font-weight:900}}
      .btnbar{{margin-top:12px}}
      button{{padding:10px 14px;border-radius:10px;border:1px solid #bbb;background:#fff;cursor:pointer;font-weight:700}}
      @media print{{.btnbar{{display:none}} body{{padding:0}}}}
    </style></head>
    <body>
      <div class="top">
        <div><h2 style="margin:0">{title}</h2><div style="opacity:.7;font-size:12px">Imprime avec le bouton.</div></div>
        <div class="meta">{meta_html}</div>
      </div>
      <div class="btnbar"><button onclick="window.print()">🖨️ Imprimer</button></div>
      <table>
        <thead><tr>{thead}</tr></thead>
        <tbody>{body}</tbody>
      </table>
    </body></html>
    """

# ================== SESSION HELPERS ==================
def ensure_counts(prefix: str, keys: list):
    if prefix not in st.session_state:
        st.session_state[prefix] = {k: 0 for k in keys}

def get_counts(prefix: str) -> dict:
    return dict(st.session_state.get(prefix, {}))

def set_count(prefix: str, k: str, v: int):
    st.session_state[prefix][k] = int(v)

def seed_int(key: str, default: int):
    if key not in st.session_state:
        st.session_state[key] = int(default)

def bump_int(key: str, delta: int, mn: int, mx: int, lock_name=None, denom=None):
    v = int(st.session_state.get(key, 0))
    v = max(mn, min(mx, v + delta))
    st.session_state[key] = v
    if lock_name and denom is not None:
        locked = dict(st.session_state.get(lock_name, {}) or {})
        locked[denom] = v
        st.session_state[lock_name] = locked

def lock_from_widget(lock_name: str, denom: str, widget_key: str, mx: int):
    locked = dict(st.session_state.get(lock_name, {}) or {})
    v = int(st.session_state.get(widget_key, 0))
    v = max(0, min(int(mx), v))
    locked[denom] = v
    st.session_state[lock_name] = locked

# ================== REPORT GRID RENDER ==================
COLS = [3.25, 1.15, 1.25, 2.7, 1.35]  # denom, col1, col2, retrait, restant

def rep_head_cell(col, text):
    col.markdown("<span class='rep-head-sentinel rep-cell-sentinel'></span>", unsafe_allow_html=True)
    col.markdown(f"<div class='rep-head-text'>{text}</div>", unsafe_allow_html=True)

def rep_cell_sentinel(col, extra_class=""):
    # sentinel to let CSS wrap border around this column's block
    col.markdown(f"<span class='rep-cell-sentinel {extra_class}'></span>", unsafe_allow_html=True)

def report_grid(
    keys_order: list,
    col1_prefix: str,
    col2_prefix: str,
    avail_for_retrait: dict,
    retrait_suggested: dict,
    restant_counts: dict,
    allow_edit_col1: bool,
    allow_edit_col2: bool,
    allow_edit_retrait: bool,
    lock_name: str,
    widget_prefix: str,
    headers: tuple,  # ("OPEN", "CLOSE", "RETRAIT", "RESTANT")
):
    ensure_counts(col1_prefix, keys_order)
    ensure_counts(col2_prefix, keys_order)

    # Header row
    head = st.columns(COLS, vertical_alignment="center")
    rep_head_cell(head[0], "Dénomination")
    rep_head_cell(head[1], headers[0])
    rep_head_cell(head[2], headers[1])
    rep_head_cell(head[3], headers[2])
    rep_head_cell(head[4], headers[3])

    locked = dict(st.session_state.get(lock_name, {}) or {})

    for k in keys_order:
        row = st.columns(COLS, vertical_alignment="center")

        # denom
        rep_cell_sentinel(row[0])
        row[0].markdown(f"<div class='rep-denom'>{k}</div>", unsafe_allow_html=True)

        # col1
        rep_cell_sentinel(row[1])
        v1 = int(st.session_state[col1_prefix].get(k, 0))
        w1 = f"{widget_prefix}__c1__{k}"
        seed_int(w1, v1)
        if allow_edit_col1:
            val = row[1].number_input("", min_value=0, step=1, key=w1)
            set_count(col1_prefix, k, val)
        else:
            row[1].markdown(f"<div class='rep-num'>{v1}</div>", unsafe_allow_html=True)

        # col2
        rep_cell_sentinel(row[2])
        v2 = int(st.session_state[col2_prefix].get(k, 0))
        w2 = f"{widget_prefix}__c2__{k}"
        seed_int(w2, v2)
        if allow_edit_col2:
            val = row[2].number_input("", min_value=0, step=1, key=w2)
            set_count(col2_prefix, k, val)
        else:
            row[2].markdown(f"<div class='rep-num'>{v2}</div>", unsafe_allow_html=True)

        # retrait with +/- (one level nested columns ONLY)
        rep_cell_sentinel(row[3])
        # mark this cell as retrait for background tint
        # we can't set class directly, so we add a tiny marker and use :has in CSS
        row[3].markdown("<span class='rep-retrait-marker'></span>", unsafe_allow_html=True)

        q_suggest = int(retrait_suggested.get(k, 0))
        mx = int(avail_for_retrait.get(k, 0))
        w3 = f"{widget_prefix}__ret__{k}"

        # Sync suggestion until user edits (locks)
        if k not in locked:
            st.session_state[w3] = q_suggest
        seed_int(w3, q_suggest)

        # add background tint by tagging the vertical block via JS-less trick:
        # we style any stVerticalBlock that has the marker.
        st.markdown(
            """
<style>
div[data-testid="stVerticalBlock"]:has(span.rep-retrait-marker){
  background: rgba(30,136,229,0.08) !important;
}
</style>
""",
            unsafe_allow_html=True,
        )

        if allow_edit_retrait:
            c_minus, c_val, c_plus = row[3].columns([0.18, 0.64, 0.18], vertical_alignment="center")
            c_minus.button(
                "−",
                key=f"{w3}_minus",
                on_click=bump_int,
                kwargs={"key": w3, "delta": -1, "mn": 0, "mx": mx, "lock_name": lock_name, "denom": k},
                type="secondary",
                use_container_width=True,
            )
            # apply class to button via CSS (Streamlit doesn't let us, so we style all secondary buttons in this layout)
            c_val.number_input(
                "",
                min_value=0,
                max_value=mx,
                step=1,
                key=w3,
                on_change=lock_from_widget,
                kwargs={"lock_name": lock_name, "denom": k, "widget_key": w3, "mx": mx},
            )
            c_plus.button(
                "+",
                key=f"{w3}_plus",
                on_click=bump_int,
                kwargs={"key": w3, "delta": 1, "mn": 0, "mx": mx, "lock_name": lock_name, "denom": k},
                type="secondary",
                use_container_width=True,
            )
        else:
            row[3].markdown(f"<div class='rep-num'>{q_suggest}</div>", unsafe_allow_html=True)

        # restant
        rep_cell_sentinel(row[4])
        row[4].markdown(f"<div class='rep-num'>{int(restant_counts.get(k, 0))}</div>", unsafe_allow_html=True)

def report_total_row(label: str, v1: str, v2: str, v3: str, v4: str):
    row = st.columns(COLS, vertical_alignment="center")

    rep_cell_sentinel(row[0])
    row[0].markdown(f"<div class='rep-denom' style='font-weight:950'>{label}</div>", unsafe_allow_html=True)

    for col, val in zip(row[1:], [v1, v2, v3, v4]):
        rep_cell_sentinel(col)
        col.markdown(f"<div class='rep-num' style='font-weight:950'>{val}</div>", unsafe_allow_html=True)


# ================== AUTH ==================
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("Accès protégé")
    pwd = st.text_input("Mot de passe", type="password", key="pwd")
    if st.button("Se connecter", key="login_btn"):
        if pwd == st.secrets.get("APP_PASSWORD"):
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("Mot de passe incorrect.")
    st.stop()

# ================== GLOBAL STATE ==================
today = datetime.now(TZ).date()
yesterday = today - timedelta(days=1)

if "mode_pick" not in st.session_state:
    st.session_state.mode_pick = "normal"

if "cashier" not in st.session_state:
    st.session_state.cashier = ""
if "register_no" not in st.session_state:
    st.session_state.register_no = 1
if "target_dollars" not in st.session_state:
    st.session_state.target_dollars = 200

if "locked_retrait_caisse" not in st.session_state:
    st.session_state.locked_retrait_caisse = {}
if "locked_retrait_hier" not in st.session_state:
    st.session_state.locked_retrait_hier = {}
if "locked_withdraw_boite" not in st.session_state:
    st.session_state.locked_withdraw_boite = {}

if "boite_allowed" not in st.session_state:
    st.session_state.boite_allowed = set(["Billet 20 $", "Billet 10 $", "Billet 5 $"] + COINS + ROLLS)

if "last_hash_caisse" not in st.session_state:
    st.session_state.last_hash_caisse = None
if "last_hash_boite" not in st.session_state:
    st.session_state.last_hash_boite = None

if "booted_for" not in st.session_state:
    st.session_state.booted_for = None

def apply_mode_change(new_mode: str):
    old = st.session_state.mode_pick
    st.session_state.mode_pick = new_mode
    if old != new_mode:
        st.session_state.locked_retrait_caisse = {}
        st.session_state.locked_retrait_hier = {}
        st.rerun()

# Load saved state once per day
if st.session_state.booted_for != today.isoformat():
    st.session_state.booted_for = today.isoformat()

    # Caisse saved
    state_path_c, _ = (os.path.join(DIR_CAISSE, f"{today.isoformat()}_state.json"),
                       os.path.join(DIR_CAISSE, f"{today.isoformat()}_receipt.html"))
    saved = load_json(state_path_c)
    if saved:
        meta = saved.get("meta", {})
        st.session_state.cashier = meta.get("Caissier(ère)", st.session_state.cashier)
        st.session_state.register_no = int(meta.get("Caisse #", st.session_state.register_no))
        st.session_state.target_dollars = int(meta.get("Cible $", st.session_state.target_dollars))
        st.session_state.mode_pick = saved.get("mode_pick", st.session_state.mode_pick)

        counts = saved.get("counts", {})
        for name, dct in counts.items():
            if isinstance(dct, dict):
                st.session_state[name] = dct

        st.session_state.locked_retrait_caisse = saved.get("locked_retrait_caisse", {}) or {}
        st.session_state.locked_retrait_hier = saved.get("locked_retrait_hier", {}) or {}

    # Boîte saved
    state_path_b, _ = (os.path.join(DIR_BOITE, f"{today.isoformat()}_state.json"),
                       os.path.join(DIR_BOITE, f"{today.isoformat()}_receipt.html"))
    savedb = load_json(state_path_b)
    if savedb:
        st.session_state.boite_allowed = set(savedb.get("boite_allowed", list(st.session_state.boite_allowed)))
        counts = savedb.get("counts", {})
        for name, dct in counts.items():
            if isinstance(dct, dict):
                st.session_state[name] = dct
        st.session_state.locked_withdraw_boite = savedb.get("locked_withdraw_boite", {}) or {}

# ================== HEADER ==================
st.title("Registre — Caisse & Boîte de monnaie")

h1, h2, h3, h4 = st.columns([1.1, 1.0, 1.2, 2.0])
with h1:
    st.write("**Date:**", today.isoformat())
with h2:
    st.write("**Heure:**", datetime.now(TZ).strftime("%H:%M"))
with h3:
    st.session_state.register_no = st.selectbox("Caisse #", [1, 2, 3], index=[1, 2, 3].index(int(st.session_state.register_no)), key="reg_sel")
with h4:
    st.session_state.cashier = st.text_input("Caissier(ère)", value=st.session_state.cashier, key="cashier_txt")

st.session_state.target_dollars = st.number_input("Cible à laisser ($)", min_value=0, step=10, value=int(st.session_state.target_dollars), key="target_num")

st.markdown("<hr class='hr-tight'/>", unsafe_allow_html=True)
tab_caisse, tab_boite, tab_save = st.tabs(["1) Caisse", "2) Boîte (Échange)", "3) Sauvegarde & reçus"])


# ================== TAB: CAISSE ==================
with tab_caisse:
    TARGET = int(st.session_state.target_dollars) * 100

    coins_desc = sorted(COINS, key=lambda x: DENOMS[x], reverse=True)
    rolls_desc = sorted(ROLLS, key=lambda x: DENOMS[x], reverse=True)
    PRIORITY_CAISSE = BILLS_BIG + BILLS_SMALL + coins_desc + rolls_desc

    st.subheader("Caisse")

    mode_labels = {"normal": "Ouverture normale", "missed_close": "Fermeture non effectuée (hier)"}
    mode_options = ["normal", "missed_close"]
    idx = mode_options.index(st.session_state.mode_pick) if st.session_state.mode_pick in mode_options else 0
    picked = st.selectbox("Mode", options=mode_options, format_func=lambda x: mode_labels.get(x, x), index=idx, key="mode_dropdown")
    if picked != st.session_state.mode_pick:
        apply_mode_change(picked)

    OPEN_T = "caisse_open_today"
    CLOSE_T = "caisse_close_today"
    CLOSE_Y = "caisse_close_yesterday"
    ensure_counts(OPEN_T, DISPLAY_ORDER)
    ensure_counts(CLOSE_T, DISPLAY_ORDER)
    ensure_counts(CLOSE_Y, DISPLAY_ORDER)

    # ---------------- YESTERDAY (MISSED CLOSE) ----------------
    if st.session_state.mode_pick == "missed_close":
        st.markdown("#### ⚠️ Hier — fermeture non effectuée")
        st.caption("Entre le CLOSE d'hier, puis ajuste le RETRAIT (colonne bleue). OPEN d'aujourd'hui = RESTANT d'hier.")

        close_y = get_counts(CLOSE_Y)
        total_close_y = total_cents(close_y)
        diff_y = total_close_y - TARGET

        retrait_y = {k: 0 for k in DISPLAY_ORDER}
        restant_y = dict(close_y)

        if diff_y > 0:
            st.session_state.locked_retrait_hier = clamp_locked(st.session_state.locked_retrait_hier, close_y)
            retrait_y_full, _ = suggest(
                diff_y,
                allowed=DISPLAY_ORDER,
                avail=close_y,
                locked=dict(st.session_state.locked_retrait_hier),
                priority=PRIORITY_CAISSE,
            )
            retrait_y = dict(retrait_y_full)
            restant_y = sub_counts(close_y, retrait_y)

        report_grid(
            keys_order=DISPLAY_ORDER,
            col1_prefix="__dummy_open_y",
            col2_prefix=CLOSE_Y,
            avail_for_retrait=close_y,
            retrait_suggested=retrait_y,
            restant_counts=restant_y,
            allow_edit_col1=False,
            allow_edit_col2=True,
            allow_edit_retrait=(diff_y > 0),
            lock_name="locked_retrait_hier",
            widget_prefix="YEST",
            headers=("OPEN", "CLOSE", "RETRAIT", "RESTANT"),
        )

        report_total_row(
            "TOTAL ($)",
            f"{0/100:.2f}",
            f"{total_close_y/100:.2f}",
            f"{total_cents(retrait_y)/100:.2f}",
            f"{total_cents(restant_y)/100:.2f}",
        )

        if st.button("Reset ajustements retrait (hier)", key="reset_lock_y"):
            st.session_state.locked_retrait_hier = {}
            st.rerun()

        # OPEN today = RESTANT yesterday
        open_today_dict = get_counts(OPEN_T)
        for k in DISPLAY_ORDER:
            open_today_dict[k] = int(restant_y.get(k, 0))
        st.session_state[OPEN_T] = open_today_dict

        st.markdown("<hr class='hr-tight'/>", unsafe_allow_html=True)

    # ---------------- TODAY ----------------
    open_today = get_counts(OPEN_T)
    close_today = get_counts(CLOSE_T)

    total_open_today = total_cents(open_today)
    total_close_today = total_cents(close_today)
    diff_today = total_close_today - TARGET

    retrait_today = {k: 0 for k in DISPLAY_ORDER}
    restant_today = dict(close_today)
    remaining_today = 0

    if diff_today > 0:
        st.session_state.locked_retrait_caisse = clamp_locked(st.session_state.locked_retrait_caisse, close_today)
        retrait_today_full, remaining_today = suggest(
            diff_today,
            allowed=DISPLAY_ORDER,
            avail=close_today,
            locked=dict(st.session_state.locked_retrait_caisse),
            priority=PRIORITY_CAISSE,
        )
        retrait_today = dict(retrait_today_full)
        restant_today = sub_counts(close_today, retrait_today)

    report_grid(
        keys_order=DISPLAY_ORDER,
        col1_prefix=OPEN_T,
        col2_prefix=CLOSE_T,
        avail_for_retrait=close_today,
        retrait_suggested=retrait_today,
        restant_counts=restant_today,
        allow_edit_col1=(st.session_state.mode_pick == "normal"),
        allow_edit_col2=True,
        allow_edit_retrait=(diff_today > 0),
        lock_name="locked_retrait_caisse",
        widget_prefix="TODAY",
        headers=("OPEN", "CLOSE", "RETRAIT", "RESTANT"),
    )

    report_total_row(
        "TOTAL ($)",
        f"{total_open_today/100:.2f}",
        f"{total_close_today/100:.2f}",
        f"{total_cents(retrait_today)/100:.2f}",
        f"{total_cents(restant_today)/100:.2f}",
    )

    if st.button("Reset ajustements retrait (aujourd'hui)", key="reset_lock_t"):
        st.session_state.locked_retrait_caisse = {}
        st.rerun()

    if diff_today <= 0:
        st.info("Sous la cible (ou égal). Aucun retrait.")
    else:
        if remaining_today == 0:
            st.success("Retrait aujourd'hui: " + cents_to_str(total_cents(retrait_today)))
        elif remaining_today < 0:
            st.warning("Verrouillage trop haut. Dépasse de " + cents_to_str(-remaining_today))
        else:
            st.warning("Impossible exact. Reste: " + cents_to_str(remaining_today))

    # Receipt rows (today)
    rows_today = []
    for k in DISPLAY_ORDER:
        rows_today.append({
            "Dénomination": k,
            "OPEN": int(open_today.get(k, 0)),
            "CLOSE": int(close_today.get(k, 0)),
            "RETRAIT": int(retrait_today.get(k, 0)),
            "RESTANT": int(restant_today.get(k, 0)),
        })
    rows_today.append({
        "Dénomination": "TOTAL ($)",
        "OPEN": f"{total_open_today/100:.2f}",
        "CLOSE": f"{total_close_today/100:.2f}",
        "RETRAIT": f"{total_cents(retrait_today)/100:.2f}",
        "RESTANT": f"{total_cents(restant_today)/100:.2f}",
    })

    meta_caisse = {
        "Type": "CAISSE",
        "Date": today.isoformat(),
        "Généré à": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "Caisse #": int(st.session_state.register_no),
        "Caissier(ère)": (st.session_state.cashier.strip() or "—"),
        "Cible $": int(st.session_state.target_dollars),
        "Mode": mode_labels.get(st.session_state.mode_pick, st.session_state.mode_pick),
    }

    payload_caisse = {
        "meta": meta_caisse,
        "mode_pick": st.session_state.mode_pick,
        "counts": {
            OPEN_T: st.session_state[OPEN_T],
            CLOSE_T: st.session_state[CLOSE_T],
            CLOSE_Y: st.session_state[CLOSE_Y] if st.session_state.mode_pick == "missed_close" else {k: 0 for k in DISPLAY_ORDER},
        },
        "locked_retrait_caisse": st.session_state.locked_retrait_caisse,
        "locked_retrait_hier": st.session_state.locked_retrait_hier,
        "rows_today": rows_today,
    }

    state_path, receipt_path = caisse_paths(today)
    hc = hash_payload(payload_caisse)
    if st.session_state.last_hash_caisse != hc:
        html = receipt_html("Reçu — Caisse", meta_caisse, ["Dénomination", "OPEN", "CLOSE", "RETRAIT", "RESTANT"], rows_today)
        save_json(state_path, payload_caisse)
        save_text(receipt_path, html)
        st.session_state.last_hash_caisse = hc

    st.markdown("### Aperçu reçu — Caisse")
    components.html(load_text(receipt_path) or "", height=560, scrolling=True)


# ================== TAB: BOÎTE ==================
with tab_boite:
    st.subheader("Boîte (Échange)")
    st.caption("Boîte: OPEN (avant), AJOUTÉ (dépôt), RETRAIT (en change) (bleu), RESTANT (après).")

    with st.expander("⚙️ Types autorisés pour le change", expanded=True):
        allowed = set(st.session_state.boite_allowed)
        c1, c2, c3 = st.columns(3)
        cols = [c1, c2, c3]
        for i, k in enumerate(DISPLAY_ORDER):
            with cols[i % 3]:
                checked = k in allowed
                if st.checkbox(k, value=checked, key=f"allow_boite_{k}"):
                    allowed.add(k)
                else:
                    allowed.discard(k)
        if not allowed:
            st.warning("Choisis au moins un type autorisé.")
        st.session_state.boite_allowed = allowed

    OPEN_B = "boite_open"
    ADD_B = "boite_added"
    ensure_counts(OPEN_B, DISPLAY_ORDER)
    ensure_counts(ADD_B, DISPLAY_ORDER)

    box_open = get_counts(OPEN_B)
    box_added = get_counts(ADD_B)

    total_open = total_cents(box_open)
    total_added = total_cents(box_added)

    after_added = add_counts(box_open, box_added)

    PRIORITY_BOITE = (
        ["Billet 20 $", "Billet 10 $", "Billet 5 $"]
        + ["Pièce 2 $", "Pièce 1 $", "Pièce 0,25 $", "Pièce 0,10 $", "Pièce 0,05 $"]
        + ROLLS
        + ["Billet 50 $", "Billet 100 $"]
    )

    retrait_change = {k: 0 for k in DISPLAY_ORDER}
    restant_boite = dict(after_added)
    remaining_boite = 0

    can_compute = total_added > 0 and bool(st.session_state.boite_allowed)

    if can_compute:
        st.session_state.locked_withdraw_boite = clamp_locked(st.session_state.locked_withdraw_boite, after_added)
        withdraw_full, remaining_boite = suggest(
            total_added,
            allowed=list(st.session_state.boite_allowed),
            avail=after_added,
            locked=dict(st.session_state.locked_withdraw_boite),
            priority=PRIORITY_BOITE,
        )
        retrait_change = dict(withdraw_full)
        restant_boite = sub_counts(after_added, retrait_change)

    report_grid(
        keys_order=DISPLAY_ORDER,
        col1_prefix=OPEN_B,
        col2_prefix=ADD_B,
        avail_for_retrait=after_added,
        retrait_suggested=retrait_change,
        restant_counts=restant_boite,
        allow_edit_col1=True,
        allow_edit_col2=True,
        allow_edit_retrait=can_compute,
        lock_name="locked_withdraw_boite",
        widget_prefix="BOITE",
        headers=("OPEN", "AJOUTÉ", "RETRAIT (en change)", "RESTANT"),
    )

    report_total_row(
        "TOTAL ($)",
        f"{total_open/100:.2f}",
        f"{total_added/100:.2f}",
        f"{total_cents(retrait_change)/100:.2f}",
        f"{total_cents(restant_boite)/100:.2f}",
    )

    if st.button("Reset ajustements (boîte)", key="reset_lock_boite"):
        st.session_state.locked_withdraw_boite = {}
        st.rerun()

    if total_added == 0:
        st.info("Ajouté = 0. Rien à calculer.")
    elif not st.session_state.boite_allowed:
        st.error("Aucun type autorisé.")
    else:
        if remaining_boite == 0:
            st.success("Change retiré: " + cents_to_str(total_cents(retrait_change)))
        elif remaining_boite < 0:
            st.warning("Verrouillage trop haut. Dépasse de " + cents_to_str(-remaining_boite))
        else:
            st.warning("Impossible exact. Reste: " + cents_to_str(remaining_boite))

    # Receipt (boîte)
    rows_boite = []
    for k in DISPLAY_ORDER:
        rows_boite.append({
            "Dénomination": k,
            "OPEN": int(box_open.get(k, 0)),
            "AJOUTÉ": int(box_added.get(k, 0)),
            "RETRAIT (en change)": int(retrait_change.get(k, 0)),
            "RESTANT": int(restant_boite.get(k, 0)),
        })
    rows_boite.append({
        "Dénomination": "TOTAL ($)",
        "OPEN": f"{total_open/100:.2f}",
        "AJOUTÉ": f"{total_added/100:.2f}",
        "RETRAIT (en change)": f"{total_cents(retrait_change)/100:.2f}",
        "RESTANT": f"{total_cents(restant_boite)/100:.2f}",
    })

    meta_boite = {
        "Type": "BOÎTE (ÉCHANGE)",
        "Date": today.isoformat(),
        "Généré à": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "Caissier(ère)": (st.session_state.cashier.strip() or "—"),
        "Caisse #": int(st.session_state.register_no),
        "Ajouté total ($)": f"{total_added/100:.2f}",
    }

    payload_boite = {
        "meta": meta_boite,
        "boite_allowed": sorted(list(st.session_state.boite_allowed)),
        "counts": {OPEN_B: st.session_state[OPEN_B], ADD_B: st.session_state[ADD_B]},
        "locked_withdraw_boite": st.session_state.locked_withdraw_boite,
        "rows": rows_boite,
    }

    state_path_b, receipt_path_b = boite_paths(today)
    hb = hash_payload(payload_boite)
    if st.session_state.last_hash_boite != hb:
        htmlb = receipt_html(
            "Reçu — Boîte (Échange)",
            meta_boite,
            ["Dénomination", "OPEN", "AJOUTÉ", "RETRAIT (en change)", "RESTANT"],
            rows_boite,
        )
        save_json(state_path_b, payload_boite)
        save_text(receipt_path_b, htmlb)
        st.session_state.last_hash_boite = hb

    st.markdown("### Aperçu reçu — Boîte (Échange)")
    components.html(load_text(receipt_path_b) or "", height=560, scrolling=True)


# ================== TAB: SAUVEGARDE ==================
with tab_save:
    st.subheader("Sauvegarde & reçus")
    st.caption("Clique une date pour voir le reçu détaillé et télécharger les fichiers.")

    colA, colB = st.columns(2)

    with colA:
        st.markdown("## 📒 Caisse")
        dates = list_dates(DIR_CAISSE)
        if not dates:
            st.info("Aucun enregistrement Caisse.")
        else:
            for ds in reversed(dates):
                d = date.fromisoformat(ds)
                state_path, receipt_path = caisse_paths(d)
                with st.expander(f"{ds} — Reçu Caisse", expanded=False):
                    html = load_text(receipt_path)
                    if html:
                        components.html(html, height=650, scrolling=True)
                    else:
                        st.warning("Reçu introuvable.")
                    if os.path.exists(receipt_path):
                        with open(receipt_path, "rb") as f:
                            st.download_button("⬇️ Télécharger reçu (HTML)", f.read(), os.path.basename(receipt_path), "text/html", key=f"dl_c_html_{ds}")
                    if os.path.exists(state_path):
                        with open(state_path, "rb") as f:
                            st.download_button("⬇️ Télécharger état (JSON)", f.read(), os.path.basename(state_path), "application/json", key=f"dl_c_json_{ds}")

    with colB:
        st.markdown("## 🪙 Boîte (Échange)")
        dates = list_dates(DIR_BOITE)
        if not dates:
            st.info("Aucun enregistrement Boîte.")
        else:
            for ds in reversed(dates):
                d = date.fromisoformat(ds)
                state_path, receipt_path = boite_paths(d)
                with st.expander(f"{ds} — Reçu Boîte (Échange)", expanded=False):
                    html = load_text(receipt_path)
                    if html:
                        components.html(html, height=650, scrolling=True)
                    else:
                        st.warning("Reçu introuvable.")
                    if os.path.exists(receipt_path):
                        with open(receipt_path, "rb") as f:
                            st.download_button("⬇️ Télécharger reçu (HTML)", f.read(), os.path.basename(receipt_path), "text/html", key=f"dl_b_html_{ds}")
                    if os.path.exists(state_path):
                        with open(state_path, "rb") as f:
                            st.download_button("⬇️ Télécharger état (JSON)", f.read(), os.path.basename(state_path), "application/json", key=f"dl_b_json_{ds}")
