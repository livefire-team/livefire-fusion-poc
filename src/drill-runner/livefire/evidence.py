"""The evidence package: one sealed JSON summary per drill, next to its events.jsonl."""
import hashlib
import json

from .contracts import DebtItem, EvidencePackage, Scorecard, Verdict
from .events import BlobEventStore, DirEventStore, parse_ts

FINAL_LABELS = ("after-fix", "after-refault", "after-restore")
NEXT_DRILL = {  # guide Phase 6, step 4: chosen by outcome, never by a model
    "verified_1": "Repeat with the durability check and a dependency blackout (Chaos Studio, roadmap).",
    "verified_2": "Repeat the same scenario to confirm the fix holds after merge.",
    Verdict.ESCALATED_BUDGET.value: "Rerun with the same fault after human remediation.",
    Verdict.ESCALATED_EVIDENCE.value: "Improve telemetry for the missing evidence source, then rerun.",
}


def _put(store, drill_id: str, name: str, data: bytes) -> None:
    """Writes once. In Blob, version-level immutability keeps it; overwrite=False refuses a second write."""
    if isinstance(store, DirEventStore):
        path = store.root / drill_id / name
        if path.exists():
            raise FileExistsError(path)
        path.write_bytes(data)
    elif isinstance(store, BlobEventStore):
        store.container.get_blob_client(f"{drill_id}/{name}").upload_blob(data, overwrite=False)
    else:
        raise TypeError("unknown event store")


def _first(events, *actions, result=None):
    for e in events:
        if e["action"] in actions and (result is None or str(e.get("result")) == result):
            return e["ts"]
    return ""


def _seconds(start: str, end: str) -> float | None:
    return round((parse_ts(end) - parse_ts(start)).total_seconds(), 1) if start and end else None


def _index(events: list[dict], test, start: int = 0) -> int | None:
    """Index of the first event from `start` on that passes `test`. Windows use the log's order, not timestamps:
    the log is append-only, so its order is the order things happened, even within one millisecond."""
    return next((i for i in range(start, len(events)) if test(events[i])), None)


def _rows(events: list[dict], lo: int, hi: int) -> list[dict]:
    return [e.get("details") or {} for e in events[lo:hi] if e["action"] == "metrics.orders"]


def scorecard(run, s, events: list[dict]) -> Scorecard:
    """Blueprint 1.6, from the event log alone (guide Phase 6, step 3)."""
    finals = {f"referee.{x}" for x in FINAL_LABELS}
    i_fault = _index(events, lambda e: e["action"] == "fault.inject")
    i_pass = _index(events, lambda e: e["action"] in finals and e.get("result") == "PASS",
                    i_fault + 1) if i_fault is not None else None
    i_restore = _index(events, lambda e: e["action"] == "fault.restore",
                       i_fault + 1) if i_fault is not None else None
    i_health = _index(events, lambda e: e["action"] == "wait.ok", i_restore) if i_restore is not None else None
    i_verdict = _index(events, lambda e: e["action"] == "verdict")
    false_green = any(e["action"] == "referee.after-restore" and e.get("result") == "FAIL" for e in events)
    ts = lambda i: events[i]["ts"] if i is not None else ""     # noqa: E731
    fault, recovered, health = ts(i_fault), ts(i_pass), ts(i_health)
    # failed orders and backlog: from the fault to the verified recovery (the durability re-fault is a test step,
    # not customer exposure), or to the verdict if it never recovered
    end = i_pass if i_pass is not None else (i_verdict if i_verdict is not None else len(events))
    during = _rows(events, i_fault, end + 1) if i_fault is not None else []
    before = []                                     # the 5 minutes before the fault
    if i_fault is not None:
        t0 = parse_ts(fault).timestamp()
        before = [r for i, r in enumerate(events[:i_fault]) if r["action"] == "metrics.orders"
                  and parse_ts(r["ts"]).timestamp() >= t0 - 300]
        before = [r.get("details") or {} for r in before]
    after = _rows(events, i_verdict + 1, len(events)) if i_verdict is not None else []

    def mean(rows, key):
        values = [float(r[key]) for r in rows if isinstance(r.get(key), (int, float))]
        return round(sum(values) / len(values), 2) if values else None

    failed_orders = None
    totals = [r["failed_total"] for r in during if isinstance(r.get("failed_total"), int)]
    if len(totals) >= 2:
        failed_orders = totals[-1] - totals[0]
    backlogs = [r["backlog"] for r in during if isinstance(r.get("backlog"), int)]
    report = s.reports[-1] if s.reports else None
    improvements = list(report.changed_paths) if report else []
    if s.terminal is not None:
        improvements.append("package.json#operational_debt")
    browser_s = sum(float((e.get("details") or {}).get("duration_s") or 0) for e in events
                    if e["action"].startswith("referee."))
    ended = next((e["ts"] for e in reversed(events) if e["action"] in ("drill.end", "verdict")), "")
    started = next((e["ts"] for e in events if e["action"] == "drill.start"), "")
    twin_s = _seconds(started, ended) or 0.0
    return Scorecard(
        target_recovery_s=run.cfg.target_recovery_s,
        verified_recovery_s=_seconds(fault, recovered) if fault and recovered else None,
        false_green_s=_seconds(health, recovered) if false_green and health and recovered else None,
        failed_orders=failed_orders,
        peak_backlog=max(backlogs) if backlogs else None,
        orders_per_min_before=mean(before, "orders_per_min"),
        orders_per_min_after=mean(after, "orders_per_min"),
        decision_latency_s=round(sum(float((e.get("details") or {}).get("latency_s") or 0) for e in events
                                     if e["action"] == "approval.decided"), 1),
        policy_denials=sum(e["action"] == "recover.broad" and e.get("result") == "denied" for e in events),
        durable_improvements=improvements,
        cost={"tokens": float(run.tokens), "est_cost_usd": round(run.cost, 4),
              "tool_calls": float(sum(e["action"].endswith(".tool_call") for e in events)),
              "browser_min": round(browser_s / 60, 2), "twin_min": round(twin_s / 60, 2)},
    )


