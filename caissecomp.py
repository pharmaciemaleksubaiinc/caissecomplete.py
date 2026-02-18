# caisse200+.py
# Registre — Caisse & Boîte (Échange)
# Report-style compact tables using st.data_editor (fixes UI + alignment)
# - Auth
# - Mode dropdown: Ouverture normale / Fermeture non effectuée (hier)
# - Caisse: table OPEN/CLOSE/RETRAIT editable, RESTANT computed
# - Missed close: table for yesterday CLOSE/RETRAIT, RESTANT => OPEN today
# - Boîte: OPEN/AJOUTÉ/RETRAIT (en change) editable, RESTANT computed
# - Save: JSON state + HTML receipt, browsable by date

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
.main .block-container { padding-top: 0.6rem !important; padding-bottom: 0.8rem !important; max-width: 1650px !important; }
h1,h2,h3 { margin-bottom: 0.25rem !important; }

/* Make data_editor look like a printed report: compact and bordered */
div[data-testid="stDataFrame"] { border: 1px solid #222 !important; border-radius: 0 !important; }
div[data-testid="stDataFrame"] * { font-size: 13px !important; }
div[data-testid="stDataFrame"] th { font-weight: 900 !important; }
div[data-testid="stDataFrame"] td { font-weight: 700 !important; }
div[data-testid="stDataFrame"] input { font-weight: 900 !important; text-align: center !important; }

/* Reduce row height */
div[data-testid="stDataFrame"] .stDataFrame { --row-height: 26px; }

/* Tighten vertical gaps */
div[data-testid="stVerticalBlock"] { gap: 0.25rem !important; }
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

def total_cents_counts(counts: dict) -> int:
    return sum(int(counts.get(k, 0)) * DENOMS[k] for k in DENOMS)

def clamp_nonneg(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).astype(int)
        out[c] = out[c].clip(lower=0)
    return out

def counts_from_df(df: pd.DataFrame, col: str) -> dict:
    return {row["Dénomination"]: int(row[col]) for _, row in df.iterrows()}

def df_from_counts(col_name: str, counts: dict) -> pd.DataFrame:
    return pd.DataFrame({
        "Dénomination": DISPLAY_ORDER,
        col_name: [int(counts.get(k, 0)) for k in DISPLAY_ORDER]
    })

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

if "mode_pick" not in st.session_state:
    st.session_state.mode_pick = "normal"
if "cashier" not in st.session_state:
    st.session_state.cashier = ""
if "register_no" not in st.session_state:
    st.session_state.register_no = 1
if "target_dollars" not in st.session_state:
    st.session_state.target_dollars = 200

if "last_hash_caisse" not in st.session_state:
    st.session_state.last_hash_caisse = None
if "last_hash_boite" not in st.session_state:
    st.session_state.last_hash_boite = None

# tables state
def init_table(key: str, columns: list[str]):
    if key not in st.session_state:
        df = pd.DataFrame({"Dénomination": DISPLAY_ORDER})
        for c in columns:
            df[c] = 0
        st.session_state[key] = df

init_table("df_caisse_today", ["OPEN", "CLOSE", "RETRAIT"])
init_table("df_caisse_yesterday", ["CLOSE", "RETRAIT"])
init_table("df_boite", ["OPEN", "AJOUTÉ", "RETRAIT (en change)"])

# load saved daily state if exists
if "booted_for" not in st.session_state or st.session_state.booted_for != today.isoformat():
    st.session_state.booted_for = today.isoformat()

    sp, _ = caisse_paths(today)
    saved = load_json(sp)
    if saved:
        meta = saved.get("meta", {})
        st.session_state.cashier = meta.get("Caissier(ère)", st.session_state.cashier)
        st.session_state.register_no = int(meta.get("Caisse #", st.session_state.register_no))
        st.session_state.target_dollars = int(meta.get("Cible $", st.session_state.target_dollars))
        st.session_state.mode_pick = saved.get("mode_pick", st.session_state.mode_pick)

        # restore caisse today df
        counts = saved.get("counts", {})
        open_t = counts.get("caisse_open_today", {})
        close_t = counts.get("caisse_close_today", {})
        retrait_t = saved.get("locked_retrait_caisse", {})  # last edited retrait
        df = pd.DataFrame({"Dénomination": DISPLAY_ORDER})
        df["OPEN"] = [int(open_t.get(k, 0)) for k in DISPLAY_ORDER]
        df["CLOSE"] = [int(close_t.get(k, 0)) for k in DISPLAY_ORDER]
        # if no locked, fallback to computed later; keep as 0 now
        df["RETRAIT"] = [int(retrait_t.get(k, 0)) for k in DISPLAY_ORDER]
        st.session_state.df_caisse_today = df

        # restore yesterday df if present
        close_y = counts.get("caisse_close_yesterday", {})
        retrait_y = saved.get("locked_retrait_hier", {})
        dfy = pd.DataFrame({"Dénomination": DISPLAY_ORDER})
        dfy["CLOSE"] = [int(close_y.get(k, 0)) for k in DISPLAY_ORDER]
        dfy["RETRAIT"] = [int(retrait_y.get(k, 0)) for k in DISPLAY_ORDER]
        st.session_state.df_caisse_yesterday = dfy

    spb, _ = boite_paths(today)
    savedb = load_json(spb)
    if savedb:
        counts = savedb.get("counts", {})
        open_b = counts.get("boite_open", {})
        add_b = counts.get("boite_added", {})
        ret_b = savedb.get("locked_withdraw_boite", {})
        dfb = pd.DataFrame({"Dénomination": DISPLAY_ORDER})
        dfb["OPEN"] = [int(open_b.get(k, 0)) for k in DISPLAY_ORDER]
        dfb["AJOUTÉ"] = [int(add_b.get(k, 0)) for k in DISPLAY_ORDER]
        dfb["RETRAIT (en change)"] = [int(ret_b.get(k, 0)) for k in DISPLAY_ORDER]
        st.session_state.df_boite = dfb


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

tab_caisse, tab_boite, tab_save = st.tabs(["1) Caisse", "2) Boîte (Échange)", "3) Sauvegarde & reçus"])


# ================== CAISSE TAB ==================
with tab_caisse:
    mode_labels = {"normal": "Ouverture normale", "missed_close": "Fermeture non effectuée (hier)"}
    mode = st.selectbox(
        "Mode",
        options=["normal", "missed_close"],
        format_func=lambda x: mode_labels[x],
        index=0 if st.session_state.mode_pick == "normal" else 1,
        key="mode_pick_sel",
    )
    if mode != st.session_state.mode_pick:
        st.session_state.mode_pick = mode
        st.rerun()

    TARGET = int(st.session_state.target_dollars) * 100

    # ---- Missed close: yesterday table
    if st.session_state.mode_pick == "missed_close":
        st.subheader("Hier — fermeture non effectuée")

        dfy = st.session_state.df_caisse_yesterday.copy()
        dfy = clamp_nonneg(dfy, ["CLOSE", "RETRAIT"])

        # compute restant_y = close - retrait (clamp to not go negative per denom)
        close_y = counts_from_df(dfy, "CLOSE")
        retrait_y = counts_from_df(dfy, "RETRAIT")
        restant_y = {}
        for k in DISPLAY_ORDER:
            restant_y[k] = max(0, int(close_y.get(k, 0)) - int(retrait_y.get(k, 0)))

        total_close_y = total_cents_counts(close_y)
        total_retrait_y = total_cents_counts(retrait_y)
        total_restant_y = total_cents_counts(restant_y)

        # enforce: retrait cannot exceed close per denom
        for k in DISPLAY_ORDER:
            mx = int(close_y.get(k, 0))
            if retrait_y[k] > mx:
                retrait_y[k] = mx
                restant_y[k] = 0
        # rebuild df after clamp
        dfy["RETRAIT"] = [retrait_y[k] for k in DISPLAY_ORDER]

        st.session_state.df_caisse_yesterday = st.data_editor(
            dfy,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "Dénomination": st.column_config.TextColumn(disabled=True),
                "CLOSE": st.column_config.NumberColumn(min_value=0, step=1),
                "RETRAIT": st.column_config.NumberColumn(min_value=0, step=1),
            },
            key="editor_caisse_y",
        )

        # OPEN today = restant_y
        dft = st.session_state.df_caisse_today.copy()
        dft["OPEN"] = [restant_y[k] for k in DISPLAY_ORDER]
        st.session_state.df_caisse_today = dft

        st.caption(
            f"TOTAL CLOSE (hier): {cents_to_str(total_close_y)} | "
            f"TOTAL RETRAIT (hier): {cents_to_str(total_retrait_y)} | "
            f"TOTAL RESTANT (hier): {cents_to_str(total_restant_y)}"
        )
        st.divider()

    # ---- Today table
    st.subheader("Aujourd'hui")

    dft = st.session_state.df_caisse_today.copy()
    dft = clamp_nonneg(dft, ["OPEN", "CLOSE", "RETRAIT"])

    # If normal mode, OPEN editable; if missed_close, OPEN locked
    open_disabled = (st.session_state.mode_pick != "normal")

    # compute restant today (clamp retrait <= close per denom)
    open_t = counts_from_df(dft, "OPEN")
    close_t = counts_from_df(dft, "CLOSE")
    retrait_t = counts_from_df(dft, "RETRAIT")

    for k in DISPLAY_ORDER:
        mx = int(close_t.get(k, 0))
        if retrait_t[k] > mx:
            retrait_t[k] = mx

    restant_t = {k: max(0, int(close_t.get(k, 0)) - int(retrait_t.get(k, 0))) for k in DISPLAY_ORDER}

    dft["RETRAIT"] = [retrait_t[k] for k in DISPLAY_ORDER]
    dft["RESTANT"] = [restant_t[k] for k in DISPLAY_ORDER]

    total_open = total_cents_counts(open_t)
    total_close = total_cents_counts(close_t)
    total_retrait = total_cents_counts(retrait_t)
    total_restant = total_cents_counts(restant_t)

    edited = st.data_editor(
        dft[["Dénomination", "OPEN", "CLOSE", "RETRAIT", "RESTANT"]],
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Dénomination": st.column_config.TextColumn(disabled=True),
            "OPEN": st.column_config.NumberColumn(min_value=0, step=1, disabled=open_disabled),
            "CLOSE": st.column_config.NumberColumn(min_value=0, step=1),
            "RETRAIT": st.column_config.NumberColumn(min_value=0, step=1),
            "RESTANT": st.column_config.NumberColumn(disabled=True),
        },
        key="editor_caisse_t",
    )

    # store back (without RESTANT column persistence issues)
    edited = clamp_nonneg(edited, ["OPEN", "CLOSE", "RETRAIT"])
    st.session_state.df_caisse_today = edited.drop(columns=["RESTANT"], errors="ignore")

    st.caption(
        f"TOTAL OPEN: {cents_to_str(total_open)} | "
        f"TOTAL CLOSE: {cents_to_str(total_close)} | "
        f"TOTAL RETRAIT: {cents_to_str(total_retrait)} | "
        f"TOTAL RESTANT: {cents_to_str(total_restant)}"
    )

    # ---- Save receipt/state
    rows = []
    for k in DISPLAY_ORDER:
        rows.append({
            "Dénomination": k,
            "OPEN": int(open_t.get(k, 0)),
            "CLOSE": int(close_t.get(k, 0)),
            "RETRAIT": int(retrait_t.get(k, 0)),
            "RESTANT": int(restant_t.get(k, 0)),
        })
    rows.append({
        "Dénomination": "TOTAL ($)",
        "OPEN": f"{total_open/100:.2f}",
        "CLOSE": f"{total_close/100:.2f}",
        "RETRAIT": f"{total_retrait/100:.2f}",
        "RESTANT": f"{total_restant/100:.2f}",
    })

    meta = {
        "Type": "CAISSE",
        "Date": today.isoformat(),
        "Généré à": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "Caisse #": int(st.session_state.register_no),
        "Caissier(ère)": (st.session_state.cashier.strip() or "—"),
        "Cible $": int(st.session_state.target_dollars),
        "Mode": mode_labels[st.session_state.mode_pick],
    }

    payload = {
        "meta": meta,
        "mode_pick": st.session_state.mode_pick,
        "counts": {
            "caisse_open_today": open_t,
            "caisse_close_today": close_t,
            "caisse_close_yesterday": counts_from_df(st.session_state.df_caisse_yesterday, "CLOSE") if st.session_state.mode_pick == "missed_close" else {k: 0 for k in DISPLAY_ORDER},
        },
        "locked_retrait_caisse": retrait_t,
        "locked_retrait_hier": counts_from_df(st.session_state.df_caisse_yesterday, "RETRAIT") if st.session_state.mode_pick == "missed_close" else {},
        "rows_today": rows,
    }

    state_path, receipt_path = caisse_paths(today)
    hc = hash_payload(payload)
    if st.session_state.last_hash_caisse != hc:
        html = receipt_html("Reçu — Caisse", meta, ["Dénomination","OPEN","CLOSE","RETRAIT","RESTANT"], rows)
        save_json(state_path, payload)
        save_text(receipt_path, html)
        st.session_state.last_hash_caisse = hc

    st.markdown("### Aperçu reçu — Caisse")
    components.html(load_text(receipt_path) or "", height=520, scrolling=True)


