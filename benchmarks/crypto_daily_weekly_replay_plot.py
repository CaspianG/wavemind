from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def render_chart(summary_path: Path) -> Path:
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assets = payload["by_symbol"]
    labels = [r["symbol"].split("/")[0] for r in assets]
    by_asset = [{v["engine"]: v for v in r["results"]} for r in assets]
    x = np.arange(len(labels))
    fig, axes = plt.subplots(1, 2, figsize=(16, 6.7), dpi=130)
    fig.patch.set_facecolor("white")
    first_origin = datetime.fromisoformat(payload["protocol"]["start_utc"])
    as_of = datetime.fromisoformat(payload["as_of_utc"])
    last_origin = as_of.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
    fig.suptitle(
        f"WaveMind: settled weekly forecasts, {first_origin:%b %d} - {last_origin:%b %d, %Y}",
        fontsize=18, y=0.96,
    )
    colors = {"WaveMind research": "#167d8d", "Weekly momentum": "#c06b35", "Always up": "#707780", "Last price": "#707780"}
    for offset, engine in enumerate(("WaveMind research", "Weekly momentum", "Always up")):
        values = [r[engine]["direction_accuracy"] * 100 for r in by_asset]
        axes[0].bar(x + (offset - 1) * 0.24, values, width=0.23, color=colors[engine], label=engine)
    axes[0].axhline(50, color="#adb2b8", linestyle="--", linewidth=1)
    axes[0].set_ylim(0, 100)
    axes[0].set_title("Correct direction (%)", fontsize=14, pad=15)
    axes[0].set_xticks(x, labels)
    axes[0].legend(loc="lower center", bbox_to_anchor=(0.5, -0.24), ncol=2, frameon=False, fontsize=10)
    for offset, engine in enumerate(("WaveMind research", "Last price")):
        values = [r[engine]["price_mape_pct"] for r in by_asset]
        group = axes[1].bar(x + (offset - 0.5) * 0.34, values, width=0.32, color=colors[engine], label=engine)
        axes[1].bar_label(group, fmt="%.1f", fontsize=9, padding=3)
    axes[1].set_title("Target-price error (MAPE %, lower is better)", fontsize=14, pad=15)
    axes[1].set_xticks(x, labels)
    axes[1].legend(loc="lower center", bbox_to_anchor=(0.5, -0.24), ncol=2, frameon=False, fontsize=10)
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_axisbelow(True)
        ax.yaxis.grid(True, alpha=0.18)
        ax.tick_params(axis="x", labelsize=10)
    fig.text(0.06, 0.055, f"{payload['matured']} settled forecasts; {payload['pending']} pending excluded. Daily horizons overlap; assets share market exposure.", fontsize=11)
    fig.text(0.06, 0.018, "Research targets from the unchanged live model. The weekly trade policy admits zero trades. Source: frozen OKX / GRAM-TON snapshots.", fontsize=10, color="#555b62")
    fig.subplots_adjust(top=0.83, bottom=0.29, left=0.055, right=0.98, wspace=0.22)
    output = summary_path.parent / "overview.png"
    fig.savefig(output, facecolor="white")
    plt.close(fig)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot verified daily weekly replay results")
    parser.add_argument("summary", type=Path)
    args = parser.parse_args()
    print(render_chart(args.summary))


if __name__ == "__main__":
    main()
