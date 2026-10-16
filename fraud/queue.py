"""Analyst review queue: prioritized worklist with assignment, verdicts,
and SLA tracking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

_PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
VERDICTS = ("confirmed_fraud", "false_positive", "needs_info")


class ReviewQueue:
    def __init__(self) -> None:
        self._cases: Dict[str, Dict] = {}  # case_id -> record

    def add(self, case) -> str:
        rec = {
            "case": case,
            "status": "open",
            "assignee": None,
            "verdict": None,
            "verdict_notes": None,
            "opened_at": case.opened_at,
            "resolved_at": None,
        }
        self._cases[case.case_id] = rec
        return case.case_id

    def worklist(self) -> List[Dict]:
        """Open cases, critical first, then by oldest opened."""
        open_recs = [r for r in self._cases.values() if r["status"] == "open"]
        open_recs.sort(key=lambda r: (_PRIORITY_RANK.get(r["case"].priority, 9),
                                      r["opened_at"]))
        return [
            {"case_id": r["case"].case_id, "account_id": r["case"].account_id,
             "priority": r["case"].priority,
             "exposure": r["case"].total_exposure,
             "assignee": r["assignee"],
             "sla_hours": self.sla_hours(r["case"].case_id)}
            for r in open_recs
        ]

    def assign(self, case_id: str, analyst_id: str) -> None:
        rec = self._get(case_id)
        if rec["status"] != "open":
            raise ValueError(f"case {case_id} is not open")
        rec["assignee"] = analyst_id

    def resolve(self, case_id: str, verdict: str, analyst_id: str,
                notes: str = "") -> None:
        if verdict not in VERDICTS:
            raise ValueError(f"unknown verdict {verdict!r}; "
                             f"expected one of {VERDICTS}")
        rec = self._get(case_id)
        if rec["status"] != "open":
            raise ValueError(f"case {case_id} is not open")
        rec["status"] = "resolved"
        rec["verdict"] = verdict
        rec["verdict_notes"] = notes
        rec["assignee"] = analyst_id
        rec["resolved_at"] = datetime.now(timezone.utc).isoformat()

    def sla_hours(self, case_id: str,
                  now: Optional[datetime] = None) -> float:
        """Hours since the case was opened (open or resolved-at time)."""
        rec = self._get(case_id)
        opened = datetime.fromisoformat(rec["opened_at"].replace("Z", "+00:00"))
        end = now or datetime.now(opened.tzinfo)
        if rec["resolved_at"]:
            end = datetime.fromisoformat(
                rec["resolved_at"].replace("Z", "+00:00"))
        return round((end - opened).total_seconds() / 3600, 2)

    def stats(self) -> Dict:
        recs = list(self._cases.values())
        return {
            "open": sum(1 for r in recs if r["status"] == "open"),
            "resolved": sum(1 for r in recs if r["status"] == "resolved"),
            "confirmed_fraud": sum(1 for r in recs
                                   if r["verdict"] == "confirmed_fraud"),
            "false_positive": sum(1 for r in recs
                                  if r["verdict"] == "false_positive"),
        }

    def _get(self, case_id: str) -> Dict:
        try:
            return self._cases[case_id]
        except KeyError:
            raise ValueError(f"unknown case {case_id}") from None
