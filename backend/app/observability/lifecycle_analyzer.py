"""
Grievance Lifecycle Metrics & Redressal Performance Engine.
Analyzes the end-to-end multi-stage grievance lifecycle:
  Submission -> AI Classification -> Assignment -> Officer Action -> Resolution

Calculates:
- Average Resolution Time (Mean)
- P50 (Median), P75, P90, P95, P99 Resolution Time
- AI Processing Time & Latency
- Assignment Delay
- First Officer Response Time
- Category & Priority SLA compliance breakdowns
"""

import math
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.db.models import Grievance, GrievanceEvent


def format_duration(seconds: float) -> str:
    """Formats duration in seconds into human-readable representation."""
    if seconds is None or seconds < 0:
        return "N/A"
    sec = float(seconds)
    if sec < 60:
        return f"{sec:.1f}s"
    minutes = sec / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.1f}h"
    days = hours / 24
    return f"{days:.1f}d"


def compute_quantiles(data: List[float]) -> Dict[str, Any]:
    """Computes mean, median, P75, P90, P95, P99, min, and max for a list of values."""
    if not data:
        return {
            "count": 0,
            "mean_seconds": 0.0,
            "mean_formatted": "0s",
            "p50_seconds": 0.0,
            "p50_formatted": "0s",
            "p75_seconds": 0.0,
            "p75_formatted": "0s",
            "p90_seconds": 0.0,
            "p90_formatted": "0s",
            "p95_seconds": 0.0,
            "p95_formatted": "0s",
            "p99_seconds": 0.0,
            "p99_formatted": "0s",
            "min_seconds": 0.0,
            "min_formatted": "0s",
            "max_seconds": 0.0,
            "max_formatted": "0s",
        }

    sorted_data = sorted(data)
    n = len(sorted_data)
    mean_val = sum(sorted_data) / n

    def quantile(q: float) -> float:
        k = (n - 1) * q
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        return sorted_data[int(f)] * (c - k) + sorted_data[int(c)] * (k - f)

    p50 = quantile(0.50)
    p75 = quantile(0.75)
    p90 = quantile(0.90)
    p95 = quantile(0.95)
    p99 = quantile(0.99)
    min_val = sorted_data[0]
    max_val = sorted_data[-1]

    return {
        "count": n,
        "mean_seconds": round(mean_val, 2),
        "mean_formatted": format_duration(mean_val),
        "p50_seconds": round(p50, 2),
        "p50_formatted": format_duration(p50),
        "p75_seconds": round(p75, 2),
        "p75_formatted": format_duration(p75),
        "p90_seconds": round(p90, 2),
        "p90_formatted": format_duration(p90),
        "p95_seconds": round(p95, 2),
        "p95_formatted": format_duration(p95),
        "p99_seconds": round(p99, 2),
        "p99_formatted": format_duration(p99),
        "min_seconds": round(min_val, 2),
        "min_formatted": format_duration(min_val),
        "max_seconds": round(max_val, 2),
        "max_formatted": format_duration(max_val),
    }


class GrievanceLifecycleAnalyzer:
    """
    Computes statistical engineering metrics across grievance event timelines.
    """

    def analyze_lifecycle(self, db: Session) -> Dict[str, Any]:
        """
        Extracts lifecycle events from database and generates detailed engineering metrics.
        """
        # Load all grievances with their event streams
        grievances = db.query(Grievance).all()

        ai_processing_times: List[float] = []
        assignment_delays: List[float] = []
        officer_response_times: List[float] = []
        total_resolution_times: List[float] = []

        category_resolution_times: Dict[str, List[float]] = {}
        priority_resolution_times: Dict[str, List[float]] = {}

        total_cases = len(grievances)
        resolved_cases = 0
        sla_compliant_cases = 0
        sla_breached_cases = 0
        active_cases = 0

        for g in grievances:
            is_resolved = (g.status or "").lower() == "resolved"
            if is_resolved:
                resolved_cases += 1
            elif (g.status or "").lower() not in ["withdrawn", "rejected"]:
                active_cases += 1

            if g.sla_breached:
                sla_breached_cases += 1

            # Determine key milestone timestamps
            sub_time = g.created_at
            ai_time = g.processed_at
            assign_time: Optional[datetime] = None
            first_action_time: Optional[datetime] = None
            resolve_time: Optional[datetime] = None

            # Scan events
            events = sorted(g.events, key=lambda e: e.timestamp) if g.events else []
            for ev in events:
                if ev.event_type == "CREATED" and not sub_time:
                    sub_time = ev.timestamp
                elif ev.event_type == "AI_CLASSIFIED" and not ai_time:
                    ai_time = ev.timestamp
                elif ev.event_type in ["ASSIGNED", "REASSIGNED"] and not assign_time:
                    assign_time = ev.timestamp
                elif ev.event_type in ["STATUS_UPDATED"] and not first_action_time:
                    first_action_time = ev.timestamp
                elif ev.event_type == "RESOLUTION_UPLOADED":
                    resolve_time = ev.timestamp

            # 1. Submission -> AI Classification
            if sub_time and ai_time and ai_time >= sub_time:
                ai_dur = (ai_time - sub_time).total_seconds()
                ai_processing_times.append(ai_dur)

            # 2. AI Classification -> Assignment Delay
            if ai_time and assign_time and assign_time >= ai_time:
                assign_dur = (assign_time - ai_time).total_seconds()
                assignment_delays.append(assign_dur)
            elif sub_time and assign_time and assign_time >= sub_time:
                assignment_delays.append((assign_time - sub_time).total_seconds())

            # 3. Assignment -> First Officer Action
            if assign_time and first_action_time and first_action_time >= assign_time:
                officer_response_times.append((first_action_time - assign_time).total_seconds())

            # 4. Total Resolution Time
            if is_resolved:
                end_time = resolve_time or (events[-1].timestamp if events else None)
                if sub_time and end_time and end_time >= sub_time:
                    res_dur = (end_time - sub_time).total_seconds()
                    total_resolution_times.append(res_dur)

                    cat = g.category or "Other"
                    category_resolution_times.setdefault(cat, []).append(res_dur)

                    prio = (g.priority or "Medium").upper()
                    priority_resolution_times.setdefault(prio, []).append(res_dur)

                    # Check SLA compliance
                    if g.sla_deadline:
                        if end_time <= g.sla_deadline:
                            sla_compliant_cases += 1
                    else:
                        sla_compliant_cases += 1

        sla_compliance_rate_pct = (
            round((sla_compliant_cases / resolved_cases) * 100, 2)
            if resolved_cases > 0
            else 100.0
        )

        category_breakdown = {
            cat: compute_quantiles(times) for cat, times in sorted(category_resolution_times.items())
        }
        priority_breakdown = {
            prio: compute_quantiles(times) for prio, times in sorted(priority_resolution_times.items())
        }

        return {
            "summary": {
                "total_grievances": total_cases,
                "resolved_count": resolved_cases,
                "active_count": active_cases,
                "sla_breached_count": sla_breached_cases,
                "sla_compliance_rate_pct": sla_compliance_rate_pct,
            },
            "lifecycle_stages": {
                "ai_processing_time": compute_quantiles(ai_processing_times),
                "assignment_delay": compute_quantiles(assignment_delays),
                "officer_first_action": compute_quantiles(officer_response_times),
                "total_resolution_time": compute_quantiles(total_resolution_times),
            },
            "by_category": category_breakdown,
            "by_priority": priority_breakdown,
        }


lifecycle_analyzer = GrievanceLifecycleAnalyzer()
