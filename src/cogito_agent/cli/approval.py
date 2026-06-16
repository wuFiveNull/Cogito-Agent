from __future__ import annotations

import json
from typing import Any

from cogito_agent.governance import AuditLogger
from cogito_agent.skill import SkillRunner
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import ApprovalRepository
from cogito_agent.trace import RedactionHelper


def _run_approval_list(args: Any) -> None:
    """List approvals. Supports --status filter."""
    db = Database(args.db_path)
    db.initialize()
    db.migrate()
    redactor = RedactionHelper()
    repo = ApprovalRepository(db)
    status = getattr(args, "status", "pending")
    workspace_id = getattr(args, "workspace_id", "*")

    if status == "all":
        if workspace_id == "*":
            approvals = repo.list_by_workspace("*")
        else:
            approvals = repo.list_by_workspace(workspace_id)
    elif status == "pending":
        if workspace_id == "*":
            approvals = repo.list_pending("*")
        else:
            approvals = repo.list_pending(workspace_id)
    else:
        if workspace_id == "*":
            cur = db.connection.execute(
                "SELECT * FROM approval_records WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        else:
            sql = (
                "SELECT * FROM approval_records"
                " WHERE workspace_id = ? AND status = ?"
                " ORDER BY created_at DESC"
            )
            cur = db.connection.execute(sql, (workspace_id, status))
        approvals = [dict(r) for r in cur.fetchall()]

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

    audit = AuditLogger(db)
    result = repo.resolve(args.approval_id, "approved", "cli")
    if result:
        print(f"  Approved: {args.approval_id}")
        audit.log(
            actor_id="cli",
            action="approval.approve",
            resource=f"approval:{args.approval_id}",
            workspace_id=str(approval.get("workspace_id", "")),
            decision="allow",
            reason="user approved via CLI",
        )
        cur = db.connection.execute(
            "SELECT id FROM skill_run_logs"
            " WHERE resume_data_json IS NOT NULL AND status = 'pending_approval'"
            " ORDER BY created_at DESC LIMIT 20"
        )
        found = False
        for row in cur.fetchall():
            run_id = str(row["id"])
            run_cur = db.connection.execute(
                "SELECT resume_data_json FROM skill_run_logs WHERE id = ?", (run_id,)
            )
            run_row = run_cur.fetchone()
            if run_row and run_row["resume_data_json"]:
                try:
                    step_logs_cur = db.connection.execute(
                        "SELECT step_logs_json FROM skill_run_logs WHERE id = ?", (run_id,)
                    )
                    sl_row = step_logs_cur.fetchone()
                    if sl_row:
                        sl_data = json.loads(str(sl_row["step_logs_json"]))
                        for step_log in sl_data.get("step_logs", []):
                            if step_log.get("output") == args.approval_id:
                                print(f"  Next: Run `cogito approval resume {run_id}` to continue.")
                                found = True
                                break
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
            if found:
                break

        if not found:
            print("  Approved. Run `cogito approval resume <skill_run_id>` to continue.")
    else:
        print(f"  Failed to approve '{args.approval_id}'.")
    db.close()


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

    audit = AuditLogger(db)
    result = repo.resolve(args.approval_id, "rejected", "cli")
    if result:
        print(f"  Rejected: {args.approval_id}")
        audit.log(
            actor_id="cli",
            action="approval.reject",
            resource=f"approval:{args.approval_id}",
            workspace_id=str(approval.get("workspace_id", "")),
            decision="deny",
            reason="user rejected via CLI",
        )
        cur = db.connection.execute(
            "SELECT id FROM skill_run_logs"
            " WHERE resume_data_json IS NOT NULL AND status = 'pending_approval'"
            " ORDER BY created_at DESC LIMIT 20"
        )
        found = False
        for row in cur.fetchall():
            run_id = str(row["id"])
            step_logs_cur = db.connection.execute(
                "SELECT step_logs_json FROM skill_run_logs WHERE id = ?", (run_id,)
            )
            sl_row = step_logs_cur.fetchone()
            if sl_row:
                try:
                    sl_data = json.loads(str(sl_row["step_logs_json"]))
                    for step_log in sl_data.get("step_logs", []):
                        if step_log.get("output") == args.approval_id:
                            print(
                                f"  Next: Run `cogito approval resume {run_id}`"
                                " to finalize rejection."
                            )
                            found = True
                            break
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
            if found:
                break

        if not found:
            print("  Rejected. Run `cogito approval resume <skill_run_id>` to finalize.")
    else:
        print(f"  Failed to reject '{args.approval_id}'.")
    db.close()


def _run_approval_resume(args: Any) -> None:
    """Resume a pending skill run after approval decision."""
    db = Database(args.db_path)
    db.initialize()
    db.migrate()

    cur = db.connection.execute(
        "SELECT resume_data_json, step_logs_json, status FROM skill_run_logs WHERE id = ?",
        (args.skill_run_id,),
    )
    row = cur.fetchone()
    if row is None:
        print(f"  Skill run '{args.skill_run_id}' not found.")
        db.close()
        return

    if row["status"] != "pending_approval":
        print(f"  Skill run is '{row['status']}', not pending_approval. Cannot resume.")
        db.close()
        return

    if not row["resume_data_json"]:
        print(f"  Skill run '{args.skill_run_id}' has no resume data.")
        db.close()
        return

    try:
        step_logs = json.loads(str(row["step_logs_json"]))
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

        audit = AuditLogger(db)
        audit.log(
            actor_id="cli",
            action="approval.resume",
            resource=f"skill_run:{args.skill_run_id}",
            workspace_id=str(approval.get("workspace_id", "")),
            decision="allow" if result.status == "completed" else "deny",
            reason=f"skill run resumed with status {result.status}",
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"  Error reading resume data: {e}")

    db.close()
