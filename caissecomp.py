# --- BEFORE showing the editor, compute the suggestion from OPEN/CLOSE + overrides ---
open_t, close_t, retrait_t, restant_t, diff_t, leftover_t, _ = compute_caisse_today(
    st.session_state.df_caisse_today, TARGET, st.session_state.over_caisse_today
)

# Build the display DF (with suggested RETRAIT already filled in)
df_t_display = st.session_state.df_caisse_today.copy()
for k in DISPLAY_ORDER:
    df_t_display.loc[df_t_display["Dénomination"] == k, "RETRAIT"] = int(retrait_t.get(k, 0))
    df_t_display.loc[df_t_display["Dénomination"] == k, "RESTANT"] = int(restant_t.get(k, 0))

# totals already written by compute_caisse_today in session df, but we keep display coherent:
df_t_display.loc[df_t_display["Dénomination"] == TOTAL_ROW_LABEL, "OPEN"] = st.session_state.df_caisse_today.loc[
    st.session_state.df_caisse_today["Dénomination"] == TOTAL_ROW_LABEL, "OPEN"
].values[0]
df_t_display.loc[df_t_display["Dénomination"] == TOTAL_ROW_LABEL, "CLOSE"] = st.session_state.df_caisse_today.loc[
    st.session_state.df_caisse_today["Dénomination"] == TOTAL_ROW_LABEL, "CLOSE"
].values[0]
df_t_display.loc[df_t_display["Dénomination"] == TOTAL_ROW_LABEL, "RETRAIT"] = st.session_state.df_caisse_today.loc[
    st.session_state.df_caisse_today["Dénomination"] == TOTAL_ROW_LABEL, "RETRAIT"
].values[0]
df_t_display.loc[df_t_display["Dénomination"] == TOTAL_ROW_LABEL, "RESTANT"] = st.session_state.df_caisse_today.loc[
    st.session_state.df_caisse_today["Dénomination"] == TOTAL_ROW_LABEL, "RESTANT"
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
    disabled=disabled_cols,  # Dénomination + RESTANT disabled; OPEN disabled in missed_close mode
)

# --- Apply button: commit OPEN/CLOSE, and update overrides ONLY where user edited RETRAIT ---
if st.button("✅ Appliquer (aujourd'hui)", use_container_width=True, key="apply_t"):

    # 1) Commit OPEN/CLOSE from edited table into the real stored df
    df_store = st.session_state.df_caisse_today.copy()
    for k in DISPLAY_ORDER:
        df_store.loc[df_store["Dénomination"] == k, "OPEN"] = safe_int(
            edited_t.loc[edited_t["Dénomination"] == k, "OPEN"].values[0]
        )
        df_store.loc[df_store["Dénomination"] == k, "CLOSE"] = safe_int(
            edited_t.loc[edited_t["Dénomination"] == k, "CLOSE"].values[0]
        )
    st.session_state.df_caisse_today = df_store

    # 2) Determine which rows user actually edited in RETRAIT
    # Streamlit gives indices, not denom labels. We map index -> denom.
    editor_state = st.session_state.get("editor_caisse_t", {})
    edited_rows = editor_state.get("edited_rows", {}) or {}

    # Build index -> denom map from the displayed df
    idx_to_denom = {i: str(df_t_display.iloc[i]["Dénomination"]) for i in range(len(df_t_display))}

    # Recompute current suggestions (based on current overrides BEFORE updating)
    _, _, suggested_ret, _, _, _, _ = compute_caisse_today(
        st.session_state.df_caisse_today, TARGET, st.session_state.over_caisse_today
    )

    overrides = dict(st.session_state.over_caisse_today)  # start from existing overrides

    for row_idx, changes in edited_rows.items():
        denom = idx_to_denom.get(int(row_idx))
        if not denom or denom == TOTAL_ROW_LABEL:
            continue

        if "RETRAIT" in changes:
            user_val = safe_int(changes["RETRAIT"])
            sugg_val = int(suggested_ret.get(denom, 0))

            # If user differs from suggestion, treat as override.
            if user_val != sugg_val:
                overrides[denom] = user_val
            else:
                # User set it back to suggested -> remove override (aka "unlock")
                overrides.pop(denom, None)

    st.session_state.over_caisse_today = overrides

    # 3) Final compute writes RETRAIT/RESTANT + totals into df_store
    compute_caisse_today(st.session_state.df_caisse_today, TARGET, st.session_state.over_caisse_today)
    st.rerun()
