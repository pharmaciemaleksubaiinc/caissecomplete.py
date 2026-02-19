import streamlit as st
import pandas as pd
import math
from datetime import datetime

TARGET = 200.0
TOTAL_ROW_LABEL = "TOTAL"

# ============================
# Denoms (include rouleaux)
# ============================
DISPLAY_ORDER = [
    "Billet 100 $",
    "Billet 50 $",
    "Billet 20 $",
    "Billet 10 $",
    "Billet 5 $",

    "Rouleau 2 $ (25 x 2$ = 50$)",
    "Rouleau 1 $ (25 x 1$ = 25$)",
    "Rouleau 0.25 $ (40 x 0.25$ = 10$)",
    "Rouleau 0.10 $ (50 x 0.10$ = 5$)",
    "Rouleau 0.05 $ (40 x 0.05$ = 2$)",

    "Pièce 2 $",
    "Pièce 1 $",
    "Pièce 0.25 $",
    "Pièce 0.10 $",
    "Pièce 0.05 $",
]

DENOM_VALUE = {
    "Billet 100 $": 100.0,
    "Billet 50 $": 50.0,
    "Billet 20 $": 20.0,
    "Billet 10 $": 10.0,
    "Billet 5 $": 5.0,

    "Rouleau 2 $ (25 x 2$ = 50$)": 50.0,
    "Rouleau 1 $ (25 x 1$ = 25$)": 25.0,
    "Rouleau 0.25 $ (40 x 0.25$ = 10$)": 10.0,
    "Rouleau 0.10 $ (50 x 0.10$ = 5$)": 5.0,
    "Rouleau 0.05 $ (40 x 0.05$ = 2$)": 2.0,

    "Pièce 2 $": 2.0,
    "Pièce 1 $": 1.0,
    "Pièce 0.25 $": 0.25,
    "Pièce 0.10 $": 0.10,
    "Pièce 0.05 $": 0.05,
}

def safe_int(x):
    try:
        if x is None:
            return 0
        if isinstance(x, float) and math.isnan(x):
            return 0
        return int(float(x))
    except Exception:
        return 0

def editor_height(n_rows: int) -> int:
    return min(820, 60 + n_rows * 34)

def sum_money(counts_by_denom: dict) -> float:
    return float(sum(DENOM_VALUE[d] * counts_by_denom.get(d, 0) for d in DISPLAY_ORDER))

def _get_row(df: pd.DataFrame, denom: str) -> pd.Series:
    return df.loc[df["Dénomination"] == denom].iloc[0]

def _set_cell(df: pd.DataFrame, denom: str, col: str, val):
    df.loc[df["Dénomination"] == denom, col] = val