def operational_debt(run, s, events: list[dict], pr_url: str = "") -> list[DebtItem]:
    """Blueprint 2.2, composed by the workflow from the brief, the change report and the results (Phase 6, step 4)."""
    brief, report = s.brief, (s.reports[-1] if s.reports else None)
    verified = s.terminal == Verdict.VERIFIED
    items = []
    if brief and report:
        refs = [e.ref for e in brief.evidence_references][:8] or ["brief"]
        source = next((p for p in report.changed_paths if p not in (report.regression_test_path, report.runbook_path)),
                      report.changed_paths[0])
        items.append(DebtItem(kind="application-resilience",
                              finding=f"{brief.supported_hypothesis} Required: {brief.required_behavior}"[:400],
                              evidence_refs=refs, artifact=f"{source}@{report.branch}"[:300],
                              residual_risk="; ".join(brief.residual_risks)[:400],
                              status="candidate" if verified else "unresolved"))
        ci_passed = any(e["action"] == "ci.result" and e.get("result") == "pass"
                        and (e.get("details") or {}).get("branch") == report.branch for e in events)
        if report.regression_test_path:
            items.append(DebtItem(kind="regression-coverage",
                                  finding="; ".join(brief.acceptance_criteria)[:400] or "regression test",
                                  evidence_refs=refs, artifact=f"{report.regression_test_path}@{report.branch}"[:300],
                                  residual_risk="", status="candidate" if ci_passed else "unresolved"))
        if report.runbook_path:
            runbook_refs = [e.ref for e in brief.evidence_references if e.source in ("runbook", "incident")]
            items.append(DebtItem(kind="runbook", finding="Runbook update for the step the evidence showed missing",
                                  evidence_refs=(runbook_refs or refs)[:8],
                                  artifact=(pr_url or f"{report.runbook_path}@{report.branch}")[:300],
                                  residual_risk="", status="proposed"))
    risks = list(brief.residual_risks) if brief else []
    items.append(DebtItem(kind="knowledge",
                          finding=f"{s.terminal.value if s.terminal else 'no verdict'} after {s.attempt} candidate "
                                  f"attempt(s): {s.reason}"[:400],
                          evidence_refs=[f"{run.cfg.drill_id}/events.jsonl"], artifact="package.json",
                          residual_risk="; ".join(risks)[:400], status="recorded"))
    return items


def next_drill(s) -> str:
    if s.terminal == Verdict.VERIFIED:
        return NEXT_DRILL["verified_2" if s.attempt >= 2 else "verified_1"]
    return NEXT_DRILL.get(s.terminal.value if s.terminal else "", "Rerun the scenario once the cause is fixed.")


