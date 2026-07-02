"""Ephemeral phantom → local SQLite database.

Spins up a throwaway Phantombuster script + agent, runs it, extracts the structured
results into a local SQLAlchemy SQLite database, then deletes the phantom so nothing
persists in your Phantombuster account.

    python examples/ephemeral_workflow.py

The demo phantom is a self-contained Node script that emits deterministic rows, so the
workflow is reproducible without any external login. See EPHEMERAL-WORKFLOW.md for the
full explanation and how to adapt it to a real scraping script.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import Integer, String, JSON, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from phantombuster import Phantombuster

API_KEY = os.environ.get(
    "PHANTOMBUSTER_API_KEY", ""
)
DB_URL = os.environ.get("DB_URL", "sqlite:///ephemeral_leads.db")

# A self-contained Node phantom. Replace the body with real scraping logic; the
# only hard requirement is the config block and a call to buster.setResultObject().
PHANTOM_SCRIPT = """// Phantombuster configuration {
"phantombuster command: nodejs"
"phantombuster package: 5"
// }
const Buster = require("phantombuster")
const buster = new Buster()
;(async () => {
  let arg = {}
  try { arg = typeof buster.argument === "string" ? JSON.parse(buster.argument) : (buster.argument || {}) } catch (e) {}
  const n = arg.count || 3
  const rows = []
  for (let i = 1; i <= n; i++) {
    rows.push({ rank: i, name: "Lead " + i, email: "lead" + i + "@example.com" })
  }
  console.log("Generating " + rows.length + " rows")
  await buster.setResultObject(rows)
  console.log("Done.")
  process.exit()
})()
"""


class Base(DeclarativeBase):
    pass


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    container_id: Mapped[str] = mapped_column(String)
    rank: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)
    raw: Mapped[dict] = mapped_column(JSON)  # keep the full row for anything unmapped


def main() -> None:
    engine = create_engine(DB_URL)
    Base.metadata.create_all(engine)
    pb = Phantombuster(API_KEY)

    # Create → run → auto-delete, all in one call. Teardown is guaranteed.
    print("Running ephemeral phantom …")
    run = pb.run_ephemeral(
        name="ephemeral leads",
        code=PHANTOM_SCRIPT,
        argument={"count": 5},
        timeout=180,
        poll=4,
    )
    print(f"  container={run.container_id} exit={run.exit_code} rows={len(run.result or [])}")

    if not run.succeeded:
        print("Run did not succeed; console tail:")
        print((run.output or "")[-500:])
        return

    # Extract the per-run result object into SQLite.
    with Session(engine) as session:
        for row in run.result or []:
            session.add(
                Lead(
                    container_id=run.container_id,
                    rank=row.get("rank"),
                    name=row.get("name"),
                    email=row.get("email"),
                    raw=row,
                )
            )
        session.commit()

    with Session(engine) as session:
        total = session.scalar(select(func.count()).select_from(Lead))
        print(f"SQLite now holds {total} lead row(s):")
        for lead in session.scalars(select(Lead).order_by(Lead.rank)):
            print(f"  {lead.rank:>2}  {lead.name:<10} {lead.email}")

    # Prove nothing was left behind in the Phantombuster account.
    remaining = [a for a in pb.list_agents() if a["name"] == "ephemeral leads"]
    print(f"Ephemeral agents remaining in account: {len(remaining)}")


if __name__ == "__main__":
    main()
