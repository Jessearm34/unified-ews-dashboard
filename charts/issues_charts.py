"""Chart builders for the cross-platform Issues Needing Attention panel."""

from __future__ import annotations

from typing import Any


SEVERITY_COLORS = {
    "high": "#dc2626",
    "medium": "#ea580c",
    "low": "#eab308",
}

SEVERITY_LABELS = {
    "high": "High",
    "medium": "Med",
    "low": "Low",
}

PLATFORM_BADGES = {
    "SD": '<span class="badge" style="background:#2563eb;color:#fff">SD</span>',
    "GT": '<span class="badge" style="background:#0e7490;color:#fff">GT</span>',
}


def issues_table(issues: list[dict[str, Any]]) -> str:
    """Render the issues list as an HTML table."""
    if not issues:
        return '<div class="chart-empty">No issues — everything on track.</div>'

    # Limit display to 15
    rows = []
    for i in issues[:15]:
        sev = i.get("severity", "low")
        sev_color = SEVERITY_COLORS.get(sev, "#64748b")
        sev_label = SEVERITY_LABELS.get(sev, "—")
        plt_badge = PLATFORM_BADGES.get(i.get("platform", ""), "")
        rows.append(
            f'<tr>'
            f'<td><span class="dot" style="background:{sev_color};display:inline-block;'
            f'width:8px;height:8px;border-radius:50%;margin-right:6px;"></span>'
            f'<span style="font-size:11px;color:#64748b">{sev_label}</span></td>'
            f'<td>{plt_badge}</td>'
            f'<td><strong>{i["label"]}</strong><br>'
            f'<span class="note">{i.get("detail", "")}</span></td>'
            f'</tr>'
        )

    header = '<thead><tr><th>Priority</th><th></th><th>Issue</th></tr></thead>'
    return (
        f'<div class="tbl-wrap" style="max-height:400px">'
        f'<table class="data">{header}<tbody>{"".join(rows)}</tbody></table>'
        f'</div>'
    )
