"""
Deep Query — Skill library seeder

Loads the version-controlled SKILL.md files under ``backend/skills/library/*/SKILL.md``
into the live skills DB (the source of truth). Idempotent: creates a skill if its name is
new, otherwise updates the body/description/metadata to match the file (a new reversible
version). Run from the backend dir:

    python -m skills.library.seed_library
    # or: python skills/library/seed_library.py

These are house-template skills the agent loads for ``produce`` (e.g. pptx-deck-design):
their body becomes design instructions to the document script generator.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script (python skills/library/seed_library.py) by ensuring the
# backend root is importable.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from core.database import SessionLocal, init_db
from skills import service
from skills.parser import parse_skill_markdown

_LIBRARY = Path(__file__).resolve().parent


def seed() -> None:
    init_db()  # ensure tables exist
    files = sorted(_LIBRARY.glob("*/SKILL.md"))
    if not files:
        print("no SKILL.md files found under", _LIBRARY)
        return
    db = SessionLocal()
    try:
        for path in files:
            parsed = parse_skill_markdown(path.read_text(encoding="utf-8"))
            existing = service.get_skill_by_name(db, parsed["name"])
            if existing is None:
                service.create_skill(
                    db, name=parsed["name"], description=parsed["description"],
                    kind=parsed["kind"], body=parsed["body"], metadata=parsed["metadata"] or None,
                )
                print(f"created  {parsed['name']}  (v1)")
            else:
                changed = (existing.body.strip() != parsed["body"].strip()
                           or existing.description.strip() != parsed["description"].strip())
                if changed:
                    service.update_human_intent(
                        db, existing.id, body=parsed["body"], description=parsed["description"],
                        metadata=parsed["metadata"] or None, by="library-seed",
                    )
                    print(f"updated  {parsed['name']}  (v{existing.current_version})")
                else:
                    print(f"unchanged {parsed['name']}  (v{existing.current_version})")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
