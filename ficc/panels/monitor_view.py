"""Monitor controls, saved watchlists and daily-move context."""

from __future__ import annotations

import streamlit as st

from .. import monitor, theme, ui, workspace


def preferences() -> workspace.Watchlist:
    if "watchlist" not in st.session_state:
        try:
            st.session_state.watchlist = workspace.load_watchlist()
        except workspace.WatchlistError as exc:
            st.session_state.watchlist_load_error = str(exc)
            st.session_state.watchlist = workspace.Watchlist()
    if st.session_state.get("watchlist_load_error"):
        st.warning(st.session_state.watchlist_load_error)
    return st.session_state.watchlist


def select_watchlist(groups, labels):
    """Keep saved order, including across the monitor's usual groups."""
    by_label = {row.label: row for _, rows in groups for row in rows if row is not None}
    return [("My watchlist", [by_label[label] for label in labels if label in by_label])]


def render(groups) -> None:
    saved = preferences()
    view = st.radio(
        "Monitor view",
        workspace.VIEWS,
        index=workspace.VIEWS.index(saved.default_view),
        key="monitor_view",
        horizontal=True,
        label_visibility="collapsed",
    )
    with st.expander("Find, watchlist & export"):
        query = st.text_input(
            "Find an instrument", key="monitor_query", placeholder="e.g. HY, JGB, SOFR"
        )
        group_names = [name for name, _ in groups]
        selected_group = st.selectbox(
            "Instrument group", ["All groups", *group_names], key="monitor_group"
        )
        available = [row.label for _, rows in groups for row in rows if row is not None]
        options = list(dict.fromkeys([*saved.labels, *available]))
        with st.form("watchlist_editor"):
            labels = st.multiselect(
                "Saved instruments",
                options,
                default=list(saved.labels),
                help="Select instruments in the order you want them to appear.",
                key="watchlist_labels",
            )
            default_watchlist = st.checkbox(
                "Open my watchlist by default",
                value=saved.default_view == "My watchlist",
                key="watchlist_default",
            )
            if st.form_submit_button("Save watchlist", key="save_watchlist"):
                updated = workspace.Watchlist(
                    tuple(labels), "My watchlist" if default_watchlist else "All instruments"
                )
                try:
                    workspace.save_watchlist(updated)
                except workspace.WatchlistError as exc:
                    st.error(str(exc))
                else:
                    saved = updated
                    st.session_state.watchlist = updated
                    st.session_state.pop("watchlist_load_error", None)
                    st.success("Watchlist saved on this computer.")

        filtered = monitor.filter_groups(groups, query, selected_group)
        shown = select_watchlist(filtered, saved.labels) if view == "My watchlist" else filtered
        st.download_button(
            "Download displayed instruments",
            monitor.to_frame(shown).to_csv(index=False),
            "ficc-monitor.csv",
            "text/csv",
            key="monitor_csv",
        )

    full = st.checkbox(
        "Show all columns on small screens",
        key="monitor_full",
        help="Compact view keeps Last, 1D and As of visible on a phone. "
        "Full view scrolls horizontally; instrument names stay in place.",
    )
    if view == "My watchlist":
        unavailable = [label for label in saved.labels if label not in available]
        if unavailable:
            st.caption("Currently unavailable: " + ", ".join(unavailable))
    if not any(row is not None for _, rows in shown for row in rows):
        if view == "My watchlist" and not saved.labels:
            st.info("Choose saved instruments in Find, watchlist & export to build your watchlist.")
        elif view == "My watchlist" and len(unavailable) == len(saved.labels):
            st.info("Your saved instruments are currently unavailable. Try All instruments.")
        else:
            st.info("No instruments match. Clear the search or choose All groups.")
        return

    _moves(shown)
    st.markdown(monitor.render_html(shown, full=full), unsafe_allow_html=True)


def _moves(groups) -> None:
    ranked = monitor.rank_moves(groups, limit=3)
    if ranked.empty:
        st.caption("Unusual moves: no fresh daily series with enough usable history.")
        return
    ui.section("Unusual daily moves", "ranked within the displayed instruments")
    rows = []
    for record in ranked.to_dict("records"):
        change = record["Change"]
        unit = record["Change unit"]
        dp = 2 if unit == "%" else 1
        color = theme.delta_color(change, mode="rates")
        previous, latest = record["Previous date"], record["As of"]
        percentile = record["Absolute move percentile"]
        sample = record["Sample count"]
        rows.append(
            '<div class="ficc-move">'
            f"<strong>{ui.esc(record['Instrument'])}</strong>"
            f'<span style="color:{color}">{change:+.{dp}f} {unit}</span>'
            f"<small>{previous:%d %b} → {latest:%d %b %Y}</small>"
            f'<small title="Compared with {sample} prior daily changes">'
            f"Move percentile {percentile:.0f}</small></div>"
        )
    st.markdown('<div class="ficc-moves">' + "".join(rows) + "</div>", unsafe_allow_html=True)
    with st.expander("How moves are ranked"):
        st.caption(
            "Absolute daily changes are compared with each instrument’s own prior changes "
            "over up to three years, excluding the current move. At least 60 comparisons are "
            "required. Weekly, stale and suspect observations are excluded. Percentiles describe "
            "historical move size, not the chance of a future move. Dates may differ by source."
        )