# ================== BOÎTE TAB ==================
with tab_boite:
    st.subheader("Boîte (Échange)")

    dfb = st.session_state.df_boite.copy()
    dfb = clamp_nonneg(dfb, ["OPEN", "AJOUTÉ", "RETRAIT (en change)"])

    open_b = counts_from_df(dfb, "OPEN")
    add_b = counts_from_df(dfb, "AJOUTÉ")
    ret_b = counts_from_df(dfb, "RETRAIT (en change)")

    # after_added = open + ajouté
    after_added = {k: int(open_b.get(k, 0)) + int(add_b.get(k, 0)) for k in DISPLAY_ORDER}
    # clamp retrait <= after_added
    for k in DISPLAY_ORDER:
        mx = int(after_added.get(k, 0))
        if ret_b[k] > mx:
            ret_b[k] = mx
    restant_b = {k: max(0, int(after_added.get(k, 0)) - int(ret_b.get(k, 0))) for k in DISPLAY_ORDER}

    dfb["RETRAIT (en change)"] = [ret_b[k] for k in DISPLAY_ORDER]
    dfb["RESTANT"] = [restant_b[k] for k in DISPLAY_ORDER]

    tot_open = total_cents_counts(open_b)
    tot_add = total_cents_counts(add_b)
    tot_ret = total_cents_counts(ret_b)
    tot_rest = total_cents_counts(restant_b)

    editedb = st.data_editor(
        dfb[["Dénomination", "OPEN", "AJOUTÉ", "RETRAIT (en change)", "RESTANT"]],
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Dénomination": st.column_config.TextColumn(disabled=True),
            "OPEN": st.column_config.NumberColumn(min_value=0, step=1),
            "AJOUTÉ": st.column_config.NumberColumn(min_value=0, step=1),
            "RETRAIT (en change)": st.column_config.NumberColumn(min_value=0, step=1),
            "RESTANT": st.column_config.NumberColumn(disabled=True),
        },
        key="editor_boite",
    )

    editedb = clamp_nonneg(editedb, ["OPEN", "AJOUTÉ", "RETRAIT (en change)"])
    st.session_state.df_boite = editedb.drop(columns=["RESTANT"], errors="ignore")

    st.caption(
        f"TOTAL OPEN: {cents_to_str(tot_open)} | "
        f"TOTAL AJOUTÉ: {cents_to_str(tot_add)} | "
        f"TOTAL RETRAIT: {cents_to_str(tot_ret)} | "
        f"TOTAL RESTANT: {cents_to_str(tot_rest)}"
    )

    # receipt save
    rows = []
    for k in DISPLAY_ORDER:
        rows.append({
            "Dénomination": k,
            "OPEN": int(open_b.get(k, 0)),
            "AJOUTÉ": int(add_b.get(k, 0)),
            "RETRAIT (en change)": int(ret_b.get(k, 0)),
            "RESTANT": int(restant_b.get(k, 0)),
        })
    rows.append({
        "Dénomination": "TOTAL ($)",
        "OPEN": f"{tot_open/100:.2f}",
        "AJOUTÉ": f"{tot_add/100:.2f}",
        "RETRAIT (en change)": f"{tot_ret/100:.2f}",
        "RESTANT": f"{tot_rest/100:.2f}",
    })

    meta = {
        "Type": "BOÎTE (ÉCHANGE)",
        "Date": today.isoformat(),
        "Généré à": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "Caissier(ère)": (st.session_state.cashier.strip() or "—"),
        "Caisse #": int(st.session_state.register_no),
        "Ajouté total ($)": f"{tot_add/100:.2f}",
    }

    payload = {
        "meta": meta,
        "counts": {"boite_open": open_b, "boite_added": add_b},
        "locked_withdraw_boite": ret_b,
        "rows": rows,
    }

    state_path, receipt_path = boite_paths(today)
    hb = hash_payload(payload)
    if st.session_state.last_hash_boite != hb:
        html = receipt_html("Reçu — Boîte (Échange)", meta,
                           ["Dénomination","OPEN","AJOUTÉ","RETRAIT (en change)","RESTANT"], rows)
        save_json(state_path, payload)
        save_text(receipt_path, html)
        st.session_state.last_hash_boite = hb

    st.markdown("### Aperçu reçu — Boîte (Échange)")
    components.html(load_text(receipt_path) or "", height=520, scrolling=True)


