# caissecomplete.py
# Registre — Caisse & Boîte (Échange)
# FULL REWRITE: stable data_editor (no revert), report-style output, lock/unlock retrait.

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

# ================== STYLE (WHITE, CONDENSED) ==================
st.markdown(
    """
<style>
.main .block-container { padding-top: .55rem !important; padding-bottom: .75rem !important; max-width: 1600px !important; }
h1,h2,h3 { margin-bottom: .25rem !important; }
hr { margin: .55rem 0 !important; }
.stCaption { opacity:.72; }
button[kind="secondary"], button[kind="primary"] { font-weight: 800 !important; }

div[data-testid="stDataFrameResizable"] { border-radius: 10px !important; }
div[data-testid="stDataFrame"] { border-radius: 10px !important; }
div[data-testid="stDataEditor"] { border-radius: 10px !important; }

/* tighten dataframe padding a bit */
div[data-testid="stDataFrame"] * { font-size: 14px; }
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


def safe_int(x) -> int:
    try:
        if pd.isna(x):
            return 0
        return int(x)
    except Exception:
        return 0


def editor_height_for_rows(n_rows: int) -> int:
    header = 42
    row_h = 30  # tighter than default
    extra = 14
    return header + n_rows * row_h + extra


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


def df_inputs_caisse_today():
    return pd.DataFrame(
        {
            "Dénomination": DISPLAY_ORDER,
            "OPEN": [0] * len(DISPLAY_ORDER),
            "CLOSE": [0] * len(DISPLAY_ORDER),
            "LOCK": [False] * len(DISPLAY_ORDER),
            "RETRAIT_LOCK": [0] * len(DISPLAY_ORDER),
        }
    )


def df_inputs_caisse_yesterday():
    return pd.DataFrame(
        {
            "Dénomination": DISPLAY_ORDER,
            "CLOSE": [0] * len(DISPLAY_ORDER),
            "LOCK": [False] * len(DISPLAY_ORDER),
            "RETRAIT_LOCK": [0] * len(DISPLAY_ORDER),
        }
    )


def df_inputs_boite():
    return pd.DataFrame(
        {
            "Dénomination": DISPLAY_ORDER,
            "OPEN": [0] * len(DISPLAY_ORDER),
            "AJOUTÉ": [0] * len(DISPLAY_ORDER),
            "LOCK": [False] * len(DISPLAY_ORDER),
            "RETRAIT_LOCK": [0] * len(DISPLAY_ORDER),
        }
    )


def counts_from_df(df: pd.DataFrame, col: str) -> dict:
    out = {k: 0 for k in DISPLAY_ORDER}
    for _, r in df.iterrows():
        denom = str(r.get("Dénomination", ""))
        if denom in out:
            out[denom] = safe_int(r.get(col, 0))
    return out


def locks_from_df(df: pd.DataFrame, lock_col="LOCK", qty_col="RETRAIT_LOCK") -> dict:
    locked = {}
    for _, r in df.iterrows():
        denom = str(r.get("Dénomination", ""))
        if denom in DISPLAY_ORDER and bool(r.get(lock_col, False)):
            locked[denom] = safe_int(r.get(qty_col, 0))
    return locked


def build_report_caisse(open_counts, close_counts, retrait_counts, restant_counts):
    rows = []
    for k in DISPLAY_ORDER:
        rows.append(
            {
                "Dénomination": k,
                "OPEN": int(open_counts.get(k, 0)),
                "CLOSE": int(close_counts.get(k, 0)),
                "RETRAIT": int(retrait_counts.get(k, 0)),
                "RESTANT": int(restant_counts.get(k, 0)),
            }
        )
    rows.append(
        {
            "Dénomination": "TOTAL ($)",
            "OPEN": round(total_cents_from_counts(open_counts) / 100, 2),
            "CLOSE": round(total_cents_from_counts(close_counts) / 100, 2),
            "RETRAIT": round(total_cents_from_counts(retrait_counts) / 100, 2),
            "RESTANT": round(total_cents_from_counts(restant_counts) / 100, 2),
        }
    )
    return pd.DataFrame(rows), rows


def build_report_yesterday(close_counts, retrait_counts, restant_counts):
    rows = []
    for k in DISPLAY_ORDER:
        rows.append(
            {
                "Dénomination": k,
                "CLOSE": int(close_counts.get(k, 0)),
                "RETRAIT": int(retrait_counts.get(k, 0)),
                "RESTANT": int(restant_counts.get(k, 0)),
            }
        )
    rows.append(
        {
            "Dénomination": "TOTAL ($)",
            "CLOSE": round(total_cents_from_counts(close_counts) / 100, 2),
            "RETRAIT": round(total_cents_from_counts(retrait_counts) / 100, 2),
            "RESTANT": round(total_cents_from_counts(restant_counts) / 100, 2),
        }
    )
    return pd.DataFrame(rows), rows


def build_report_boite(open_counts, ajoute_counts, retrait_counts, restant_counts):
    rows = []
    for k in DISPLAY_ORDER:
        rows.append(
            {
                "Dénomination": k,
                "OPEN": int(open_counts.get(k, 0)),
                "AJOUTÉ": int(ajoute_counts.get(k, 0)),
                "RETRAIT (en change)": int(retrait_counts.get(k, 0)),
                "RESTANT": int(restant_counts.get(k, 0)),
            }
        )
    rows.append(
        {
            "Dénomination": "TOTAL ($)",
            "OPEN": round(total_cents_from_counts(open_counts) / 100, 2),
            "AJOUTÉ": round(total_cents_from_counts(ajoute_counts) / 100, 2),
            "RETRAIT (en change)": round(total_cents_from_counts(retrait_counts) / 100, 2),
            "RESTANT": round(total_cents_from_counts(restant_counts) / 100, 2),
        }
    )
    return pd.DataFrame(rows), rows


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

# ================== STATE ==================
today = datetime.now(TZ).date()
yesterday = today - timedelta(days=1)

st.session_state.setdefault("cashier", "")
st.session_state.setdefault("register_no", 1)
st.session_state.setdefault("target_dollars", 200)
st.session_state.setdefault("mode_pick", "normal")  # "normal" or "missed_close"

# IMPORTANT: editor inputs live here and we do NOT overwrite them on rerun (prevents revert-to-0)
st.session_state.setdefault("inputs_caisse_today", df_inputs_caisse_today())
st.session_state.setdefault("inputs_caisse_yesterday", df_inputs_caisse_yesterday())
st.session_state.setdefault("inputs_boite", df_inputs_boite())

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

        if "inputs_caisse_today" in saved:
            st.session_state.inputs_caisse_today = pd.DataFrame(saved["inputs_caisse_today"])
        if "inputs_caisse_yesterday" in saved:
            st.session_state.inputs_caisse_yesterday = pd.DataFrame(saved["inputs_caisse_yesterday"])

    spb, _ = boite_paths(today)
    savedb = load_json(spb)
    if savedb and "inputs_boite" in savedb:
        st.session_state.inputs_boite = pd.DataFrame(savedb["inputs_boite"])


# ================== HEADER ==================
st.title("Registre — Caisse & Boîte de monnaie")

h1, h2, h3, h4 = st.columns([1.1, 1.0, 1.2, 2.0])
with h1:
    st.write("**Date:**", today.isoformat())
with h2:
    st.write("**Heure:**", datetime.now(TZ).strftime("%H:%M"))
with h3:
    st.session_state.register_no = st.selectbox(
        "Caisse #", [1, 2, 3], index=[1, 2, 3].index(int(st.session_state.register_no)), key="reg_sel"
    )
with h4:
    st.session_state.cashier = st.text_input("Caissier(ère)", value=st.session_state.cashier, key="cashier_txt")

st.session_state.target_dollars = st.number_input(
    "Cible à laisser ($)", min_value=0, step=10, value=int(st.session_state.target_dollars), key="target_num"
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

    st.caption("Ajustement retrait: coche LOCK ✅ et mets RETRAIT_LOCK (ex: 0 pour refuser une coupure). Décoche pour déverrouiller.")

    # ------- Hier (si missed) -------
    restant_y = {k: 0 for k in DISPLAY_ORDER}
    if st.session_state.mode_pick == "missed_close":
        st.markdown("### ⚠️ Hier — fermeture non effectuée")

        inp_y = st.session_state.inputs_caisse_yesterday.copy()
        # Keep shape stable
        inp_y = inp_y[["Dénomination", "CLOSE", "LOCK", "RETRAIT_LOCK"]]

        edited_y = st.data_editor(
            inp_y,
            use_container_width=True,
            hide_index=True,
            key="editor_y_inputs",
            height=editor_height_for_rows(len(inp_y) + 1),
            column_config={
                "Dénomination": st.column_config.TextColumn(width="large"),
                "CLOSE": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
                "LOCK": st.column_config.CheckboxColumn(width="small"),
                "RETRAIT_LOCK": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            },
        )

        if st.button("✅ Appliquer (hier)", use_container_width=True, key="apply_y"):
            st.session_state.inputs_caisse_yesterday = edited_y.copy()
            st.rerun()

        # Compute from stored
        base_y = st.session_state.inputs_caisse_yesterday.copy()
        close_y = counts_from_df(base_y, "CLOSE")
        total_close_y = total_cents_from_counts(close_y)
        diff_y = total_close_y - TARGET

        locked_y = clamp_locked_counts(locks_from_df(base_y), close_y)

        retrait_y = {k: 0 for k in DISPLAY_ORDER}
        restant_y = close_y.copy()
        remaining_y = 0
        if diff_y > 0:
            retrait_y, remaining_y = suggest_retrait(diff_y, close_y, locked_y, PRIORITY_CAISSE)
            restant_y = {k: int(close_y.get(k, 0)) - int(retrait_y.get(k, 0)) for k in DISPLAY_ORDER}

        rep_y_df, rep_y_rows = build_report_yesterday(close_y, retrait_y, restant_y)
        st.markdown("#### Résultat (hier)")
        st.dataframe(rep_y_df, use_container_width=True, hide_index=True)

        if diff_y <= 0:
            st.info("Hier: sous la cible (ou égal). Aucun retrait.")
        else:
            if remaining_y == 0:
                st.success(f"À retirer (hier): {cents_to_str(diff_y)}")
            elif remaining_y < 0:
                st.warning("Verrouillage trop haut. Dépasse de " + cents_to_str(-remaining_y))
            else:
                st.warning("Impossible exact. Reste: " + cents_to_str(remaining_y))

        st.divider()

        # Auto-fill OPEN today from restant_y (but ONLY in stored inputs, not pushing into editor live)
        cur_t = st.session_state.inputs_caisse_today.copy()
        cur_t["OPEN"] = cur_t["Dénomination"].map(lambda k: int(restant_y.get(k, 0)) if k in DISPLAY_ORDER else 0)
        st.session_state.inputs_caisse_today = cur_t

    # ------- Aujourd'hui -------
    st.markdown("### Aujourd'hui")

    inp_t = st.session_state.inputs_caisse_today.copy()
    inp_t = inp_t[["Dénomination", "OPEN", "CLOSE", "LOCK", "RETRAIT_LOCK"]]

    disabled_cols = []
    if st.session_state.mode_pick != "normal":
        disabled_cols.append("OPEN")

    edited_t = st.data_editor(
        inp_t,
        use_container_width=True,
        hide_index=True,
        key="editor_t_inputs",
        height=editor_height_for_rows(len(inp_t) + 1),
        disabled=disabled_cols,
        column_config={
            "Dénomination": st.column_config.TextColumn(width="large"),
            "OPEN": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "CLOSE": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "LOCK": st.column_config.CheckboxColumn(width="small"),
            "RETRAIT_LOCK": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
        },
    )

    if st.button("✅ Appliquer (aujourd'hui)", use_container_width=True, key="apply_t"):
        st.session_state.inputs_caisse_today = edited_t.copy()
        st.rerun()

    # Compute from stored inputs
    base_t = st.session_state.inputs_caisse_today.copy()
    open_t = counts_from_df(base_t, "OPEN")
    close_t = counts_from_df(base_t, "CLOSE")

    total_open_t = total_cents_from_counts(open_t)
    total_close_t = total_cents_from_counts(close_t)
    diff_t = total_close_t - TARGET

    locked_t = clamp_locked_counts(locks_from_df(base_t), close_t)

    retrait_t = {k: 0 for k in DISPLAY_ORDER}
    restant_t = close_t.copy()
    remaining_t = 0
    if diff_t > 0:
        retrait_t, remaining_t = suggest_retrait(diff_t, close_t, locked_t, PRIORITY_CAISSE)
        restant_t = {k: int(close_t.get(k, 0)) - int(retrait_t.get(k, 0)) for k in DISPLAY_ORDER}

    rep_t_df, rep_t_rows = build_report_caisse(open_t, close_t, retrait_t, restant_t)
    st.markdown("#### Résultat (aujourd'hui)")
    st.dataframe(rep_t_df, use_container_width=True, hide_index=True)

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

    payload_caisse = {
        "meta": meta_caisse,
        "mode_pick": st.session_state.mode_pick,
        "inputs_caisse_today": st.session_state.inputs_caisse_today.to_dict(orient="records"),
        "inputs_caisse_yesterday": st.session_state.inputs_caisse_yesterday.to_dict(orient="records"),
        "rows_today": rep_t_rows,
        "rows_yesterday": rep_y_rows if st.session_state.mode_pick == "missed_close" else None,
    }

    state_path, receipt_path = caisse_paths(today)
    hc = hash_payload(payload_caisse)
    if st.session_state.last_hash_caisse != hc:
        html = receipt_html(
            "Reçu — Caisse",
            meta_caisse,
            ["Dénomination", "OPEN", "CLOSE", "RETRAIT", "RESTANT"],
            rep_t_rows,
        )
        save_json(state_path, payload_caisse)
        save_text(receipt_path, html)
        st.session_state.last_hash_caisse = hc

    with st.expander("Aperçu reçu — Caisse", expanded=False):
        components.html(load_text(receipt_path) or html, height=560, scrolling=True)


# ================== TAB: BOÎTE ==================
with tab_boite:
    st.subheader("Boîte (Échange)")
    st.caption("Entre OPEN et AJOUTÉ. Ajuste le RETRAIT via LOCK/RETRAIT_LOCK. Le RETRAIT vise = total AJOUTÉ.")

    inp_b = st.session_state.inputs_boite.copy()
    inp_b = inp_b[["Dénomination", "OPEN", "AJOUTÉ", "LOCK", "RETRAIT_LOCK"]]

    edited_b = st.data_editor(
        inp_b,
        use_container_width=True,
        hide_index=True,
        key="editor_b_inputs",
        height=editor_height_for_rows(len(inp_b) + 1),
        column_config={
            "Dénomination": st.column_config.TextColumn(width="large"),
            "OPEN": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "AJOUTÉ": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
            "LOCK": st.column_config.CheckboxColumn(width="small"),
            "RETRAIT_LOCK": st.column_config.NumberColumn(min_value=0, step=1, width="small"),
        },
    )

    if st.button("✅ Appliquer (boîte)", use_container_width=True, key="apply_b"):
        st.session_state.inputs_boite = edited_b.copy()
        st.rerun()

    base_b = st.session_state.inputs_boite.copy()
    open_b = counts_from_df(base_b, "OPEN")
    ajoute_b = counts_from_df(base_b, "AJOUTÉ")

    # availability after adding
    after_add_counts = {k: int(open_b.get(k, 0)) + int(ajoute_b.get(k, 0)) for k in DISPLAY_ORDER}

    total_ajoute = total_cents_from_counts(ajoute_b)

    locked_b = clamp_locked_counts(locks_from_df(base_b), after_add_counts)

    retrait_b = {k: 0 for k in DISPLAY_ORDER}
    restant_b = after_add_counts.copy()
    remaining_b = 0

    if total_ajoute > 0:
        retrait_b, remaining_b = suggest_retrait(total_ajoute, after_add_counts, locked_b, PRIORITY_BOITE)
        restant_b = {k: int(after_add_counts.get(k, 0)) - int(retrait_b.get(k, 0)) for k in DISPLAY_ORDER}

    rep_b_df, rep_b_rows = build_report_boite(open_b, ajoute_b, retrait_b, restant_b)
    st.markdown("#### Résultat (boîte)")
    st.dataframe(rep_b_df, use_container_width=True, hide_index=True)

    if total_ajoute == 0:
        st.info("AJOUTÉ = 0. Rien à calculer.")
    else:
        if remaining_b == 0:
            st.success(f"Change à retirer: {cents_to_str(total_ajoute)}")
        elif remaining_b < 0:
            st.warning("Verrouillage trop haut. Dépasse de " + cents_to_str(-remaining_b))
        else:
            st.warning("Impossible exact. Reste: " + cents_to_str(remaining_b))

    # Receipt + autosave
    meta_boite = {
        "Type": "BOÎTE (ÉCHANGE)",
        "Date": today.isoformat(),
        "Généré à": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "Caissier(ère)": (st.session_state.cashier.strip() or "—"),
        "Caisse #": int(st.session_state.register_no),
        "Ajouté total ($)": f"{total_ajoute/100:.2f}",
    }

    payload_boite = {
        "meta": meta_boite,
        "inputs_boite": st.session_state.inputs_boite.to_dict(orient="records"),
        "rows": rep_b_rows,
    }

    state_path_b, receipt_path_b = boite_paths(today)
    hb = hash_payload(payload_boite)
    if st.session_state.last_hash_boite != hb:
        htmlb = receipt_html(
            "Reçu — Boîte (Échange)",
            meta_boite,
            ["Dénomination", "OPEN", "AJOUTÉ", "RETRAIT (en change)", "RESTANT"],
            rep_b_rows,
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
                    else:
                        st.warning("Reçu introuvable.")
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
