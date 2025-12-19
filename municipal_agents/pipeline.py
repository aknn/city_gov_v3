# -*- coding: utf-8 -*-
"""
Municipal HITL Pipeline Orchestrator

Three-stage pipeline with HUMAN APPROVAL GATEWAY between stages 2 and 3.

Flow:
1. Formation Agent → Creates project candidates
2. Governance Agent → Makes decisions (some require human approval)
   ↓
   [APPROVAL GATEWAY] ← Human reviews pending decisions
   ↓
3. Scheduling Agent → Schedules approved projects
"""

import asyncio
from typing import Optional

from agents import Runner, trace

from .context import MunicipalContext
from .database import init_database, seed_sample_data, clear_agent_outputs
from .formation_agent import create_formation_agent
from .governance_agent import create_governance_agent
from .scheduling_agent import create_scheduling_agent


async def run_formation_stage(
    context: MunicipalContext,
    verbose: bool = True
) -> dict:
    """
    Stage 1: Project Formation
    
    Converts open issues into structured project candidates.
    """
    if verbose:
        print("\n" + "=" * 60)
        print("STAGE 1: PROJECT FORMATION")
        print("=" * 60)
    
    agent = create_formation_agent(context)
    
    prompt = """Process all open citizen issues:

1. Get the list of open issues
2. For each issue with risk score >= 3:
   - Assess the risk
   - Create a project candidate with a clear scope description
3. Show the formation summary when done

Create projects for ALL high-risk issues."""
    
    with trace("Formation Stage"):
        result = await Runner.run(agent, prompt, context=context)
    
    if verbose:
        print(f"\nFormation Agent Output:\n{result.final_output}")
    
    candidates = context.get_project_candidates()
    
    return {
        "stage": "FORMATION",
        "candidates_formed": len(candidates),
        "total_cost": sum(c['estimated_cost'] for c in candidates),
        "output": result.final_output
    }


async def run_governance_stage(
    context: MunicipalContext,
    verbose: bool = True
) -> dict:
    """
    Stage 2: Governance / Policy Decisions
    
    Agent evaluates each project and makes APPROVE/REJECT decisions.
    Some decisions require human approval before proceeding.
    """
    if verbose:
        print("\n" + "=" * 60)
        print("STAGE 2: GOVERNANCE (POLICY DECISIONS)")
        print("=" * 60)
    
    agent = create_governance_agent(context)
    
    prompt = """Review all project candidates and make funding decisions.

1. Check the budget status
2. Get all project candidates
3. For EACH project, evaluate and decide:
   - APPROVE or REJECT (you must choose)
   - Set your confidence (0-100)
   - Provide reason codes and rationale
4. Show the governance summary when done

The system will determine which decisions need human approval.
Evaluate ALL projects."""
    
    with trace("Governance Stage"):
        result = await Runner.run(agent, prompt, context=context)
    
    if verbose:
        print(f"\nGovernance Agent Output:\n{result.final_output}")
    
    # Get decision statistics
    decisions = context.get_all_decisions()
    pending = [d for d in decisions if d['authorization'] == 'HUMAN_REQUIRED' and not d['final_decision']]
    auto_approved = [d for d in decisions if d['authorization'] == 'AUTO' and d['decision'] == 'APPROVE']
    auto_rejected = [d for d in decisions if d['authorization'] == 'AUTO' and d['decision'] == 'REJECT']
    
    return {
        "stage": "GOVERNANCE",
        "total_decisions": len(decisions),
        "auto_approved": len(auto_approved),
        "auto_rejected": len(auto_rejected),
        "pending_human_approval": len(pending),
        "pending_decisions": pending,
        "requires_approval": len(pending) > 0,
        "output": result.final_output
    }


def get_pending_approvals(context: MunicipalContext) -> dict:
    """
    Get all decisions awaiting human approval.
    
    This is called by the API to show the approval UI.
    """
    pending = context.get_pending_decisions()
    decisions = context.get_all_decisions()
    
    auto_approved = [d for d in decisions if d['authorization'] == 'AUTO' and d['decision'] == 'APPROVE']
    auto_rejected = [d for d in decisions if d['authorization'] == 'AUTO' and d['decision'] == 'REJECT']
    
    budget = context.get_budget_status()
    
    return {
        "pending": pending,
        "auto_approved": auto_approved,
        "auto_rejected": auto_rejected,
        "budget": budget,
        "requires_approval": len(pending) > 0
    }


