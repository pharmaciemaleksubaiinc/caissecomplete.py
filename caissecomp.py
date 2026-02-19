import streamlit as st
import pandas as pd
import math

# -----------------------------
# Constants / helpers
# -----------------------------
TOTAL_ROW_LABEL = "TOTAL"
TARGET = 200

# Order shown in table (largest -> smallest helps for greedy withdrawal)
DISPLAY_ORDER = [
    "Billet 100 $",
    "Billet 50 $",
    "Billet 20 $",
    "Billet 10 $",
    "Billet 5 $",
    "Pièce 2 $",
    "Pièce 1 $",
    "Pièce 0.25 $",
    "Pièce 0.10 $",
    "Pièce 0.05 $",
]

DENOM_VALUE = {
    "Billet 100 $": 100,
    "Billet 50 $": 50,
    "Billet 20 $": 20,
    "Billet 10 $": 10,
    "Billet 5 $": 5,
    "Pièce 2 $": 2,
    "Pièce 1 $": 1,
    "Pièce 0.25 $": 0.25,
    "Pièce 0.10 $": 0.10,
    "Pièce 0.05 $": 0.05,
}

def safe_int(x):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return 0
        # accept strings, floats, ints
        return int(float(x))
    except Exception:
        return 0

def editor_height(n_rows: int) -> int:
    return min(800, 40 + n_rows * 35)

def _get_row(df: pd.DataFrame, denom: str) -> pd.Series:
    return df.loc[df["Dénomination"] == denom].iloc[0]

def _set_cell(df: pd.DataFrame, denom: str, col: str, val):
    df.loc[df["Dénomination"] == denom, col] = val

def _sum_money(amounts_by_denom: dict) -> float:
    return sum(DENOM_VALUE[d] * amounts_by_denom.get(d, 0) for d in DISPLAY_ORDER)