def build(run, s) -> tuple[EvidencePackage, list[dict]]:
    events = run.log.read()
    raw = "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events).encode()
    report = s.reports[-1] if s.reports else None
    card = scorecard(run, s, events)
    residual = list(s.brief.residual_risks) if s.brief else []
    if not any(e["action"] == "metrics.orders" for e in events):
        residual.append("No metrics.orders lines in this drill: throughput, backlog and failed orders are not measured "
                        "(WS1's per-drill load generator).")
    package = EvidencePackage(
        drill_id=run.cfg.drill_id,
        scenario=run.cfg.scenario,
        terminal_state=s.terminal,
        reason=s.reason,
        verdict_inputs=s.verdict_inputs,
        policy=run.cfg.policy,
        agents=run.meta.get("agents", {}),
        prompt_sha256=run.meta.get("prompt_sha256", {}),
        model_deployment=run.meta.get("model_deployment", ""),
        base_ref=run.cfg.base_ref,
        candidate={"branch": report.branch if report else "", "commit": s.commit, "image": s.image,
                   "image_digest": next((str((e.get("details") or {}).get("digest", "")) for e in reversed(events)
                                         if e["action"] == "deploy.revision" and e.get("result") == "ok"), ""),
                   "checks": next(((e.get("details") or {}).get("checks", {}) for e in reversed(events)
                                   if e["action"] == "ci.result"), {}),
                   "ci_run": s.ci_url, "attempts": s.attempt,
                   "change_report": report.model_dump() if report else None},
        options=s.options.model_dump() if s.options else None,
        brief=s.brief.model_dump() if s.brief else None,
        counts={
            "events": len(events),
            "tool_calls": sum(e["action"].endswith(".tool_call") for e in events),
            "denied_tool_calls": sum(e["action"].endswith(".tool_call") and e.get("result") == "deny" for e in events),
            "policy_denials": sum(e["action"] == "recover.broad" and e.get("result") == "denied" for e in events),
            "referee_runs": sum(e["action"].startswith("referee.") for e in events),
            "human_decisions": sum(e["action"] == "approval.decided" for e in events),
            "candidate_attempts": s.attempt,
        },
        usage={"tokens": run.tokens, "est_cost_usd": round(run.cost, 4)},
        timeline={"started": _first(events, "drill.start"), "fault": _first(events, "fault.inject"),
                  "false_green": _first(events, "referee.after-restore", result="FAIL"),
                  "verdict": _first(events, "verdict"), "sealed_from_events_through": events[-1]["ts"] if events else ""},
        events_sha256=hashlib.sha256(raw).hexdigest(),
        events_count=len(events),
        residual_risks=residual,
        scorecard=card,
        operational_debt=operational_debt(run, s, events),
        next_drill_recommendation=next_drill(s),
    )
    return package, events


def seal(run, s) -> str:
    package, _ = build(run, s)
    data = json.dumps(package.model_dump(mode="json"), indent=2).encode()
    _put(run.log.store, run.cfg.drill_id, "package.json", data)
    digest = hashlib.sha256(data).hexdigest()
    card, debt = package.scorecard, package.operational_debt
    kinds = {}
    for item in debt:
        kinds[item.kind] = kinds.get(item.kind, 0) + 1
    run.log.write("package.ready", "ok", {"path": f"{run.cfg.drill_id}/package.json", "sha256": digest,
                                          "events_sha256": package.events_sha256,
                                          "verified_recovery_s": card.verified_recovery_s if card else None,
                                          "target_recovery_s": run.cfg.target_recovery_s,
                                          "operational_debt": kinds,
                                          "next_drill_recommendation": package.next_drill_recommendation})
    return digest


def pull_request_body(run, s) -> str:
    report, brief = s.reports[-1], s.brief
    rows = "\n".join(f"| {m.change} | {m.evidence_ref} | {m.acceptance_criterion} |" for m in report.evidence_to_change)
    inputs = s.verdict_inputs.model_dump() if s.verdict_inputs else {}
    checks = "\n".join(f"- {'PASS' if v else 'FAIL'}: {k}" for k, v in inputs.items() if isinstance(v, bool))
    debt = "\n".join(f"- {d.kind} ({d.status}): {d.artifact}" for d in operational_debt(run, s, run.log.read()))
    return (
        f"Candidate from LiveFire drill `{run.cfg.drill_id}` (attempt {s.attempt}), produced by the Engineer agent "
        f"and verified by the deterministic workflow. **Not merged by any agent: a person reviews and decides.**\n\n"
        f"**Verdict:** {s.terminal.value}\n\n{checks}\n\n"
        f"**Required behavior (from the Planner's brief):** {brief.required_behavior}\n\n"
        f"| Change | Evidence | Acceptance criterion |\n| --- | --- | --- |\n{rows}\n\n"
        f"**Residual risks:** {'; '.join(brief.residual_risks) or 'none recorded'}\n\n"
        f"**Operational debt:**\n{debt}\n\n"
        f"Evidence package: `{run.cfg.drill_id}/package.json` (sha256 `{s.package_sha256[:16]}…`). "
        f"CI run: {s.ci_url}\n"
    )
