# caisse200plus.py
# Registre — Caisse & Boîte (Échange)
# Compact "report-like" tables + no revert-to-0 + smart retrait steering + unlock UI

import os
import json
import hashlib
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
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


# ================== STYLE ==================
st.markdown(
    """
<style>
.main .block-container { padding-top: 0.55rem !important; padding-bottom: 0.75rem !important; max-width: 1650px !important; }
h1,h2,h3 { margin-bottom: 0.2rem !important; }
div[data-testid="stVerticalBlock"] { gap: 0.18rem !important; }

/* Report look (white, condensed) */
div[data-testid="stDataFrame"] { border: 2px solid #222 !important; border-radius: 0 !important; background:#fff !important; }
div[data-testid="stDataFrame"] * { font-size: 13px !important; }
div[data-testid="stDataFrame"] thead th { font-weight: 950 !important; background: #f2f2f2 !important; }
div[data-testid="stDataFrame"] tbody td { font-weight: 800 !important; background:#fff !important; }
div[data-testid="stDataFrame"] td, div[data-testid="stDataFrame"] th { padding-top: 6px !important; padding-bottom: 6px !important; }
div[data-testid="stDataFrame"] input { font-weight: 950 !important; text-align: center !important; }

button[kind="primary"], button[kind="secondary"] { font-weight: 900 !important; }
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

COINS_DESC = sorted(COINS, key=lambda x: DENOMS[x], reverse=True)
ROLLS_DESC = sorted(ROLLS, key=lambda x: DENOMS[x], reverse=True)

PRIORITY_CAISSE = BILLS_BIG + BILLS_SMALL + COINS_DESC + ROLLS_DESC
PRIORITY_BOITE = (
    ["Billet 20 $", "Billet 10 $", "Billet 5 $"]
    + ["Pièce 2 $", "Pièce 1 $", "Pièce 0,25 $", "Pièce 0,10 $", "Pièce 0,05 $"]
    + ROLLS
    + ["Billet 50 $", "Billet 100 $"]
)


# ================== HELPERS ==================
def cents_to_str(c: int) -> str:
    return f"{c/100:.2f} $"

def clean_int(x, default=0) -> int:
    if x is None:
        return default
    try:
        if pd.isna(x):
            return default
    except Exception:
        pass
    try:
        v = int(x)
    except Exception:
        return default
    return max(0, v)

def init_df(cols: list[str]) -> pd.DataFrame:
    df = pd.DataFrame({"Dénomination": DISPLAY_ORDER})
    for c in cols:
        df[c] = 0
    return df

def counts_from_df(df: pd.DataFrame, col: str) -> dict:
    out = {k: 0 for k in DISPLAY_ORDER}
    if not isinstance(df, pd.DataFrame) or col not in df.columns:
        return out
    for _, r in df.iterrows():
        denom = r.get("Dénomination")
        if denom in out:
            out[denom] = clean_int(r.get(col, 0), 0)
    return out

def total_cents_counts(counts: dict) -> int:
    return sum(int(counts.get(k, 0)) * DENOMS[k] for k in DENOMS)

def sub_counts(a: dict, b: dict) -> dict:
    return {k: int(a.get(k, 0)) - int(b.get(k, 0)) for k in DENOMS}

def add_counts(a: dict, b: dict) -> dict:
    return {k: int(a.get(k, 0)) + int(b.get(k, 0)) for k in DENOMS}

def merge_commit(base: pd.DataFrame, edited: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Commit edited values into base for specific cols (by denom)."""
    out = base.copy()
    if not isinstance(edited, pd.DataFrame) or "Dénomination" not in edited.columns:
        return out
    out = out.set_index("Dénomination")
    e = edited.set_index("Dénomination")
    for c in cols:
        if c not in out.columns:
            out[c] = 0
        if c not in e.columns:
            continue
        for denom in out.index:
            if denom in e.index:
                out.at[denom, c] = clean_int(e.at[denom, c], default=int(out.at[denom, c]))
    return out.reset_index()

def get_locks(lock_key: str) -> dict:
    if lock_key not in st.session_state:
        st.session_state[lock_key] = {}
    # ensure ints
    d = {}
    for k, v in dict(st.session_state[lock_key]).items():
        if k in DENOMS:
            d[k] = clean_int(v, 0)
    st.session_state[lock_key] = d
    return dict(d)

def set_locks(lock_key: str, d: dict):
    dd = {}
    for k, v in (d or {}).items():
        if k in DENOMS:
            dd[k] = clean_int(v, 0)
    st.session_state[lock_key] = dd

def render_unlock_ui(lock_key: str, title: str):
    locks = get_locks(lock_key)
    with st.expander(title, expanded=False):
        if not locks:
            st.info("Aucun verrou actif.")
            return
        c0, c1 = st.columns([1, 2])
        with c0:
            if st.button("Tout déverrouiller", key=f"{lock_key}_unlock_all"):
                set_locks(lock_key, {})
                st.rerun()
        st.markdown("**Verrous actifs (RETRAIT) :**")
        for denom in list(locks.keys()):
            a, b, c = st.columns([3.2, 1.2, 1.4])
            a.write(denom)
            b.write(f"**{int(locks[denom])}**")
            if c.button("Déverrouiller", key=f"{lock_key}_unlock_{denom}"):
                new = get_locks(lock_key)
                new.pop(denom, None)
                set_locks(lock_key, new)
                st.rerun()

def take_greedy(remaining: int, keys_order: list, avail: dict, out: dict, locked: dict) -> int:
    for k in keys_order:
        if remaining <= 0:
            break
        # if locked (even 0), we do not auto-use it
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

def suggest_with_locks(amount_cents: int, avail: dict, priority: list, locks: dict):
    """
    Build suggestion that sums to amount_cents using avail counts and greedy priority,
    respecting locks:
    - locks[k] = fixed qty (including 0 => "ban denom").
    """
    out = {k: 0 for k in DENOMS}
    # apply locks first
    for k, q in (locks or {}).items():
        out[k] = clean_int(q, 0)

    remaining = amount_cents - total_cents_counts(out)
    if remaining < 0:
        # locks already exceed target; still return out
        return out, remaining

    remaining = take_greedy(remaining, priority, avail, out, locks or {})
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

if "cashier" not in st.session_state:
    st.session_state.cashier = ""
if "register_no" not in st.session_state:
    st.session_state.register_no = 1
if "target_dollars" not in st.session_state:
    st.session_state.target_dollars = 200

# mode dropdown state
if "mode_pick" not in st.session_state:
    st.session_state.mode_pick = "normal"  # "normal" or "missed_close"

# editor base tables (committed)
if "df_caisse_today" not in st.session_state:
    st.session_state.df_caisse_today = init_df(["OPEN", "CLOSE", "RETRAIT", "RESTANT"])
if "df_caisse_yesterday" not in st.session_state:
    st.session_state.df_caisse_yesterday = init_df(["CLOSE", "RETRAIT", "RESTANT"])
if "df_boite" not in st.session_state:
    st.session_state.df_boite = init_df(["OPEN", "AJOUTÉ", "RETRAIT (en change)", "RESTANT"])

# locks
LOCK_T = "locks_retrait_caisse_today"
LOCK_Y = "locks_retrait_caisse_yesterday"
LOCK_B = "locks_retrait_boite"

# last committed RETRAIT snapshots for detecting what user changed
if "last_retrait_t" not in st.session_state:
    st.session_state.last_retrait_t = {k: 0 for k in DISPLAY_ORDER}
if "last_retrait_y" not in st.session_state:
    st.session_state.last_retrait_y = {k: 0 for k in DISPLAY_ORDER}
if "last_retrait_b" not in st.session_state:
    st.session_state.last_retrait_b = {k: 0 for k in DISPLAY_ORDER}

# autosave hashes
if "last_hash_caisse" not in st.session_state:
    st.session_state.last_hash_caisse = None
if "last_hash_boite" not in st.session_state:
    st.session_state.last_hash_boite = None

# boot-load saved state daily
if "booted_for" not in st.session_state:
    st.session_state.booted_for = None

if st.session_state.booted_for != today.isoformat():
    st.session_state.booted_for = today.isoformat()

    # load caisse state
    state_path_c, _ = caisse_paths(today)
    saved = load_json(state_path_c)
    if saved:
        meta = saved.get("meta", {})
        st.session_state.cashier = meta.get("Caissier(ère)", st.session_state.cashier)
        st.session_state.register_no = int(meta.get("Caisse #", st.session_state.register_no))
        st.session_state.target_dollars = int(meta.get("Cible $", st.session_state.target_dollars))
        st.session_state.mode_pick = saved.get("mode_pick", st.session_state.mode_pick)

        st.session_state.df_caisse_today = pd.DataFrame(saved.get("df_caisse_today", st.session_state.df_caisse_today))
        st.session_state.df_caisse_yesterday = pd.DataFrame(saved.get("df_caisse_yesterday", st.session_state.df_caisse_yesterday))

        set_locks(LOCK_T, saved.get("locks_today", {}))
        set_locks(LOCK_Y, saved.get("locks_yesterday", {}))

        st.session_state.last_retrait_t = saved.get("last_retrait_t", st.session_state.last_retrait_t)
        st.session_state.last_retrait_y = saved.get("last_retrait_y", st.session_state.last_retrait_y)

    # load boite state
    state_path_b, _ = boite_paths(today)
    savedb = load_json(state_path_b)
    if savedb:
        st.session_state.df_boite = pd.DataFrame(savedb.get("df_boite", st.session_state.df_boite))
        set_locks(LOCK_B, savedb.get("locks_boite", {}))
        st.session_state.last_retrait_b = savedb.get("last_retrait_b", st.session_state.last_retrait_b)


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

st.divider()

tab_caisse, tab_boite, tab_save = st.tabs(["Caisse", "Boîte (Échange)", "Sauvegarde & reçus"])


# ================== CAISSE COMPUTE REFRESH ==================
def refresh_caisse_tables():
    TARGET = int(st.session_state.target_dollars) * 100

    # yesterday table only used if missed close
    dfy = st.session_state.df_caisse_yesterday.copy()
    # ensure columns exist
    for c in ["Dénomination", "CLOSE", "RETRAIT", "RESTANT"]:
        if c not in dfy.columns:
            if c == "Dénomination":
                dfy[c] = DISPLAY_ORDER
            else:
                dfy[c] = 0
    dfy = dfy[["Dénomination", "CLOSE", "RETRAIT", "RESTANT"]]

    close_y = counts_from_df(dfy, "CLOSE")
    total_close_y = total_cents_counts(close_y)
    diff_y = total_close_y - TARGET

    locks_y = get_locks(LOCK_Y)
    retrait_y = {k: 0 for k in DISPLAY_ORDER}
    restant_y = dict(close_y)
    remaining_y = 0

    if diff_y > 0:
        retrait_y, remaining_y = suggest_with_locks(diff_y, close_y, PRIORITY_CAISSE, locks_y)
        restant_y = sub_counts(close_y, retrait_y)

    # write computed columns back
    for i, denom in enumerate(DISPLAY_ORDER):
        dfy.loc[dfy["Dénomination"] == denom, "RETRAIT"] = int(retrait_y.get(denom, 0))
        dfy.loc[dfy["Dénomination"] == denom, "RESTANT"] = int(restant_y.get(denom, 0))
    st.session_state.df_caisse_yesterday = dfy

    # today table
    dft = st.session_state.df_caisse_today.copy()
    for c in ["Dénomination", "OPEN", "CLOSE", "RETRAIT", "RESTANT"]:
        if c not in dft.columns:
            if c == "Dénomination":
                dft[c] = DISPLAY_ORDER
            else:
                dft[c] = 0
    dft = dft[["Dénomination", "OPEN", "CLOSE", "RETRAIT", "RESTANT"]]

    # if missed_close, OPEN today must be restant_y
    if st.session_state.mode_pick == "missed_close":
        for denom in DISPLAY_ORDER:
            dft.loc[dft["Dénomination"] == denom, "OPEN"] = int(restant_y.get(denom, 0))

    open_t = counts_from_df(dft, "OPEN")
    close_t = counts_from_df(dft, "CLOSE")

    total_close_t = total_cents_counts(close_t)
    diff_t = total_close_t - TARGET

    locks_t = get_locks(LOCK_T)
    retrait_t = {k: 0 for k in DISPLAY_ORDER}
    restant_t = dict(close_t)
    remaining_t = 0

    if diff_t > 0:
        retrait_t, remaining_t = suggest_with_locks(diff_t, close_t, PRIORITY_CAISSE, locks_t)
        restant_t = sub_counts(close_t, retrait_t)

    for denom in DISPLAY_ORDER:
        dft.loc[dft["Dénomination"] == denom, "RETRAIT"] = int(retrait_t.get(denom, 0))
        dft.loc[dft["Dénomination"] == denom, "RESTANT"] = int(restant_t.get(denom, 0))
    st.session_state.df_caisse_today = dft

    return {
        "TARGET": TARGET,
        "diff_y": diff_y,
        "remaining_y": remaining_y,
        "close_y": close_y,
        "retrait_y": retrait_y,
        "restant_y": restant_y,
        "diff_t": diff_t,
        "remaining_t": remaining_t,
        "open_t": open_t,
        "close_t": close_t,
        "retrait_t": retrait_t,
        "restant_t": restant_t,
    }


# ================== TAB: CAISSE ==================
with tab_caisse:
    st.subheader("Caisse")

    st.session_state.mode_pick = st.selectbox(
        "Mode",
        ["Ouverture normale", "Fermeture non effectuée (hier)"],
        index=0 if st.session_state.mode_pick == "normal" else 1,
        key="mode_dropdown",
    )
    st.session_state.mode_pick = "normal" if st.session_state.mode_pick.startswith("Ouverture") else "missed_close"

    # recompute computed columns
    ctx = refresh_caisse_tables()

    if st.session_state.mode_pick == "missed_close":
        st.markdown("### Hier — fermeture non effectuée")
        st.caption("Entre le CLOSE d'hier. Ajuste RETRAIT en modifiant la colonne RETRAIT (mettre 0 = bannir une coupure).")

        with st.form("form_caisse_y", clear_on_submit=False):
            dfy_display = st.session_state.df_caisse_yesterday.copy()

            edited_y = st.data_editor(
                dfy_display,
                use_container_width=True,
                hide_index=True,
                key="editor_caisse_y",
                column_config={
                    "Dénomination": st.column_config.TextColumn(disabled=True),
                    "CLOSE": st.column_config.NumberColumn(min_value=0, step=1),
                    "RETRAIT": st.column_config.NumberColumn(min_value=0, step=1),
                    "RESTANT": st.column_config.NumberColumn(disabled=True),
                },
            )

            submitted_y = st.form_submit_button("✅ Appliquer (hier)")

        if submitted_y:
            base = st.session_state.df_caisse_yesterday.copy()
            committed = merge_commit(base, edited_y, ["CLOSE", "RETRAIT"])  # user may edit RETRAIT to lock/ban

            # detect changed RETRAIT -> update locks only for those denoms
            new_retrait = counts_from_df(committed, "RETRAIT")
            last = dict(st.session_state.last_retrait_y)
            locks = get_locks(LOCK_Y)
            for denom in DISPLAY_ORDER:
                if int(new_retrait.get(denom, 0)) != int(last.get(denom, 0)):
                    locks[denom] = int(new_retrait.get(denom, 0))
            set_locks(LOCK_Y, locks)
            st.session_state.last_retrait_y = new_retrait

            st.session_state.df_caisse_yesterday = committed
            # refresh computed and OPEN today
            refresh_caisse_tables()
            st.rerun()

        # totals row under yesterday
        total_close_y = total_cents_counts(ctx["close_y"])
        total_retrait_y = total_cents_counts(ctx["retrait_y"])
        total_restant_y = total_cents_counts(ctx["restant_y"])

        total_row_y = pd.DataFrame([{
            "Dénomination": "TOTAL ($)",
            "CLOSE": float(f"{total_close_y/100:.2f}"),
            "RETRAIT": float(f"{total_retrait_y/100:.2f}"),
            "RESTANT": float(f"{total_restant_y/100:.2f}"),
        }])

        st.dataframe(total_row_y, use_container_width=True, hide_index=True)

        render_unlock_ui(LOCK_Y, "Déverrouiller des coupures (RETRAIT) — HIER")

        st.divider()

    st.markdown("### Aujourd'hui")
    st.caption("Entre OPEN/CLOSE. Pour forcer une autre combinaison, modifie RETRAIT (mettre 0 = bannir une coupure).")

    with st.form("form_caisse_t", clear_on_submit=False):
        dft_display = st.session_state.df_caisse_today.copy()

        edited_t = st.data_editor(
            dft_display,
            use_container_width=True,
            hide_index=True,
            key="editor_caisse_t",
            column_config={
                "Dénomination": st.column_config.TextColumn(disabled=True),
                "OPEN": st.column_config.NumberColumn(min_value=0, step=1, disabled=(st.session_state.mode_pick == "missed_close")),
                "CLOSE": st.column_config.NumberColumn(min_value=0, step=1),
                "RETRAIT": st.column_config.NumberColumn(min_value=0, step=1),
                "RESTANT": st.column_config.NumberColumn(disabled=True),
            },
        )
        submitted_t = st.form_submit_button("✅ Appliquer (aujourd'hui)")

    if submitted_t:
        base = st.session_state.df_caisse_today.copy()
        cols_to_commit = ["CLOSE", "RETRAIT"] if st.session_state.mode_pick == "missed_close" else ["OPEN", "CLOSE", "RETRAIT"]
        committed = merge_commit(base, edited_t, cols_to_commit)

        new_retrait = counts_from_df(committed, "RETRAIT")
        last = dict(st.session_state.last_retrait_t)
        locks = get_locks(LOCK_T)
        for denom in DISPLAY_ORDER:
            if int(new_retrait.get(denom, 0)) != int(last.get(denom, 0)):
                locks[denom] = int(new_retrait.get(denom, 0))
        set_locks(LOCK_T, locks)
        st.session_state.last_retrait_t = new_retrait

        st.session_state.df_caisse_today = committed
        refresh_caisse_tables()
        st.rerun()

    # totals row under today
    total_open_t = total_cents_counts(ctx["open_t"])
    total_close_t = total_cents_counts(ctx["close_t"])
    total_retrait_t = total_cents_counts(ctx["retrait_t"])
    total_restant_t = total_cents_counts(ctx["restant_t"])

    total_row_t = pd.DataFrame([{
        "Dénomination": "TOTAL ($)",
        "OPEN": float(f"{total_open_t/100:.2f}"),
        "CLOSE": float(f"{total_close_t/100:.2f}"),
        "RETRAIT": float(f"{total_retrait_t/100:.2f}"),
        "RESTANT": float(f"{total_restant_t/100:.2f}"),
    }])

    st.dataframe(total_row_t, use_container_width=True, hide_index=True)

    render_unlock_ui(LOCK_T, "Déverrouiller des coupures (RETRAIT) — AUJOURD'HUI")

    # Build & save receipt (today)
    rows_today = []
    dft_now = st.session_state.df_caisse_today.copy()
    for _, r in dft_now.iterrows():
        rows_today.append({
            "Dénomination": r["Dénomination"],
            "OPEN": int(clean_int(r.get("OPEN", 0))),
            "CLOSE": int(clean_int(r.get("CLOSE", 0))),
            "RETRAIT": int(clean_int(r.get("RETRAIT", 0))),
            "RESTANT": int(clean_int(r.get("RESTANT", 0))),
        })
    rows_today.append({
        "Dénomination": "TOTAL ($)",
        "OPEN": f"{total_open_t/100:.2f}",
        "CLOSE": f"{total_close_t/100:.2f}",
        "RETRAIT": f"{total_retrait_t/100:.2f}",
        "RESTANT": f"{total_restant_t/100:.2f}",
    })

    meta_caisse = {
        "Type": "CAISSE",
        "Date": today.isoformat(),
        "Généré à": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "Caisse #": int(st.session_state.register_no),
        "Caissier(ère)": (st.session_state.cashier.strip() or "—"),
        "Cible $": int(st.session_state.target_dollars),
        "Mode": "Fermeture non effectuée (hier)" if st.session_state.mode_pick == "missed_close" else "Ouverture normale",
    }

    payload_caisse = {
        "meta": meta_caisse,
        "mode_pick": st.session_state.mode_pick,
        "df_caisse_today": st.session_state.df_caisse_today.to_dict(orient="records"),
        "df_caisse_yesterday": st.session_state.df_caisse_yesterday.to_dict(orient="records"),
        "locks_today": get_locks(LOCK_T),
        "locks_yesterday": get_locks(LOCK_Y),
        "last_retrait_t": st.session_state.last_retrait_t,
        "last_retrait_y": st.session_state.last_retrait_y,
    }

    state_path, receipt_path = caisse_paths(today)
    hc = hash_payload(payload_caisse)
    if st.session_state.last_hash_caisse != hc:
        html = receipt_html("Reçu — Caisse", meta_caisse, ["Dénomination", "OPEN", "CLOSE", "RETRAIT", "RESTANT"], rows_today)
        save_json(state_path, payload_caisse)
        save_text(receipt_path, html)
        st.session_state.last_hash_caisse = hc

    st.markdown("### Aperçu reçu — Caisse")
    components.html(load_text(receipt_path) or html, height=520, scrolling=True)


# ================== BOÎTE COMPUTE REFRESH ==================
def refresh_boite_table():
    dfb = st.session_state.df_boite.copy()
    for c in ["Dénomination", "OPEN", "AJOUTÉ", "RETRAIT (en change)", "RESTANT"]:
        if c not in dfb.columns:
            if c == "Dénomination":
                dfb[c] = DISPLAY_ORDER
            else:
                dfb[c] = 0
    dfb = dfb[["Dénomination", "OPEN", "AJOUTÉ", "RETRAIT (en change)", "RESTANT"]]

    before = counts_from_df(dfb, "OPEN")
    added = counts_from_df(dfb, "AJOUTÉ")

    after_added = add_counts(before, added)
    total_added = total_cents_counts(added)

    locks_b = get_locks(LOCK_B)

    withdraw = {k: 0 for k in DISPLAY_ORDER}
    restant = dict(after_added)
    remaining = 0

    if total_added > 0:
        withdraw, remaining = suggest_with_locks(total_added, after_added, PRIORITY_BOITE, locks_b)
        restant = sub_counts(after_added, withdraw)

    for denom in DISPLAY_ORDER:
        dfb.loc[dfb["Dénomination"] == denom, "RETRAIT (en change)"] = int(withdraw.get(denom, 0))
        dfb.loc[dfb["Dénomination"] == denom, "RESTANT"] = int(restant.get(denom, 0))

    st.session_state.df_boite = dfb

    return {
        "before": before,
        "added": added,
        "after_added": after_added,
        "withdraw": withdraw,
        "restant": restant,
        "total_before": total_cents_counts(before),
        "total_added": total_added,
        "total_withdraw": total_cents_counts(withdraw),
        "total_rest": total_cents_counts(restant),
        "remaining": remaining,
    }


# ================== TAB: BOÎTE ==================
with tab_boite:
    st.subheader("Boîte (Échange)")
    st.caption("Colonnes: OPEN / AJOUTÉ / RETRAIT (en change) / RESTANT. Pour forcer une autre combinaison: modifie RETRAIT (mettre 0 = bannir).")

    bctx = refresh_boite_table()

    with st.form("form_boite", clear_on_submit=False):
        dfb_display = st.session_state.df_boite.copy()
        edited_b = st.data_editor(
            dfb_display,
            use_container_width=True,
            hide_index=True,
            key="editor_boite",
            column_config={
                "Dénomination": st.column_config.TextColumn(disabled=True),
                "OPEN": st.column_config.NumberColumn(min_value=0, step=1),
                "AJOUTÉ": st.column_config.NumberColumn(min_value=0, step=1),
                "RETRAIT (en change)": st.column_config.NumberColumn(min_value=0, step=1),
                "RESTANT": st.column_config.NumberColumn(disabled=True),
            },
        )
        submitted_b = st.form_submit_button("✅ Appliquer (boîte)")

    if submitted_b:
        base = st.session_state.df_boite.copy()
        committed = merge_commit(base, edited_b, ["OPEN", "AJOUTÉ", "RETRAIT (en change)"])

        new_retrait = counts_from_df(committed, "RETRAIT (en change)")
        last = dict(st.session_state.last_retrait_b)
        locks = get_locks(LOCK_B)
        for denom in DISPLAY_ORDER:
            if int(new_retrait.get(denom, 0)) != int(last.get(denom, 0)):
                locks[denom] = int(new_retrait.get(denom, 0))
        set_locks(LOCK_B, locks)
        st.session_state.last_retrait_b = new_retrait

        st.session_state.df_boite = committed
        refresh_boite_table()
        st.rerun()

    # totals row
    total_row_b = pd.DataFrame([{
        "Dénomination": "TOTAL ($)",
        "OPEN": float(f"{bctx['total_before']/100:.2f}"),
        "AJOUTÉ": float(f"{bctx['total_added']/100:.2f}"),
        "RETRAIT (en change)": float(f"{bctx['total_withdraw']/100:.2f}"),
        "RESTANT": float(f"{bctx['total_rest']/100:.2f}"),
    }])
    st.dataframe(total_row_b, use_container_width=True, hide_index=True)

    render_unlock_ui(LOCK_B, "Déverrouiller des coupures (RETRAIT) — BOÎTE")

    # Receipt (boîte)
    rows_boite = []
    dfb_now = st.session_state.df_boite.copy()
    for _, r in dfb_now.iterrows():
        rows_boite.append({
            "Dénomination": r["Dénomination"],
            "OPEN": int(clean_int(r.get("OPEN", 0))),
            "AJOUTÉ": int(clean_int(r.get("AJOUTÉ", 0))),
            "RETRAIT (en change)": int(clean_int(r.get("RETRAIT (en change)", 0))),
            "RESTANT": int(clean_int(r.get("RESTANT", 0))),
        })
    rows_boite.append({
        "Dénomination": "TOTAL ($)",
        "OPEN": f"{bctx['total_before']/100:.2f}",
        "AJOUTÉ": f"{bctx['total_added']/100:.2f}",
        "RETRAIT (en change)": f"{bctx['total_withdraw']/100:.2f}",
        "RESTANT": f"{bctx['total_rest']/100:.2f}",
    })

    meta_boite = {
        "Type": "BOÎTE (ÉCHANGE)",
        "Date": today.isoformat(),
        "Généré à": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "Caissier(ère)": (st.session_state.cashier.strip() or "—"),
        "Caisse #": int(st.session_state.register_no),
        "Ajout total ($)": f"{bctx['total_added']/100:.2f}",
    }

    payload_boite = {
        "meta": meta_boite,
        "df_boite": st.session_state.df_boite.to_dict(orient="records"),
        "locks_boite": get_locks(LOCK_B),
        "last_retrait_b": st.session_state.last_retrait_b,
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
    components.html(load_text(receipt_path_b) or htmlb, height=520, scrolling=True)


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
