"""Hash-chained audit ledger: every detection, case assembly, assignment,
and verdict is recorded immutably.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, List


class FraudLedger:
    def __init__(self) -> None:
        self.entries: List[Dict] = []

    def record(self, event_type: str, payload: Dict) -> Dict:
        prev = self.entries[-1]["hash"] if self.entries else "GENESIS"
        entry = {
            "seq": len(self.entries),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": payload,
            "prev_hash": prev,
        }
        body = json.dumps(entry, sort_keys=True)
        entry["hash"] = hashlib.sha256(body.encode()).hexdigest()
        self.entries.append(entry)
        return entry

    def verify_chain(self) -> bool:
        """Recompute every hash and linkage; False on any tampering."""
        prev = "GENESIS"
        for entry in self.entries:
            if entry["prev_hash"] != prev:
                return False
            check = {k: v for k, v in entry.items() if k != "hash"}
            if hashlib.sha256(json.dumps(check, sort_keys=True).encode()
                              ).hexdigest() != entry["hash"]:
                return False
            prev = entry["hash"]
        return True

    def events_of(self, event_type: str) -> List[Dict]:
        return [e for e in self.entries if e["event_type"] == event_type]
