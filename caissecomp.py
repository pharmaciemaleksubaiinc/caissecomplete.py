# caisse_one_table_autosuggest.py
# Registre — Caisse & Boîte
# ONE table per tab (no extra result table)
# - RETRAIT auto-suggested to bring CLOSE down to target
# - You can override RETRAIT by editing cells in the SAME table
# - Overrides act like "implicit locks" WITHOUT showing lock columns
# - Overrides are stored ONLY for rows the user actually edited (fixes "all zeros lock the algo")
# - If user edits RETRAIT back to the suggested value -> override removed ("unlock")
# - Fix "Enter resets to 0" by keeping DF + overrides in session_state and not rebuilding them each rerun

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

# ================== STYLE (white + compact + bolder tables) ==================
st.markdown(
    """
<style>
.main .block-container { padding-top: .55rem !important; padding-bottom: .75rem !important; max-width: 1600px !important; }
h1,h2,h3 { margin-bottom: .25rem !important; }
hr { margin: .55rem 0 !important; }
.stCaption { opacity:.72; }
button[kind="secondary"], button[kind="primary"] { font-weight: 800 !important; }

/* Compact editor, report-like */
div[data-testid="stDataEditor"] { background:#fff !important; border-radius: 10px !important; }
div[data-testid="stDataEditor"] * { font-size: 14px; }

/* Make table text bolder (Streamlit DOM-targeted) */
div[data-testid="stDataEditor"] thead * { font-weight: 850 !important; }
div[data-testid="stDataEditor"] tbody * { font-weight: 650 !important; }
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
DISPLAY_ORDER = (
    BILLS_BIG
    + BILLS_SMALL
    + sorted(COINS, key=lambda x: DENOMS[x], reverse=True)
    + sorted(ROLLS, key=lambda x: DENOMS[x], reverse=True)
)
TOTAL_ROW_LABEL = "TOTAL ($)"

PRIORITY_CAISSE = DISPLAY_ORDER[:]  # big -> small already
PRIORITY_BOITE = (
    ["Billet 20 $", "Billet 10 $", "Billet 5 $"]
    + ["Pièce 2 $", "Pièce 1 $", "Pièce 0,25 $", "Pièce 0,10 $", "Pièce 0,05 $"]
    + ROLLS
    + ["Billet 50 $", "Billet 100 $"]
)

# ================== HELPERS ==================
def safe_int(x) -> int:
    try:
        if pd.isna(x) or x is None:
            return 0
        return int(x)
    except Exception:
        return 0

def cents_to_str(c: int) -> str:
    return f"{c/100:.2f} $"

def total_cents_from_counts(counts: dict) -> int:
    return sum(int(counts.get(k, 0)) * DENOMS[k] for k in DISPLAY_ORDER)

def editor_height(n_rows: int) -> int:
    return 46 + n_rows * 30 + 8

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

def ensure_df_caisse_today():
    return pd.DataFrame({
        "Dénomination": DISPLAY_ORDER + [TOTAL_ROW_LABEL],
        "OPEN": [0]*len(DISPLAY_ORDER) + [0.0],
        "CLOSE": [0]*len(DISPLAY_ORDER) + [0.0],
        "RETRAIT": [0]*len(DISPLAY_ORDER) + [0.0],   # editable override (but we only store overrides on edited rows)
        "RESTANT": [0]*len(DISPLAY_ORDER) + [0.0],   # computed
    })

def ensure_df_caisse_yesterday():
    return pd.DataFrame({
        "Dénomination": DISPLAY_ORDER + [TOTAL_ROW_LABEL],
        "CLOSE": [0]*len(DISPLAY_ORDER) + [0.0],
        "RETRAIT": [0]*len(DISPLAY_ORDER) + [0.0],   # editable override
        "RESTANT": [0]*len(DISPLAY_ORDER) + [0.0],   # computed
    })

def ensure_df_boite():
    return pd.DataFrame({
        "Dénomination": DISPLAY_ORDER + [TOTAL_ROW_LABEL],
        "OPEN": [0]*len(DISPLAY_ORDER) + [0.0],
        "AJOUTÉ": [0]*len(DISPLAY_ORDER) + [0.0],
        "RETRAIT (en change)": [0]*len(DISPLAY_ORDER) + [0.0],  # editable override
        "RESTANT": [0]*len(DISPLAY_ORDER) + [0.0],              # computed
    })

def clamp_override(override: dict, avail: dict) -> dict:
    out = {}
    for k, v in (override or {}).items():
        v = int(v)
        if v < 0:
            v = 0
        mx = int(avail.get(k, 0))
        if v > mx:
            v = mx
        out[k] = v
    return out

def greedy_fill(remaining_cents: int, avail_counts: dict, fixed_counts: dict, priority: list) -> dict:
    # Start with fixed counts
    out = {k: int(fixed_counts.get(k, 0)) for k in DISPLAY_ORDER}
    fixed_keys = set(k for k, v in fixed_counts.items() if v is not None)

    rem = remaining_cents - total_cents_from_counts(out)
    if rem <= 0:
        return out  # already met or over

    for k in priority:
        if rem <= 0:
            break
        if k in fixed_keys:
            continue
        v = DENOMS[k]
        can_take = int(avail_counts.get(k, 0)) - int(out.get(k, 0))
        if can_take <= 0:
            continue
        take = min(rem // v, can_take)
        if take > 0:
            out[k] = int(out.get(k, 0)) + int(take)
            rem -= int(take) * v

    return out

def compute_caisse_today(df: pd.DataFrame, target_cents: int, overrides: dict):
    # sanitize inputs
    for col in ["OPEN", "CLOSE", "RETRAIT"]:
        df[col] = df[col].map(safe_int)

    open_counts = {k: int(df.loc[df["Dénomination"] == k, "OPEN"].values[0]) for k in DISPLAY_ORDER}
    close_counts = {k: int(df.loc[df["Dénomination"] == k, "CLOSE"].values[0]) for k in DISPLAY_ORDER}

    diff = total_cents_from_counts(close_counts) - target_cents
    if diff <= 0:
        retrait = {k: 0 for k in DISPLAY_ORDER}
    else:
        overrides = clamp_override(overrides, close_counts)
        retrait = greedy_fill(diff, close_counts, overrides, PRIORITY_CAISSE)

    # compute restant
    restant = {k: int(close_counts[k]) - int(retrait.get(k, 0)) for k in DISPLAY_ORDER}

    # write back computed
    for k in DISPLAY_ORDER:
        df.loc[df["Dénomination"] == k, "RETRAIT"] = int(retrait.get(k, 0))
        df.loc[df["Dénomination"] == k, "RESTANT"] = int(restant.get(k, 0))

    # totals row ($)
    total_open = total_cents_from_counts(open_counts)
    total_close = total_cents_from_counts(close_counts)
    total_ret = total_cents_from_counts(retrait)
    total_res = total_cents_from_counts(restant)

    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "OPEN"] = round(total_open/100, 2)
    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "CLOSE"] = round(total_close/100, 2)
    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "RETRAIT"] = round(total_ret/100, 2)
    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "RESTANT"] = round(total_res/100, 2)

    leftover = (diff - total_ret) if diff > 0 else 0
    return open_counts, close_counts, retrait, restant, diff, leftover, overrides

def compute_caisse_yesterday(df: pd.DataFrame, target_cents: int, overrides: dict):
    for col in ["CLOSE", "RETRAIT"]:
        df[col] = df[col].map(safe_int)

    close_counts = {k: int(df.loc[df["Dénomination"] == k, "CLOSE"].values[0]) for k in DISPLAY_ORDER}
    diff = total_cents_from_counts(close_counts) - target_cents

    if diff <= 0:
        retrait = {k: 0 for k in DISPLAY_ORDER}
    else:
        overrides = clamp_override(overrides, close_counts)
        retrait = greedy_fill(diff, close_counts, overrides, PRIORITY_CAISSE)

    restant = {k: int(close_counts[k]) - int(retrait.get(k, 0)) for k in DISPLAY_ORDER}

    for k in DISPLAY_ORDER:
        df.loc[df["Dénomination"] == k, "RETRAIT"] = int(retrait.get(k, 0))
        df.loc[df["Dénomination"] == k, "RESTANT"] = int(restant.get(k, 0))

    total_close = total_cents_from_counts(close_counts)
    total_ret = total_cents_from_counts(retrait)
    total_res = total_cents_from_counts(restant)

    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "CLOSE"] = round(total_close/100, 2)
    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "RETRAIT"] = round(total_ret/100, 2)
    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "RESTANT"] = round(total_res/100, 2)

    leftover = (diff - total_ret) if diff > 0 else 0
    return close_counts, retrait, restant, diff, leftover, overrides

def compute_boite(df: pd.DataFrame, overrides: dict):
    for col in ["OPEN", "AJOUTÉ", "RETRAIT (en change)"]:
        df[col] = df[col].map(safe_int)

    open_counts = {k: int(df.loc[df["Dénomination"] == k, "OPEN"].values[0]) for k in DISPLAY_ORDER}
    add_counts = {k: int(df.loc[df["Dénomination"] == k, "AJOUTÉ"].values[0]) for k in DISPLAY_ORDER}

    after_add = {k: int(open_counts[k]) + int(add_counts[k]) for k in DISPLAY_ORDER}
    total_add = total_cents_from_counts(add_counts)

    if total_add <= 0:
        retrait = {k: 0 for k in DISPLAY_ORDER}
    else:
        overrides = clamp_override(overrides, after_add)
        retrait = greedy_fill(total_add, after_add, overrides, PRIORITY_BOITE)

    restant = {k: int(after_add[k]) - int(retrait.get(k, 0)) for k in DISPLAY_ORDER}

    for k in DISPLAY_ORDER:
        df.loc[df["Dénomination"] == k, "RETRAIT (en change)"] = int(retrait.get(k, 0))
        df.loc[df["Dénomination"] == k, "RESTANT"] = int(restant.get(k, 0))

    total_open = total_cents_from_counts(open_counts)
    total_ret = total_cents_from_counts(retrait)
    total_res = total_cents_from_counts(restant)

    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "OPEN"] = round(total_open/100, 2)
    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "AJOUTÉ"] = round(total_add/100, 2)
    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "RETRAIT (en change)"] = round(total_ret/100, 2)
    df.loc[df["Dénomination"] == TOTAL_ROW_LABEL, "RESTANT"] = round(total_res/100, 2)

    leftover = total_add - total_ret if total_add > 0 else 0
    return open_counts, add_counts, retrait, restant, total_add, leftover, overrides

def idx_to_denom_map(df_display: pd.DataFrame) -> dict:
    # Streamlit editor_state uses row indices; map them back to denom labels
    return {i: str(df_display.iloc[i]["Dénomination"]) for i in range(len(df_display))}

# ================== AUTH ==================
st.session_state.setdefault("auth", False)
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
st.session_state.setdefault("mode_pick", "normal")

st.session_state.setdefault("df_caisse_today", ensure_df_caisse_today())
st.session_state.setdefault("df_caisse_yesterday", ensure_df_caisse_yesterday())
st.session_state.setdefault("df_boite", ensure_df_boite())

# Overrides stored separately (invisible to user)
st.session_state.setdefault("over_caisse_today", {})       # denom -> count (ONLY edited rows)
st.session_state.setdefault("over_caisse_yesterday", {})
st.session_state.setdefault("over_boite", {})

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

        if "df_caisse_today" in saved:
            st.session_state.df_caisse_today = pd.DataFrame(saved["df_caisse_today"])
        if "df_caisse_yesterday" in saved:
            st.session_state.df_caisse_yesterday = pd.DataFrame(saved["df_caisse_yesterday"])
        st.session_state.over_caisse_today = saved.get("over_caisse_today", {}) or {}
        st.session_state.over_caisse_yesterday = saved.get("over_caisse_yesterday", {}) or {}

    spb, _ = boite_paths(today)
    savedb = load_json(spb)
    if savedb:
        if "df_boite" in savedb:
            st.session_state.df_boite = pd.DataFrame(savedb["df_boite"])
        st.session_state.over_boite = savedb.get("over_boite", {}) or {}

# ================== HEADER ==================
st.title("Registre — Caisse & Boîte de monnaie")

h1, h2, h3, h4 = st.columns([1.1, 1.0, 1.2, 2.0])
with h1:
    st.write("**Date:**", today.isoformat())
with h2:
    st.write("**Heure:**", datetime.now(TZ).strftime("%H:%M"))
with h3:
    st.session_state.register_no = st.selectbox(
        "Caisse #",
        [1, 2, 3],
        index=[1, 2, 3].index(int(st.session_state.register_no)),
        key="reg_sel",
    )
with h4:
    st.session_state.cashier = st.text_input("Caissier(ère)", value=st.session_state.cashier, key="cashier_txt")

st.session_state.target_dollars = st.number_input(
    "Cible à laisser ($)",
    min_value=0,
    step=10,
    value=int(st.session_state.target_dollars),
    key="target_num",
)
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

    # Reset overrides button (unlock without lock UI)
    cA, cB = st.columns([1, 3])
    with cA:
        if st.button("↩️ Réinitialiser les retraits", use_container_width=True):
            st.session_state.over_caisse_today = {}
            st.session_state.over_caisse_yesterday = {}
            st.rerun()
    with cB:
        st.caption(
            "Pour changer la proposition, modifie les chiffres dans RETRAIT (ex: mets 0 sur Billet 100 $). "
            "L’app recalculera le reste automatiquement. Remets la valeur suggérée pour déverrouiller."
        )

    restant_y = {k: 0 for k in DISPLAY_ORDER}

    # ---- Yesterday (only if missed_close). Kept in an expander so you’re not “scrolling forever”.
    if st.session_state.mode_pick == "missed_close":
        with st.expander("Hier — fermeture non effectuée", expanded=True):

            # Compute suggestions first so RETRAIT/RESTANT are shown
            close_y, retrait_y_sugg, restant_y, diff_y, leftover_y, _ = compute_caisse_yesterday(
                st.session_state.df_caisse_yesterday, TARGET, st.session_state.over_caisse_yesterday
            )
            df_y_display = st.session_state.df_caisse_yesterday.copy()

            edited_y = st.data_editor(
                df_y_display,
                use_container_width=True,
                hide_index=True,
                key="editor_caisse_y",
                height=editor_height(len(df_y_display)),
                column_config={
                    "Dénomination": st.column_config.TextColumn(width="large"),
                    "CLOSE": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
                    "RETRAIT": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
                    "RESTANT": st.column_config.NumberColumn(width="small"),
                },
                disabled=["Dénomination", "RESTANT"],
            )

            if st.button("✅ Appliquer (hier)", use_container_width=True, key="apply_y"):
                # 1) Commit CLOSE
                df_store = st.session_state.df_caisse_yesterday.copy()
                for k in DISPLAY_ORDER:
                    df_store.loc[df_store["Dénomination"] == k, "CLOSE"] = safe_int(
                        edited_y.loc[edited_y["Dénomination"] == k, "CLOSE"].values[0]
                    )
                st.session_state.df_caisse_yesterday = df_store

                # 2) Update overrides ONLY where user actually edited RETRAIT
                editor_state = st.session_state.get("editor_caisse_y", {})
                edited_rows = editor_state.get("edited_rows", {}) or {}
                idx_map = idx_to_denom_map(df_y_display)

                # Recompute suggestions before changing overrides
                _, suggested_ret_y, _, _, _, _ = compute_caisse_yesterday(
                    st.session_state.df_caisse_yesterday, TARGET, st.session_state.over_caisse_yesterday
                )

                overrides = dict(st.session_state.over_caisse_yesterday)

                for row_idx, changes in edited_rows.items():
                    denom = idx_map.get(int(row_idx))
                    if not denom or denom == TOTAL_ROW_LABEL:
                        continue
                    if "RETRAIT" in changes:
                        user_val = safe_int(changes["RETRAIT"])
                        sugg_val = int(suggested_ret_y.get(denom, 0))
                        if user_val != sugg_val:
                            overrides[denom] = user_val
                        else:
                            overrides.pop(denom, None)

                st.session_state.over_caisse_yesterday = overrides

                compute_caisse_yesterday(
                    st.session_state.df_caisse_yesterday, TARGET, st.session_state.over_caisse_yesterday
                )
                st.rerun()

            # Recompute (for status + for prefill OPEN)
            close_y, retrait_y, restant_y, diff_y, leftover_y, _ = compute_caisse_yesterday(
                st.session_state.df_caisse_yesterday, TARGET, st.session_state.over_caisse_yesterday
            )

            if diff_y <= 0:
                st.info("Hier: sous la cible (ou égal). Aucun retrait requis.")
            else:
                if leftover_y == 0:
                    st.success(f"Hier OK. À retirer: {cents_to_str(diff_y)}")
                elif leftover_y > 0:
                    st.warning(f"Hier: il manque {cents_to_str(leftover_y)} à retirer.")
                else:
                    st.warning(f"Hier: tu as retiré {cents_to_str(-leftover_y)} de trop.")

        # Pre-fill OPEN today from RESTANT yesterday
        df_t_prefill = st.session_state.df_caisse_today
        for k in DISPLAY_ORDER:
            df_t_prefill.loc[df_t_prefill["Dénomination"] == k, "OPEN"] = int(restant_y.get(k, 0))
        st.session_state.df_caisse_today = df_t_prefill

    st.markdown("### Aujourd'hui")

    # Compute suggestions first so RETRAIT is auto-suggested in the editor
    open_t, close_t, retrait_t, restant_t, diff_t, leftover_t, _ = compute_caisse_today(
        st.session_state.df_caisse_today, TARGET, st.session_state.over_caisse_today
    )

    df_t_display = st.session_state.df_caisse_today.copy()

    disabled_cols = ["Dénomination", "RESTANT"]
    if st.session_state.mode_pick != "normal":
        disabled_cols.append("OPEN")

    edited_t = st.data_editor(
        df_t_display,
        use_container_width=True,
        hide_index=True,
        key="editor_caisse_t",
        height=editor_height(len(df_t_display)),
        column_config={
            "Dénomination": st.column_config.TextColumn(width="large"),
            "OPEN": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "CLOSE": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "RETRAIT": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "RESTANT": st.column_config.NumberColumn(width="small"),
        },
        disabled=disabled_cols,
    )

    if st.button("✅ Appliquer (aujourd'hui)", use_container_width=True, key="apply_t"):
        # 1) Commit OPEN/CLOSE (don’t blindly commit RETRAIT)
        df_store = st.session_state.df_caisse_today.copy()
        for k in DISPLAY_ORDER:
            if "OPEN" not in disabled_cols:
                df_store.loc[df_store["Dénomination"] == k, "OPEN"] = safe_int(
                    edited_t.loc[edited_t["Dénomination"] == k, "OPEN"].values[0]
                )
            df_store.loc[df_store["Dénomination"] == k, "CLOSE"] = safe_int(
                edited_t.loc[edited_t["Dénomination"] == k, "CLOSE"].values[0]
            )
        st.session_state.df_caisse_today = df_store

        # 2) Update overrides ONLY for RETRAIT rows that user edited
        editor_state = st.session_state.get("editor_caisse_t", {})
        edited_rows = editor_state.get("edited_rows", {}) or {}
        idx_map = idx_to_denom_map(df_t_display)

        # Suggestions before updating overrides
        _, _, suggested_ret, _, _, _, _ = compute_caisse_today(
            st.session_state.df_caisse_today, TARGET, st.session_state.over_caisse_today
        )

        overrides = dict(st.session_state.over_caisse_today)

        for row_idx, changes in edited_rows.items():
            denom = idx_map.get(int(row_idx))
            if not denom or denom == TOTAL_ROW_LABEL:
                continue
            if "RETRAIT" in changes:
                user_val = safe_int(changes["RETRAIT"])
                sugg_val = int(suggested_ret.get(denom, 0))
                if user_val != sugg_val:
                    overrides[denom] = user_val
                else:
                    overrides.pop(denom, None)

        st.session_state.over_caisse_today = overrides

        # 3) Final compute writes RETRAIT/RESTANT + totals
        compute_caisse_today(st.session_state.df_caisse_today, TARGET, st.session_state.over_caisse_today)
        st.rerun()

    # Recompute for status + receipt building
    open_t, close_t, retrait_t, restant_t, diff_t, leftover_t, _ = compute_caisse_today(
        st.session_state.df_caisse_today, TARGET, st.session_state.over_caisse_today
    )

    if diff_t <= 0:
        st.info("Sous la cible (ou égal). Aucun retrait requis.")
    else:
        if leftover_t == 0:
            st.success(f"OK. À retirer: {cents_to_str(diff_t)}")
        elif leftover_t > 0:
            st.warning(f"Il manque {cents_to_str(leftover_t)} à retirer.")
        else:
            st.warning(f"Tu as retiré {cents_to_str(-leftover_t)} de trop.")

    # Receipt + save
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
        "df_caisse_today": st.session_state.df_caisse_today.to_dict(orient="records"),
        "df_caisse_yesterday": st.session_state.df_caisse_yesterday.to_dict(orient="records"),
        "over_caisse_today": st.session_state.over_caisse_today,
        "over_caisse_yesterday": st.session_state.over_caisse_yesterday,
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

    cA, cB = st.columns([1, 3])
    with cA:
        if st.button("↩️ Réinitialiser change", use_container_width=True):
            st.session_state.over_boite = {}
            st.rerun()
    with cB:
        st.caption(
            "Modifie RETRAIT (en change) pour forcer une répartition. "
            "L’app recalculera le reste automatiquement. Remets la valeur suggérée pour déverrouiller."
        )

    # Compute suggestions first so RETRAIT (en change) is auto-suggested in the editor
    open_b, add_b, ret_b_sugg, res_b, total_add, leftover_b, _ = compute_boite(
        st.session_state.df_boite, st.session_state.over_boite
    )
    df_b_display = st.session_state.df_boite.copy()

    edited_b = st.data_editor(
        df_b_display,
        use_container_width=True,
        hide_index=True,
        key="editor_boite",
        height=editor_height(len(df_b_display)),
        column_config={
            "Dénomination": st.column_config.TextColumn(width="large"),
            "OPEN": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "AJOUTÉ": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "RETRAIT (en change)": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "RESTANT": st.column_config.NumberColumn(width="small"),
        },
        disabled=["Dénomination", "RESTANT"],
    )

    if st.button("✅ Appliquer (boîte)", use_container_width=True, key="apply_b"):
        # 1) Commit OPEN + AJOUTÉ (don’t blindly commit RETRAIT)
        df_store = st.session_state.df_boite.copy()
        for k in DISPLAY_ORDER:
            df_store.loc[df_store["Dénomination"] == k, "OPEN"] = safe_int(
                edited_b.loc[edited_b["Dénomination"] == k, "OPEN"].values[0]
            )
            df_store.loc[df_store["Dénomination"] == k, "AJOUTÉ"] = safe_int(
                edited_b.loc[edited_b["Dénomination"] == k, "AJOUTÉ"].values[0]
            )
        st.session_state.df_boite = df_store

        # 2) Update overrides ONLY for rows edited in RETRAIT (en change)
        editor_state = st.session_state.get("editor_boite", {})
        edited_rows = editor_state.get("edited_rows", {}) or {}
        idx_map = idx_to_denom_map(df_b_display)

        # Suggestions before updating overrides
        _, _, suggested_ret_b, _, _, _, _ = compute_boite(st.session_state.df_boite, st.session_state.over_boite)

        overrides = dict(st.session_state.over_boite)

        for row_idx, changes in edited_rows.items():
            denom = idx_map.get(int(row_idx))
            if not denom or denom == TOTAL_ROW_LABEL:
                continue
            if "RETRAIT (en change)" in changes:
                user_val = safe_int(changes["RETRAIT (en change)"])
                sugg_val = int(suggested_ret_b.get(denom, 0))
                if user_val != sugg_val:
                    overrides[denom] = user_val
                else:
                    overrides.pop(denom, None)

        st.session_state.over_boite = overrides

        compute_boite(st.session_state.df_boite, st.session_state.over_boite)
        st.rerun()

    # Recompute for status + receipt building
    open_b, add_b, ret_b, res_b, total_add, leftover_b, _ = compute_boite(
        st.session_state.df_boite, st.session_state.over_boite
    )

    if total_add <= 0:
        st.info("AJOUTÉ = 0. Rien à équilibrer.")
    else:
        if leftover_b == 0:
            st.success(f"OK. Change retiré = Ajouté: {cents_to_str(total_add)}")
        elif leftover_b > 0:
            st.warning(f"Il manque {cents_to_str(leftover_b)} à retirer.")
        else:
            st.warning(f"Tu as retiré {cents_to_str(-leftover_b)} de trop.")

    meta_boite = {
        "Type": "BOÎTE (ÉCHANGE)",
        "Date": today.isoformat(),
        "Généré à": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "Caissier(ère)": (st.session_state.cashier.strip() or "—"),
        "Caisse #": int(st.session_state.register_no),
        "Ajouté total ($)": f"{total_add/100:.2f}",
    }

    rows_boite = []
    for k in DISPLAY_ORDER:
        rows_boite.append({
            "Dénomination": k,
            "OPEN": int(open_b.get(k, 0)),
            "AJOUTÉ": int(add_b.get(k, 0)),
            "RETRAIT (en change)": int(ret_b.get(k, 0)),
            "RESTANT": int(res_b.get(k, 0)),
        })
    rows_boite.append({
        "Dénomination": "TOTAL ($)",
        "OPEN": f"{total_cents_from_counts(open_b)/100:.2f}",
        "AJOUTÉ": f"{total_cents_from_counts(add_b)/100:.2f}",
        "RETRAIT (en change)": f"{total_cents_from_counts(ret_b)/100:.2f}",
        "RESTANT": f"{total_cents_from_counts(res_b)/100:.2f}",
    })

    payload_boite = {
        "meta": meta_boite,
        "df_boite": st.session_state.df_boite.to_dict(orient="records"),
        "over_boite": st.session_state.over_boite,
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

    def list_dates(folder: str):
        files = sorted([f for f in os.listdir(folder) if f.endswith("_state.json")])
        return [f.replace("_state.json", "") for f in files]

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
                    if os.path.exists(receipt_path):
                        with open(receipt_path, "rb") as f:
                            st.download_button(
                                "⬇️ Télécharger reçu (HTML)",
                                f.read(),
                                os.path.basename(receipt_path),
                                "text/html",
                                key=f"dl_c_html_{ds}",
                            )
                    if os.path.exists(state_path):
                        with open(state_path, "rb") as f:
                            st.download_button(
                                "⬇️ Télécharger état (JSON)",
                                f.read(),
                                os.path.basename(state_path),
                                "application/json",
                                key=f"dl_c_json_{ds}",
                            )

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
                    if os.path.exists(receipt_path):
                        with open(receipt_path, "rb") as f:
                            st.download_button(
                                "⬇️ Télécharger reçu (HTML)",
                                f.read(),
                                os.path.basename(receipt_path),
                                "text/html",
                                key=f"dl_b_html_{ds}",
                            )
                    if os.path.exists(state_path):
                        with open(state_path, "rb") as f:
                            st.download_button(
                                "⬇️ Télécharger état (JSON)",
                                f.read(),
                                os.path.basename(state_path),
                                "application/json",
                                key=f"dl_b_json_{ds}",
                            )
