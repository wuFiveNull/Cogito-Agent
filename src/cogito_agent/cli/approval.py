from __future__ import annotations

import json
from typing import Any

from cogito_agent.skill import SkillRunner
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import ApprovalRepository
from cogito_agent.shared.redaction import RedactionHelper


def _run_approval_list(args: Any) -> None:
    """List approvals. Supports --status filter."""
    db = Database(args.db_path)
    db.initialize()
    db.migrate()
    redactor = RedactionHelper()
    repo = ApprovalRepository(db)
    status = getattr(args, "status", "pending")
    workspace_id = getattr(args, "workspace_id", "*")

    ws = workspace_id if workspace_id != "*" else ""
    approvals = repo.list_by_filters(ws, status=status)

    if not approvals:
        print(f"  No {status} approvals found.")
    else:
        print(f"  Approvals ({len(approvals)}):")
        for a in approvals:
            aid = str(a.get("id", ""))[:8]
            cap = redactor.redact(str(a.get("capability_name", "")))
            st = str(a.get("status", ""))
            ws = str(a.get("workspace_id", ""))[:8]
            created = str(a.get("created_at", ""))[:19]
            print(f"    {aid}  [{st}]  {cap}  ws={ws}  {created}")
    db.close()


def _run_approval_show(args: Any) -> None:
    """Show approval details."""
    db = Database(args.db_path)
    db.initialize()
    db.migrate()
    redactor = RedactionHelper()
    repo = ApprovalRepository(db)
    approval = repo.get_by_id(args.approval_id)
    if approval is None:
        print(f"  Approval '{args.approval_id}' not found.")
        db.close()
        return

    print(f"  ID:           {approval.get('id', '')}")
    print(f"  Status:       {approval.get('status', '')}")
    print(f"  Workspace:    {approval.get('workspace_id', '')}")
    cap = redactor.redact(str(approval.get("capability_name", "")))
    print(f"  Capability:   {cap}")
    print(f"  Operation:    {approval.get('operation', '')}")
    print(f"  Resource:     {approval.get('resource', '')}")
    print(f"  Reason:       {redactor.redact(str(approval.get('reason', '')))}")
    print(f"  Actor:        {approval.get('actor_id', '')}")
    print(f"  Decision:     {approval.get('decision', '')}")
    print(f"  Decided By:   {approval.get('decided_by', '')}")
    print(f"  Created:      {str(approval.get('created_at', ''))[:19]}")
    decided_at = approval.get("decided_at")
    if decided_at:
        print(f"  Decided At:   {str(decided_at)[:19]}")
    db.close()


def _run_approval_approve(args: Any) -> None:
    """Approve a pending approval."""
    db = Database(args.db_path)
    db.initialize()
    db.migrate()
    repo = ApprovalRepository(db)
    approval = repo.get_by_id(args.approval_id)
    if approval is None:
        print(f"  Approval '{args.approval_id}' not found.")
        db.close()
        return

    if approval.get("status") != "pending":
        print(f"  Approval is already {approval.get('status')}. Use --force to override.")
        db.close()
        return

    from cogito_agent.application.audit import log_audit
    result = repo.resolve(args.approval_id, "approved", "cli")
    if result:
        print(f"  Approved: {args.approval_id}")
        log_audit(
            db, "cli", "approval.approve", f"approval:{args.approval_id}",
            str(approval.get("workspace_id", "")),
            decision="allow", reason="user approved via CLI",
        )
        found = _notify_matching_runs(db, args.approval_id, "approved")
        if not found:
            print("  Approved. Run `cogito approval resume <skill_run_id>` to continue.")
    else:
        print(f"  Failed to approve '{args.approval_id}'.")
    db.close()


