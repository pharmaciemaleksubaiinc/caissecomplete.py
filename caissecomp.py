# caisse_one_table.py
# Registre — Caisse & Boîte (Échange)
# SINGLE TABLE PER SECTION (inputs + computed + TOTAL in the same data_editor)
# - No reverting to 0: we never rebuild editor df every rerun; only update in-place on Apply
# - Mode dropdown: Ouverture normale / Fermeture non effectuée (hier)
# - Lock/Unlock: LOCK + RETRAIT_LOCK per denom (force 0 to refuse denom)
# - Boîte columns: OPEN / AJOUTÉ / RETRAIT (en change) / RESTANT
# - Compact white report style

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


# ================== STYLE (WHITE, COMPACT) ==================
st.markdown(
    """
<style>
.main .block-container { padding-top: .55rem !important; padding-bottom: .75rem !important; max-width: 1600px !important; }
h1,h2,h3 { margin-bottom: .25rem !important; }
hr { margin: .55rem 0 !important; }
.stCaption { opacity:.72; }
button[kind="secondary"], button[kind="primary"] { font-weight: 800 !important; }

div[data-testid="stDataFrameResizable"], div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {
  border-radius: 10px !important;
}

/* keep everything white, clean */
div[data-testid="stDataEditor"] { background: #fff !important; }

/* slightly tighter fonts */
div[data-testid="stDataEditor"] * { font-size: 14px; }

/* reduce empty vertical air a bit */
div[data-testid="stDataEditor"] { padding-top: 0.1rem !important; padding-bottom: 0.1rem !important; }
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
TOTAL_ROW_LABEL = "TOTAL ($)"

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
def safe_int(x) -> int:
    try:
        if pd.isna(x):
            return 0
        return int(x)
    except Exception:
        return 0

def cents_to_str(c: int) -> str:
    return f"{c/100:.2f} $"

def editor_height(rows: int) -> int:
    # header ~ 38-44, row ~ 28-30; keep tight
    return 44 + rows * 30 + 10

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

def hash_payload(obj: dict) -> str:
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

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
      th{{background:#f4f4f4;font-weight:900}}
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

def total_cents_from_counts(counts: dict) -> int:
    return sum(int(counts.get(k, 0)) * DENOMS[k] for k in DISPLAY_ORDER)

def clamp_locked_counts(locked: dict, avail: dict) -> dict:
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

def suggest_retrait(amount_cents: int, avail: dict, locked: dict, priority: list):
    out = {k: 0 for k in DISPLAY_ORDER}
    for k, q in (locked or {}).items():
        out[k] = int(q)

    remaining = amount_cents - total_cents_from_counts(out)
    if remaining < 0:
        return out, remaining

    remaining = take_greedy(remaining, priority, avail, out, locked or {})
    return out, remaining

def ensure_caisse_df_today():
    # Columns: Denom | OPEN | CLOSE | LOCK | RETRAIT_LOCK | RETRAIT | RESTANT
    df = pd.DataFrame({
        "Dénomination": DISPLAY_ORDER + [TOTAL_ROW_LABEL],
        "OPEN": [0]*len(DISPLAY_ORDER) + [0],
        "CLOSE": [0]*len(DISPLAY_ORDER) + [0],
        "LOCK": [False]*len(DISPLAY_ORDER) + [False],
        "RETRAIT_LOCK": [0]*len(DISPLAY_ORDER) + [0],
        "RETRAIT": [0]*len(DISPLAY_ORDER) + [0],
        "RESTANT": [0]*len(DISPLAY_ORDER) + [0],
    })
    return df

def ensure_caisse_df_yesterday():
    df = pd.DataFrame({
        "Dénomination": DISPLAY_ORDER + [TOTAL_ROW_LABEL],
        "CLOSE": [0]*len(DISPLAY_ORDER) + [0],
        "LOCK": [False]*len(DISPLAY_ORDER) + [False],
        "RETRAIT_LOCK": [0]*len(DISPLAY_ORDER) + [0],
        "RETRAIT": [0]*len(DISPLAY_ORDER) + [0],
        "RESTANT": [0]*len(DISPLAY_ORDER) + [0],
    })
    return df

def ensure_boite_df():
    df = pd.DataFrame({
        "Dénomination": DISPLAY_ORDER + [TOTAL_ROW_LABEL],
        "OPEN": [0]*len(DISPLAY_ORDER) + [0],
        "AJOUTÉ": [0]*len(DISPLAY_ORDER) + [0],
        "LOCK": [False]*len(DISPLAY_ORDER) + [False],
        "RETRAIT_LOCK": [0]*len(DISPLAY_ORDER) + [0],
        "RETRAIT (en change)": [0]*len(DISPLAY_ORDER) + [0],
        "RESTANT": [0]*len(DISPLAY_ORDER) + [0],
    })
    return df

def locked_from_df(df: pd.DataFrame) -> dict:
    locked = {}
    for _, r in df.iterrows():
        denom = str(r.get("Dénomination", ""))
        if denom in DISPLAY_ORDER and bool(r.get("LOCK", False)):
            locked[denom] = safe_int(r.get("RETRAIT_LOCK", 0))
    return locked


def compute_caisse_today_inplace(df: pd.DataFrame, target_cents: int, allow_open_edit: bool):
    # sanitise inputs
    for col in ["OPEN", "CLOSE", "RETRAIT_LOCK", "RETRAIT", "RESTANT"]:
        if col in df.columns:
            df[col] = df[col].map(safe_int)

    # ignore total row in computations
    base = df[df["Dénomination"].isin(DISPLAY_ORDER)].copy()

    open_counts = {k: int(base.loc[base["Dénomination"] == k, "OPEN"].values[0]) for k in DISPLAY_ORDER}
    close_counts = {k: int(base.loc[base["Dénomination"] == k, "CLOSE"].values[0]) for k in DISPLAY_ORDER}

    diff = total_cents_from_counts(close_counts) - target_cents

    locked = clamp_locked_counts(locked_from_df(base), close_counts)
    retrait = {k: 0 for k in DISPLAY_ORDER}
    restant = close_counts.copy()
    remaining = 0

    if diff > 0:
        retrait, remaining = suggest_retrait(diff, close_counts, locked, PRIORITY_CAISSE)
        restant = {k: int(close_counts[k]) - int(retrait.get(k, 0)) for k in DISPLAY_ORDER}

    # write computed columns back into df for denom rows
    for k in DISPLAY_ORDER:
        df.loc[df["Dénomination"] == k, "RETRAIT"] = int(retrait.get(k, 0))
        df.loc[df["Dénomination"] == k, "RESTANT"] = int(restant.get(k, 0))

    # totals row
    total_open = total_cents_from_counts(open_counts)
    total_close = total_cents_from_counts(close_counts)
    total_retrait = total_cents_from_counts(retrait)
    total_restant = total_cents_from_counts(restant)

    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "OPEN"] = round(total_open/100, 2)
    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "CLOSE"] = round(total_close/100, 2)
    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "RETRAIT"] = round(total_retrait/100, 2)
    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "RESTANT"] = round(total_restant/100, 2)

    # keep totals row locks clean
    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "LOCK"] = False
    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "RETRAIT_LOCK"] = 0

    return diff, remaining, open_counts, close_counts, retrait, restant


def compute_caisse_yesterday_inplace(df_y: pd.DataFrame, target_cents: int):
    for col in ["CLOSE", "RETRAIT_LOCK", "RETRAIT", "RESTANT"]:
        df_y[col] = df_y[col].map(safe_int)

    base = df_y[df_y["Dénomination"].isin(DISPLAY_ORDER)].copy()
    close_counts = {k: int(base.loc[base["Dénomination"] == k, "CLOSE"].values[0]) for k in DISPLAY_ORDER}

    diff = total_cents_from_counts(close_counts) - target_cents
    locked = clamp_locked_counts(locked_from_df(base), close_counts)

    retrait = {k: 0 for k in DISPLAY_ORDER}
    restant = close_counts.copy()
    remaining = 0

    if diff > 0:
        retrait, remaining = suggest_retrait(diff, close_counts, locked, PRIORITY_CAISSE)
        restant = {k: int(close_counts[k]) - int(retrait.get(k, 0)) for k in DISPLAY_ORDER}

    for k in DISPLAY_ORDER:
        df_y.loc[df_y["Dénomination"] == k, "RETRAIT"] = int(retrait.get(k, 0))
        df_y.loc[df_y["Dénomination"] == k, "RESTANT"] = int(restant.get(k, 0))

    df_y.loc[df_y["Dénomination"] == TOTAL_ROW_LABEL, "CLOSE"] = round(total_cents_from_counts(close_counts)/100, 2)
    df_y.loc[df_y["Dénomination"] == TOTAL_ROW_LABEL, "RETRAIT"] = round(total_cents_from_counts(retrait)/100, 2)
    df_y.loc[df_y["Dénomination"] == TOTAL_ROW_LABEL, "RESTANT"] = round(total_cents_from_counts(restant)/100, 2)
    df_y.loc[df_y["Dénomination"] == TOTAL_ROW_LABEL, "LOCK"] = False
    df_y.loc[df_y["Dénomination"] == TOTAL_ROW_LABEL, "RETRAIT_LOCK"] = 0

    return diff, remaining, close_counts, retrait, restant


def compute_boite_inplace(df_b: pd.DataFrame):
    for col in ["OPEN", "AJOUTÉ", "RETRAIT_LOCK", "RETRAIT (en change)", "RESTANT"]:
        df_b[col] = df_b[col].map(safe_int)

    base = df_b[df_b["Dénomination"].isin(DISPLAY_ORDER)].copy()
    open_counts = {k: int(base.loc[base["Dénomination"] == k, "OPEN"].values[0]) for k in DISPLAY_ORDER}
    ajoute_counts = {k: int(base.loc[base["Dénomination"] == k, "AJOUTÉ"].values[0]) for k in DISPLAY_ORDER}

    after_add = {k: int(open_counts[k]) + int(ajoute_counts[k]) for k in DISPLAY_ORDER}
    total_ajoute = total_cents_from_counts(ajoute_counts)

    locked = clamp_locked_counts(locked_from_df(base), after_add)

    retrait = {k: 0 for k in DISPLAY_ORDER}
    restant = after_add.copy()
    remaining = 0

    if total_ajoute > 0:
        retrait, remaining = suggest_retrait(total_ajoute, after_add, locked, PRIORITY_BOITE)
        restant = {k: int(after_add[k]) - int(retrait.get(k, 0)) for k in DISPLAY_ORDER}

    for k in DISPLAY_ORDER:
        df_b.loc[df_b["Dénomination"] == k, "RETRAIT (en change)"] = int(retrait.get(k, 0))
        df_b.loc[df_b["Dénomination"] == k, "RESTANT"] = int(restant.get(k, 0))

    df_b.loc[df_b["Dénomination"] == TOTAL_ROW_LABEL, "OPEN"] = round(total_cents_from_counts(open_counts)/100, 2)
    df_b.loc[df_b["Dénomination"] == TOTAL_ROW_LABEL, "AJOUTÉ"] = round(total_cents_from_counts(ajoute_counts)/100, 2)
    df_b.loc[df_b["Dénomination"] == TOTAL_ROW_LABEL, "RETRAIT (en change)"] = round(total_cents_from_counts(retrait)/100, 2)
    df_b.loc[df_b["Dénomination"] == TOTAL_ROW_LABEL, "RESTANT"] = round(total_cents_from_counts(restant)/100, 2)
    df_b.loc[df_b["Dénomination"] == TOTAL_ROW_LABEL, "LOCK"] = False
    df_b.loc[df_b["Dénomination"] == TOTAL_ROW_LABEL, "RETRAIT_LOCK"] = 0

    return total_ajoute, remaining, open_counts, ajoute_counts, retrait, restant


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

# ================== INIT STATE ==================
today = datetime.now(TZ).date()
yesterday = today - timedelta(days=1)

st.session_state.setdefault("cashier", "")
st.session_state.setdefault("register_no", 1)
st.session_state.setdefault("target_dollars", 200)
st.session_state.setdefault("mode_pick", "normal")  # normal/missed_close

st.session_state.setdefault("caisse_today_df", ensure_caisse_df_today())
st.session_state.setdefault("caisse_yesterday_df", ensure_caisse_df_yesterday())
st.session_state.setdefault("boite_df", ensure_boite_df())

st.session_state.setdefault("last_hash_caisse", None)
st.session_state.setdefault("last_hash_boite", None)

# Load saved once per day
if st.session_state.get("booted_for") != today.isoformat():
    st.session_state["booted_for"] = today.isoformat()

    sp, _ = caisse_paths(today)
    saved = load_json(sp)
    if saved:
        meta = saved.get("meta", {})
        st.session_state.cashier = meta.get("Caissier(ère)", st.session_state.cashier)
        st.session_state.register_no = int(meta.get("Caisse #", st.session_state.register_no))
        st.session_state.target_dollars = int(meta.get("Cible $", st.session_state.target_dollars))
        st.session_state.mode_pick = saved.get("mode_pick", st.session_state.mode_pick)
        if "caisse_today_df" in saved:
            st.session_state.caisse_today_df = pd.DataFrame(saved["caisse_today_df"])
        if "caisse_yesterday_df" in saved:
            st.session_state.caisse_yesterday_df = pd.DataFrame(saved["caisse_yesterday_df"])

    spb, _ = boite_paths(today)
    savedb = load_json(spb)
    if savedb and "boite_df" in savedb:
        st.session_state.boite_df = pd.DataFrame(savedb["boite_df"])

# ================== HEADER ==================
st.title("Registre — Caisse & Boîte de monnaie")

h1, h2, h3, h4 = st.columns([1.1, 1.0, 1.2, 2.0])
with h1:
    st.write("**Date:**", today.isoformat())
with h2:
    st.write("**Heure:**", datetime.now(TZ).strftime("%H:%M"))
with h3:
    st.session_state.register_no = st.selectbox("Caisse #", [1, 2, 3], index=[1,2,3].index(int(st.session_state.register_no)), key="reg_sel")
with h4:
    st.session_state.cashier = st.text_input("Caissier(ère)", value=st.session_state.cashier, key="cashier_txt")

st.session_state.target_dollars = st.number_input("Cible à laisser ($)", min_value=0, step=10, value=int(st.session_state.target_dollars), key="target_num")
TARGET = int(st.session_state.target_dollars) * 100

st.divider()
tab_caisse, tab_boite, tab_save = st.tabs(["Caisse", "Boîte (Échange)", "Sauvegarde & reçus"])


# ================== TAB: CAISSE ==================
with tab_caisse:
    st.subheader("Caisse")

    mode = st.selectbox(
        "Mode",
        ["Ouverture normale", "Fermeture non effectuée (hier)"],
        index=0 if st.session_state.mode_pick == "normal" else 1,
        key="mode_dropdown",
    )
    st.session_state.mode_pick = "normal" if mode == "Ouverture normale" else "missed_close"
    st.caption("Pour forcer un retrait: coche LOCK ✅ et mets RETRAIT_LOCK (mets 0 pour refuser une coupure). Décoche LOCK pour déverrouiller.")

    # --- Yesterday block (only if missed_close)
    restant_y = {k: 0 for k in DISPLAY_ORDER}
    rep_y_rows = None

    if st.session_state.mode_pick == "missed_close":
        st.markdown("### Hier — fermeture non effectuée")

        df_y = st.session_state.caisse_yesterday_df.copy()

        edited_y = st.data_editor(
            df_y,
            use_container_width=True,
            hide_index=True,
            key="editor_caisse_y",
            height=editor_height(len(df_y)),
            column_config={
                "Dénomination": st.column_config.TextColumn(width="large"),
                "CLOSE": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
                "LOCK": st.column_config.CheckboxColumn(width="small"),
                "RETRAIT_LOCK": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
                "RETRAIT": st.column_config.NumberColumn(width="small"),
                "RESTANT": st.column_config.NumberColumn(width="small"),
            },
            disabled=["Dénomination", "RETRAIT", "RESTANT"],  # computed
        )

        if st.button("✅ Appliquer (hier)", use_container_width=True, key="apply_y"):
            # Store edits
            st.session_state.caisse_yesterday_df = edited_y.copy()
            # Compute in-place into stored df
            diff_y, remaining_y, close_y, retrait_y, restant_y = compute_caisse_yesterday_inplace(st.session_state.caisse_yesterday_df, TARGET)
            st.rerun()

        # compute current display (without forcing rerun)
        diff_y, remaining_y, close_y, retrait_y, restant_y = compute_caisse_yesterday_inplace(st.session_state.caisse_yesterday_df, TARGET)

        if diff_y <= 0:
            st.info("Hier: sous la cible (ou égal). Aucun retrait.")
        else:
            if remaining_y == 0:
                st.success(f"À retirer (hier): {cents_to_str(diff_y)}")
            elif remaining_y < 0:
                st.warning("Verrouillage trop haut. Dépasse de " + cents_to_str(-remaining_y))
            else:
                st.warning("Impossible exact. Reste: " + cents_to_str(remaining_y))

        # Auto-fill OPEN today with RESTANT yesterday (stored df only)
        df_t = st.session_state.caisse_today_df
        for k in DISPLAY_ORDER:
            df_t.loc[df_t["Dénomination"] == k, "OPEN"] = int(restant_y.get(k, 0))
        st.session_state.caisse_today_df = df_t

        st.divider()

    # --- Today
    st.markdown("### Aujourd'hui")

    df_t = st.session_state.caisse_today_df.copy()

    disable_cols = ["Dénomination", "RETRAIT", "RESTANT"]
    if st.session_state.mode_pick != "normal":
        disable_cols.append("OPEN")  # auto

    edited_t = st.data_editor(
        df_t,
        use_container_width=True,
        hide_index=True,
        key="editor_caisse_t",
        height=editor_height(len(df_t)),
        column_config={
            "Dénomination": st.column_config.TextColumn(width="large"),
            "OPEN": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "CLOSE": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "LOCK": st.column_config.CheckboxColumn(width="small"),
            "RETRAIT_LOCK": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "RETRAIT": st.column_config.NumberColumn(width="small"),
            "RESTANT": st.column_config.NumberColumn(width="small"),
        },
        disabled=disable_cols,
    )

    if st.button("✅ Appliquer (aujourd'hui)", use_container_width=True, key="apply_t"):
        st.session_state.caisse_today_df = edited_t.copy()
        diff_t, remaining_t, open_t, close_t, retrait_t, restant_t = compute_caisse_today_inplace(
            st.session_state.caisse_today_df, TARGET, allow_open_edit=(st.session_state.mode_pick == "normal")
        )
        st.rerun()

    diff_t, remaining_t, open_t, close_t, retrait_t, restant_t = compute_caisse_today_inplace(
        st.session_state.caisse_today_df, TARGET, allow_open_edit=(st.session_state.mode_pick == "normal")
    )

    if diff_t <= 0:
        st.info("Sous la cible (ou égal). Aucun retrait.")
    else:
        if remaining_t == 0:
            st.success(f"À retirer: {cents_to_str(diff_t)}")
        elif remaining_t < 0:
            st.warning("Verrouillage trop haut. Dépasse de " + cents_to_str(-remaining_t))
        else:
            st.warning("Impossible exact. Reste: " + cents_to_str(remaining_t))

    # Receipt + autosave
    meta_caisse = {
        "Type": "CAISSE",
        "Date": today.isoformat(),
        "Généré à": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "Caisse #": int(st.session_state.register_no),
        "Caissier(ère)": (st.session_state.cashier.strip() or "—"),
        "Cible $": int(st.session_state.target_dollars),
        "Mode": "Fermeture non effectuée (hier)" if st.session_state.mode_pick == "missed_close" else "Ouverture normale",
    }

    rows_today = []
    for k in DISPLAY_ORDER:
        rows_today.append({
            "Dénomination": k,
            "OPEN": int(open_t.get(k, 0)),
            "CLOSE": int(close_t.get(k, 0)),
            "RETRAIT": int(retrait_t.get(k, 0)),
            "RESTANT": int(restant_t.get(k, 0)),
        })
    rows_today.append({
        "Dénomination": "TOTAL ($)",
        "OPEN": f"{total_cents_from_counts(open_t)/100:.2f}",
        "CLOSE": f"{total_cents_from_counts(close_t)/100:.2f}",
        "RETRAIT": f"{total_cents_from_counts(retrait_t)/100:.2f}",
        "RESTANT": f"{total_cents_from_counts(restant_t)/100:.2f}",
    })

    payload_caisse = {
        "meta": meta_caisse,
        "mode_pick": st.session_state.mode_pick,
        "caisse_today_df": st.session_state.caisse_today_df.to_dict(orient="records"),
        "caisse_yesterday_df": st.session_state.caisse_yesterday_df.to_dict(orient="records"),
        "rows_today": rows_today,
    }

    state_path, receipt_path = caisse_paths(today)
    hc = hash_payload(payload_caisse)
    if st.session_state.last_hash_caisse != hc:
        html = receipt_html("Reçu — Caisse", meta_caisse, ["Dénomination", "OPEN", "CLOSE", "RETRAIT", "RESTANT"], rows_today)
        save_json(state_path, payload_caisse)
        save_text(receipt_path, html)
        st.session_state.last_hash_caisse = hc

    with st.expander("Aperçu reçu — Caisse", expanded=False):
        components.html(load_text(receipt_path) or html, height=560, scrolling=True)


# ================== TAB: BOÎTE ==================
with tab_boite:
    st.subheader("Boîte (Échange)")
    st.caption("Même logique. Ajuste le change via LOCK ✅ + RETRAIT_LOCK. Décoche LOCK pour déverrouiller.")

    df_b = st.session_state.boite_df.copy()

    edited_b = st.data_editor(
        df_b,
        use_container_width=True,
        hide_index=True,
        key="editor_boite",
        height=editor_height(len(df_b)),
        column_config={
            "Dénomination": st.column_config.TextColumn(width="large"),
            "OPEN": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "AJOUTÉ": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "LOCK": st.column_config.CheckboxColumn(width="small"),
            "RETRAIT_LOCK": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "RETRAIT (en change)": st.column_config.NumberColumn(width="small"),
            "RESTANT": st.column_config.NumberColumn(width="small"),
        },
        disabled=["Dénomination", "RETRAIT (en change)", "RESTANT"],
    )

    if st.button("✅ Appliquer (boîte)", use_container_width=True, key="apply_b"):
        st.session_state.boite_df = edited_b.copy()
        total_ajoute, remaining_b, open_b, ajoute_b, retrait_b, restant_b = compute_boite_inplace(st.session_state.boite_df)
        st.rerun()

    total_ajoute, remaining_b, open_b, ajoute_b, retrait_b, restant_b = compute_boite_inplace(st.session_state.boite_df)

    if total_ajoute == 0:
        st.info("AJOUTÉ = 0. Rien à calculer.")
    else:
        if remaining_b == 0:
            st.success(f"Change à retirer: {cents_to_str(total_ajoute)}")
        elif remaining_b < 0:
            st.warning("Verrouillage trop haut. Dépasse de " + cents_to_str(-remaining_b))
        else:
            st.warning("Impossible exact. Reste: " + cents_to_str(remaining_b))

    meta_boite = {
        "Type": "BOÎTE (ÉCHANGE)",
        "Date": today.isoformat(),
        "Généré à": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "Caissier(ère)": (st.session_state.cashier.strip() or "—"),
        "Caisse #": int(st.session_state.register_no),
        "Ajouté total ($)": f"{total_ajoute/100:.2f}",
    }

    rows_boite = []
    for k in DISPLAY_ORDER:
        rows_boite.append({
            "Dénomination": k,
            "OPEN": int(open_b.get(k, 0)),
            "AJOUTÉ": int(ajoute_b.get(k, 0)),
            "RETRAIT (en change)": int(retrait_b.get(k, 0)),
            "RESTANT": int(restant_b.get(k, 0)),
        })
    rows_boite.append({
        "Dénomination": "TOTAL ($)",
        "OPEN": f"{total_cents_from_counts(open_b)/100:.2f}",
        "AJOUTÉ": f"{total_cents_from_counts(ajoute_b)/100:.2f}",
        "RETRAIT (en change)": f"{total_cents_from_counts(retrait_b)/100:.2f}",
        "RESTANT": f"{total_cents_from_counts(restant_b)/100:.2f}",
    })

    payload_boite = {
        "meta": meta_boite,
        "boite_df": st.session_state.boite_df.to_dict(orient="records"),
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

    with st.expander("Aperçu reçu — Boîte (Échange)", expanded=False):
        components.html(load_text(receipt_path_b) or htmlb, height=560, scrolling=True)


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