def compute_caisse_today(df: pd.DataFrame, target: float, overrides: dict):
    # Read OPEN/CLOSE counts
    open_t = {d: safe_int(_get_row(df, d)["OPEN"]) for d in DISPLAY_ORDER}
    close_t = {d: safe_int(_get_row(df, d)["CLOSE"]) for d in DISPLAY_ORDER}

    close_total = sum_money(close_t)
    to_withdraw_amount = max(0.0, close_total - float(target))

    # Start suggested retrait at 0
    retrait_t = {d: 0 for d in DISPLAY_ORDER}

    overrides = overrides or {}

    # Apply overrides as fixed counts first (clamped)
    for d, v in overrides.items():
        if d in retrait_t:
            retrait_t[d] = max(0, min(safe_int(v), close_t.get(d, 0)))

    fixed_withdrawn = sum_money(retrait_t)
    remaining_to_withdraw = max(0.0, to_withdraw_amount - fixed_withdrawn)

    # Greedy fill on non-overridden denoms
    for d in DISPLAY_ORDER:
        if d in overrides:
            continue
        if remaining_to_withdraw <= 1e-9:
            break

        val = DENOM_VALUE[d]
        avail = close_t[d] - retrait_t[d]
        if avail <= 0:
            continue

        take = min(avail, int(remaining_to_withdraw // val))
        if take > 0:
            retrait_t[d] += take
            remaining_to_withdraw -= take * val

    restant_t = {d: max(0, close_t[d] - retrait_t[d]) for d in DISPLAY_ORDER}

    retrait_total = sum_money(retrait_t)
    restant_total = sum_money(restant_t)

    diff_t = restant_total - float(target)
    leftover_t = remaining_to_withdraw

    # Write into df (in-place)
    for d in DISPLAY_ORDER:
        _set_cell(df, d, "RETRAIT", int(retrait_t[d]))
        _set_cell(df, d, "RESTANT", int(restant_t[d]))

    _set_cell(df, TOTAL_ROW_LABEL, "OPEN", sum_money(open_t))
    _set_cell(df, TOTAL_ROW_LABEL, "CLOSE", close_total)
    _set_cell(df, TOTAL_ROW_LABEL, "RETRAIT", retrait_total)
    _set_cell(df, TOTAL_ROW_LABEL, "RESTANT", restant_total)

    return open_t, close_t, retrait_t, restant_t, diff_t, leftover_t, {}


# ============================
# Metadata (name, caisse #, datetime)
# Put this in your Today tab above the editor
# ============================
if "meta_today" not in st.session_state:
    st.session_state.meta_today = {
        "nom": "",
        "caisse_no": "",
        "dt": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    st.session_state.meta_today["nom"] = st.text_input("Nom", st.session_state.meta_today["nom"])
with c2:
    st.session_state.meta_today["caisse_no"] = st.text_input("Numéro de caisse", st.session_state.meta_today["caisse_no"])
with c3:
    st.session_state.meta_today["dt"] = st.text_input("Date & heure (YYYY-MM-DD HH:MM)", st.session_state.meta_today["dt"])

st.divider()

# ============================
# Critical part: overrides start empty
# ============================
if "over_caisse_today" not in st.session_state:
    st.session_state.over_caisse_today = {}

# Your df must already exist in session_state (you already had this)
# st.session_state.df_caisse_today = ...

# --- Compute suggestions BEFORE editor ---
open_t, close_t, retrait_t, restant_t, diff_t, leftover_t, _ = compute_caisse_today(
    st.session_state.df_caisse_today, TARGET, st.session_state.over_caisse_today
)

# Build display DF (suggestions visible)
df_t_display = st.session_state.df_caisse_today.copy()
for k in DISPLAY_ORDER:
    df_t_display.loc[df_t_display["Dénomination"] == k, "RETRAIT"] = int(retrait_t.get(k, 0))
    df_t_display.loc[df_t_display["Dénomination"] == k, "RESTANT"] = int(restant_t.get(k, 0))

# Keep totals coherent
for col in ["OPEN", "CLOSE", "RETRAIT", "RESTANT"]:
    df_t_display.loc[df_t_display["Dénomination"] == TOTAL_ROW_LABEL, col] = st.session_state.df_caisse_today.loc[
        st.session_state.df_caisse_today["Dénomination"] == TOTAL_ROW_LABEL, col
    ].values[0]

# --- Make the editor look bolder (Streamlit workaround) ---
st.markdown(
    """
    <style>
      /* data editor body text */
      div[data-testid="stDataFrame"] * { font-weight: 650 !important; }
      /* headers */
      div[data-testid="stDataFrame"] thead * { font-weight: 750 !important; }
    </style>
    """,
    unsafe_allow_html=True
)

disabled_cols = ["Dénomination", "RESTANT"]  # keep your missed-close logic if you had it

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

# --- Apply button: commit OPEN/CLOSE + update overrides only where user edited RETRAIT ---
if st.button("✅ Appliquer (aujourd'hui)", use_container_width=True, key="apply_t"):

    # 1) Commit OPEN/CLOSE into stored df
    df_store = st.session_state.df_caisse_today.copy()
    for k in DISPLAY_ORDER:
        df_store.loc[df_store["Dénomination"] == k, "OPEN"] = safe_int(
            edited_t.loc[edited_t["Dénomination"] == k, "OPEN"].values[0]
        )
        df_store.loc[df_store["Dénomination"] == k, "CLOSE"] = safe_int(
            edited_t.loc[edited_t["Dénomination"] == k, "CLOSE"].values[0]
        )
    st.session_state.df_caisse_today = df_store

    # 2) Determine actual edited RETRAIT rows
    editor_state = st.session_state.get("editor_caisse_t", {})
    edited_rows = editor_state.get("edited_rows", {}) or {}

    idx_to_denom = {i: str(df_t_display.iloc[i]["Dénomination"]) for i in range(len(df_t_display))}

    # Recompute suggestion BEFORE updating overrides
    _, _, suggested_ret, _, _, _, _ = compute_caisse_today(
        st.session_state.df_caisse_today, TARGET, st.session_state.over_caisse_today
    )

    overrides = dict(st.session_state.over_caisse_today)

    for row_idx, changes in edited_rows.items():
        denom = idx_to_denom.get(int(row_idx))
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

    # Keep your existing "save today" function call here (DON'T delete it)
    # save_today_state(...)

    st.rerun()