def submit_human_decisions(
    context: MunicipalContext,
    decisions: list[dict]
) -> dict:
    """
    Submit human decisions for pending approvals.
    
    Args:
        decisions: List of {project_id, decision, reason}
    
    Returns:
        Summary of submitted decisions
    """
    approved = 0
    rejected = 0
    
    for d in decisions:
        project_id = d['project_id']
        human_decision = d['decision']  # "APPROVE" or "REJECT"
        reason = d.get('reason', 'Human override')
        
        context.update_decision_with_human_input(project_id, human_decision, reason)
        
        if human_decision == "APPROVE":
            approved += 1
        else:
            rejected += 1
        
        # Log audit
        context.log_audit(
            event_type="HUMAN_DECISION",
            agent_name="human",
            payload={
                "project_id": project_id,
                "decision": human_decision,
                "reason": reason
            }
        )
    
    # Finalize any remaining AUTO decisions
    context.finalize_auto_decisions()
    
    return {
        "submitted": len(decisions),
        "approved": approved,
        "rejected": rejected
    }


async def run_scheduling_stage(
    context: MunicipalContext,
    verbose: bool = True
) -> dict:
    """
    Stage 3: Scheduling
    
    Schedules all approved projects within resource constraints.
    """
    if verbose:
        print("\n" + "=" * 60)
        print("STAGE 3: SCHEDULING")
        print("=" * 60)
    
    agent = create_scheduling_agent(context)
    
    prompt = """Schedule all approved projects for the quarter.

1. Get the list of approved projects
2. Check resource status
3. For EACH project (highest risk first), schedule it
4. Show the final schedule summary

Schedule ALL approved projects."""
    
    with trace("Scheduling Stage"):
        result = await Runner.run(agent, prompt, context=context)
    
    if verbose:
        print(f"\nScheduling Agent Output:\n{result.final_output}")
    
    tasks = context.get_schedule_tasks()
    scheduled = [t for t in tasks if t['status'] == 'SCHEDULED']
    blocked = [t for t in tasks if t['status'] == 'BLOCKED']
    
    return {
        "stage": "SCHEDULING",
        "total_tasks": len(tasks),
        "scheduled": len(scheduled),
        "blocked": len(blocked),
        "output": result.final_output
    }


async def run_full_pipeline(
    budget: float = 75_000_000,
    auto_approve: bool = False,
    verbose: bool = True
) -> dict:
    """
    Run the complete pipeline.
    
    If auto_approve=False (default), stops after governance for human review.
    If auto_approve=True, auto-approves all pending decisions.
    """
    # Initialize
    init_database()
    seed_sample_data()
    clear_agent_outputs()
    
    context = MunicipalContext(quarterly_budget=budget)
    
    # Stage 1: Formation
    formation_result = await run_formation_stage(context, verbose)
    
    # Stage 2: Governance
    governance_result = await run_governance_stage(context, verbose)
    
    # Check if human approval needed
    if governance_result['requires_approval'] and not auto_approve:
        return {
            "status": "AWAITING_APPROVAL",
            "formation": formation_result,
            "governance": governance_result,
            "message": f"{governance_result['pending_human_approval']} decisions require human approval"
        }
    
    # Auto-approve if requested
    if auto_approve and governance_result['pending_human_approval'] > 0:
        pending = governance_result['pending_decisions']
        auto_decisions = [
            {"project_id": d['project_id'], "decision": d['decision'], "reason": "Auto-approved"}
            for d in pending
        ]
        submit_human_decisions(context, auto_decisions)
    
    # Stage 3: Scheduling
    scheduling_result = await run_scheduling_stage(context, verbose)
    
    return {
        "status": "COMPLETE",
        "formation": formation_result,
        "governance": governance_result,
        "scheduling": scheduling_result
    }


async def continue_after_approval(
    context: MunicipalContext,
    verbose: bool = True
) -> dict:
    """
    Continue pipeline after human approvals are submitted.
    """
    # Run scheduling stage
    scheduling_result = await run_scheduling_stage(context, verbose)
    
    return {
        "status": "COMPLETE",
        "scheduling": scheduling_result
    }


# ============ CLI Entry Point ============

if __name__ == "__main__":
    import sys
    
    auto_approve = "--auto" in sys.argv
    budget = 75_000_000
    
    for arg in sys.argv:
        if arg.startswith("--budget="):
            budget = float(arg.split("=")[1])
    
    result = asyncio.run(run_full_pipeline(budget=budget, auto_approve=auto_approve))
    
    print("\n" + "=" * 60)
    print("PIPELINE RESULT")
    print("=" * 60)
    print(f"Status: {result['status']}")
    
    if result['status'] == "AWAITING_APPROVAL":
        print(f"\n⏳ {result['message']}")
        print("\nRun with --auto to auto-approve, or use the web UI for manual review.")