def _notify_matching_runs(db: Database, approval_id: str, verb: str) -> bool:
    """Notify user about skill runs matching the given approval_id. Returns True if a match was found."""
    from cogito_agent.skill import SkillRunner

    runner = SkillRunner(db)
    pending = runner.find_pending_approval_runs()
    found = False
    for row in pending:
        run_id = str(row["id"])
        log = runner.get_skill_run_log(run_id)
        if log and log.get("resume_data_json"):
            try:
                sl_data = json.loads(str(log.get("step_logs_json", "{}")))
                for step_log in sl_data.get("step_logs", []):
                    if step_log.get("output") == approval_id:
                        print(f"  Next: Run `cogito approval resume {run_id}` to {verb}.")
                        found = True
                        break
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        if found:
            break
    return found


def _run_approval_reject(args: Any) -> None:
    """Reject a pending approval."""
    db = Database(args.db_path)
    db.initialize()
    db.migrate()
    repo = ApprovalRepository(db)
    approval = repo.get_by_id(args.approval_id)
    if approval is None:
        print(f"  Approval '{args.approval_id}' not found.")
        db.close()
        return

    if approval.get("status") != "pending":
        print(f"  Approval is already {approval.get('status')}. Use --force to override.")
        db.close()
        return

    from cogito_agent.application.audit import log_audit
    result = repo.resolve(args.approval_id, "rejected", "cli")
    if result:
        print(f"  Rejected: {args.approval_id}")
        log_audit(
            db, "cli", "approval.reject", f"approval:{args.approval_id}",
            str(approval.get("workspace_id", "")),
            decision="deny", reason="user rejected via CLI",
        )
        found2 = _notify_matching_runs(db, args.approval_id, "finalize rejection")
        if not found2:
            print("  Rejected. Run `cogito approval resume <skill_run_id>` to finalize.")
    else:
        print(f"  Failed to reject '{args.approval_id}'.")
    db.close()


def _run_approval_resume(args: Any) -> None:
    """Resume a pending skill run after approval decision."""
    db = Database(args.db_path)
    db.initialize()
    db.migrate()

    from cogito_agent.skill import SkillRunner
    runner = SkillRunner(db)
    log = runner.get_skill_run_log(args.skill_run_id)
    if log is None:
        print(f"  Skill run '{args.skill_run_id}' not found.")
        db.close()
        return

    if log["status"] != "pending_approval":
        print(f"  Skill run is '{log['status']}', not pending_approval. Cannot resume.")
        db.close()
        return

    if not log.get("resume_data_json"):
        print(f"  Skill run '{args.skill_run_id}' has no resume data.")
        db.close()
        return

    try:
        step_logs = json.loads(str(log.get("step_logs_json", "{}")))
        approval_id = ""
        for step_log in step_logs.get("step_logs", []):
            if step_log.get("status") == "pending_approval":
                output = str(step_log.get("output", ""))
                if output:
                    approval_id = output
                    break

        if not approval_id:
            print(f"  Could not find approval ID for skill run '{args.skill_run_id}'.")
            db.close()
            return

        repo = ApprovalRepository(db)
        approval = repo.get_by_id(approval_id)
        if approval is None:
            print(f"  Approval '{approval_id}' not found.")
            db.close()
            return

        runner = SkillRunner(db)
        result = runner.resume(args.skill_run_id, approval_id)
        if result is None:
            print(f"  Failed to resume skill run '{args.skill_run_id}'.")
            db.close()
            return

        print(f"  Skill run resumed with status: {result.status}")
        print(f"  Steps executed: {len(result.step_logs)}")
        for sl in result.step_logs:
            sid = sl.get("step_id", "")
            st = sl.get("status", "")
            print(f"    - {sid}: {st}")

        from cogito_agent.application.audit import log_audit
        log_audit(
            db, "cli", "approval.resume", f"skill_run:{args.skill_run_id}",
            str(approval.get("workspace_id", "")),
            decision="allow" if result.status == "completed" else "deny",
            reason=f"skill run resumed with status {result.status}",
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"  Error reading resume data: {e}")

    db.close()