# -----------------------------
# Core compute
# -----------------------------
def compute_caisse_today(df: pd.DataFrame, target: float, overrides: dict):
    """
    Computes suggested RETRAIT to reach `target` remaining cash (RESTANT total),
    while respecting per-denom overrides when provided.

    Returns:
      open_t, close_t, retrait_t, restant_t, diff_t, leftover_t, debug
    Also writes RETRAIT/RESTANT + totals into df in-place (streamlit state DF).
    """
    # Read OPEN/CLOSE counts
    open_t = {d: safe_int(_get_row(df, d)["OPEN"]) for d in DISPLAY_ORDER}
    close_t = {d: safe_int(_get_row(df, d)["CLOSE"]) for d in DISPLAY_ORDER}

    close_total = _sum_money(close_t)

    # How much should be withdrawn (in $) to leave exactly target?
    to_withdraw_amount = max(0.0, close_total - float(target))

    # Start with suggestion = 0
    retrait_t = {d: 0 for d in DISPLAY_ORDER}

    # Apply overrides as fixed counts first (clamped to available close counts)
    for d, v in (overrides or {}).items():
        if d in retrait_t:
            retrait_t[d] = max(0, min(safe_int(v), close_t.get(d, 0)))

    fixed_withdrawn = _sum_money(retrait_t)
    remaining_to_withdraw = max(0.0, to_withdraw_amount - fixed_withdrawn)

    # Greedy fill on non-overridden denoms: largest -> smallest
    for d in DISPLAY_ORDER:
        if overrides and d in overrides:
            continue  # user locked this denom
        if remaining_to_withdraw <= 1e-9:
            break

        val = DENOM_VALUE[d]
        avail = close_t[d] - retrait_t[d]
        if avail <= 0:
            continue

        # max units we can take from this denom
        take = min(avail, int(remaining_to_withdraw // val))
        if take > 0:
            retrait_t[d] += take
            remaining_to_withdraw -= take * val

    # Compute restant counts
    restant_t = {d: max(0, close_t[d] - retrait_t[d]) for d in DISPLAY_ORDER}

    retrait_total = _sum_money(retrait_t)
    restant_total = _sum_money(restant_t)

    # diff: how far remaining total is from target
    diff_t = restant_total - float(target)
    leftover_t = remaining_to_withdraw  # what couldn't be matched due to denominations/availability

    # Write per-denom into df
    for d in DISPLAY_ORDER:
        _set_cell(df, d, "RETRAIT", int(retrait_t[d]))
        _set_cell(df, d, "RESTANT", int(restant_t[d]))

    # Totals row (store as money totals)
    _set_cell(df, TOTAL_ROW_LABEL, "OPEN", _sum_money(open_t))
    _set_cell(df, TOTAL_ROW_LABEL, "CLOSE", close_total)
    _set_cell(df, TOTAL_ROW_LABEL, "RETRAIT", retrait_total)
    _set_cell(df, TOTAL_ROW_LABEL, "RESTANT", restant_total)

    debug = {
        "close_total": close_total,
        "to_withdraw_amount": to_withdraw_amount,
        "fixed_withdrawn": fixed_withdrawn,
        "leftover_unmatched": leftover_t,
        "restant_total": restant_total,
        "diff_vs_target": diff_t,
    }

    return open_t, close_t, retrait_t, restant_t, diff_t, leftover_t, debug


# -----------------------------
# Demo DF initializer (replace with your real loader)
# -----------------------------
def make_default_df_today():
    rows = []
    for d in DISPLAY_ORDER:
        rows.append({"Dénomination": d, "OPEN": 0, "CLOSE": 0, "RETRAIT": 0, "RESTANT": 0})
    rows.append({"Dénomination": TOTAL_ROW_LABEL, "OPEN": 0, "CLOSE": 0, "RETRAIT": 0, "RESTANT": 0})
    return pd.DataFrame(rows)

# -----------------------------
# Streamlit state init
# -----------------------------
if "df_caisse_today" not in st.session_state:
    st.session_state.df_caisse_today = make_default_df_today()

if "over_caisse_today" not in st.session_state:
    st.session_state.over_caisse_today = {}  # only stores the rows user edited

# -----------------------------
# UI: "Aujourd'hui" table
# -----------------------------
st.subheader("Caisse - Aujourd'hui")

# Disabled cols: denom and restant always. (You can add OPEN disable in missed-close mode elsewhere.)
disabled_cols = ["Dénomination", "RESTANT"]

# --- BEFORE showing editor: compute suggestion from OPEN/CLOSE + overrides ---
open_t, close_t, retrait_t, restant_t, diff_t, leftover_t, _ = compute_caisse_today(
    st.session_state.df_caisse_today, TARGET, st.session_state.over_caisse_today
)

# Build the display DF (with suggested RETRAIT/RESTANT already filled in)
df_t_display = st.session_state.df_caisse_today.copy()

for k in DISPLAY_ORDER:
    df_t_display.loc[df_t_display["Dénomination"] == k, "RETRAIT"] = int(retrait_t.get(k, 0))
    df_t_display.loc[df_t_display["Dénomination"] == k, "RESTANT"] = int(restant_t.get(k, 0))

# Keep totals coherent in display
for col in ["OPEN", "CLOSE", "RETRAIT", "RESTANT"]:
    df_t_display.loc[df_t_display["Dénomination"] == TOTAL_ROW_LABEL, col] = st.session_state.df_caisse_today.loc[
        st.session_state.df_caisse_today["Dénomination"] == TOTAL_ROW_LABEL, col
    ].values[0]

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

# --- Apply button: commit OPEN/CLOSE, update overrides ONLY where user edited RETRAIT ---
if st.button("✅ Appliquer (aujourd'hui)", use_container_width=True, key="apply_t"):

    # 1) Commit OPEN/CLOSE from edited table into stored df
    df_store = st.session_state.df_caisse_today.copy()
    for k in DISPLAY_ORDER:
        df_store.loc[df_store["Dénomination"] == k, "OPEN"] = safe_int(
            edited_t.loc[edited_t["Dénomination"] == k, "OPEN"].values[0]
        )
        df_store.loc[df_store["Dénomination"] == k, "CLOSE"] = safe_int(
            edited_t.loc[edited_t["Dénomination"] == k, "CLOSE"].values[0]
        )
    st.session_state.df_caisse_today = df_store

    # 2) Which rows user actually edited in RETRAIT (Streamlit gives row indices)
    editor_state = st.session_state.get("editor_caisse_t", {})
    edited_rows = editor_state.get("edited_rows", {}) or {}

    # Build index -> denom map from displayed df
    idx_to_denom = {i: str(df_t_display.iloc[i]["Dénomination"]) for i in range(len(df_t_display))}

    # Recompute suggestions based on current overrides BEFORE updating them
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

            # If user differs from suggestion -> override
            if user_val != sugg_val:
                overrides[denom] = user_val
            else:
                # If user set back to suggestion -> unlock
                overrides.pop(denom, None)

    st.session_state.over_caisse_today = overrides

    # 3) Final compute writes RETRAIT/RESTANT + totals into df_store
    compute_caisse_today(st.session_state.df_caisse_today, TARGET, st.session_state.over_caisse_today)
    st.rerun()
