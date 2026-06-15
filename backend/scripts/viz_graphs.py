"""
Render the agent graphs (fixed pipeline + controller loop) to Mermaid (+ PNG if the
network renderer is reachable). The controller's gate/ask nodes only exist when compiled
with a checkpointer, so we use an in-memory saver to show the COMPLETE graph (no Redis).

    cd backend && python scripts/viz_graphs.py
Outputs land in docs/agent_graphs/ (.mmd you can paste into https://mermaid.live, + .png).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.memory import MemorySaver

from agents.orchestrator import controller
from agents.orchestrator.graph import _build_graph

OUT = Path(__file__).resolve().parents[2] / "docs" / "agent_graphs"
OUT.mkdir(parents=True, exist_ok=True)


def render(name: str, compiled) -> None:
    g = compiled.get_graph()
    mmd = g.draw_mermaid()
    (OUT / f"{name}.mmd").write_text(mmd, encoding="utf-8")
    print(f"\n===== {name} =====\n{mmd}")
    try:
        png = g.draw_mermaid_png()  # uses the mermaid.ink API (needs network)
        (OUT / f"{name}.png").write_bytes(png)
        print(f"[png] wrote {name}.png")
    except Exception as exc:
        print(f"[png] skipped {name}.png ({type(exc).__name__}: {exc}) — use the .mmd at mermaid.live")


def main() -> None:
    saver = MemorySaver()
    render("fixed_pipeline", _build_graph(saver))
    render("controller_loop", controller.build_controller_graph(saver))
    print(f"\nFiles in: {OUT}")


if __name__ == "__main__":
    main()