# ================== SAVE TAB ==================
with tab_save:
    st.subheader("Sauvegarde & reçus")
    colA, colB = st.columns(2)

    with colA:
        st.markdown("## 📒 Caisse")
        dates = list_dates(DIR_CAISSE)
        if not dates:
            st.info("Aucun enregistrement Caisse.")
        else:
            for ds in reversed(dates):
                d = date.fromisoformat(ds)
                sp, rp = caisse_paths(d)
                with st.expander(f"{ds} — Reçu Caisse", expanded=False):
                    html = load_text(rp)
                    if html:
                        components.html(html, height=650, scrolling=True)
                    if os.path.exists(rp):
                        with open(rp, "rb") as f:
                            st.download_button("⬇️ Télécharger reçu (HTML)", f.read(), os.path.basename(rp), "text/html", key=f"dl_c_html_{ds}")
                    if os.path.exists(sp):
                        with open(sp, "rb") as f:
                            st.download_button("⬇️ Télécharger état (JSON)", f.read(), os.path.basename(sp), "application/json", key=f"dl_c_json_{ds}")

    with colB:
        st.markdown("## 🪙 Boîte (Échange)")
        dates = list_dates(DIR_BOITE)
        if not dates:
            st.info("Aucun enregistrement Boîte.")
        else:
            for ds in reversed(dates):
                d = date.fromisoformat(ds)
                sp, rp = boite_paths(d)
                with st.expander(f"{ds} — Reçu Boîte (Échange)", expanded=False):
                    html = load_text(rp)
                    if html:
                        components.html(html, height=650, scrolling=True)
                    if os.path.exists(rp):
                        with open(rp, "rb") as f:
                            st.download_button("⬇️ Télécharger reçu (HTML)", f.read(), os.path.basename(rp), "text/html", key=f"dl_b_html_{ds}")
                    if os.path.exists(sp):
                        with open(sp, "rb") as f:
                            st.download_button("⬇️ Télécharger état (JSON)", f.read(), os.path.basename(sp), "application/json", key=f"dl_b_json_{ds}")
