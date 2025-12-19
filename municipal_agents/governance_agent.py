# -*- coding: utf-8 -*-
"""
Agent 2: Governance Agent (AGENTIC with HITL)

THIS IS THE KEY AGENT that makes the system agentic.

The agent DECIDES (APPROVE/REJECT) for each project, then determines
if it has AUTHORITY to execute (AUTO) or needs HUMAN approval (HUMAN_REQUIRED).

Policy rules are embedded in the system prompt.
RAG-assisted briefings are generated for escalated decisions.
"""

from agents import Agent, function_tool, RunContextWrapper
from .context import MunicipalContext
from .models import PolicyDecision, ReasonCode
from .rag_service import get_rag_service
from .briefing_service import generate_briefing, format_briefing_for_display
import json


# ============ Policy Constants ============

COST_THRESHOLD = 10_000_000  # $10M - above this requires human approval
CONFIDENCE_THRESHOLD = 65   # Below this requires human approval
HIGH_RISK_THRESHOLD = 6     # Risk score >= 6 is high risk
HIGH_POPULATION_THRESHOLD = 200_000  # Affects > 200K people


# ============ Agent Tools ============

@function_tool
def get_project_candidates(ctx: RunContextWrapper["MunicipalContext"]) -> str:
    """
    Get all project candidates awaiting governance decisions.
    
    Returns project details needed for decision-making.
    """
    candidates = ctx.context.get_project_candidates()
    budget = ctx.context.get_budget_status()
    
    if not candidates:
        return "No project candidates found. Run Formation Agent first."
    
    result = f"""
GOVERNANCE REVIEW QUEUE
=======================
Quarterly Budget: ${budget['total']:,.0f}
Already Allocated: ${budget['allocated']:,.0f}
Remaining: ${budget['remaining']:,.0f}

{len(candidates)} Projects Awaiting Decision:
"""
    
    for c in candidates:
        mandate = " [LEGAL MANDATE]" if c['legal_mandate'] else ""
        escalation = " ⚠️ REQUIRES HUMAN APPROVAL" if c['estimated_cost'] > COST_THRESHOLD else ""
        result += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{c['project_id']}: {c['title']}{mandate}{escalation}
  Category: {c['category']}
  Cost: ${c['estimated_cost']:,.0f}
  Risk Score: {c['risk_score']}/8
  Population: {c['population_affected']:,}
  Duration: {c['estimated_weeks']} weeks
  Crew: {c['crew_size']} {c['required_crew_type']}
"""
    
    return result


@function_tool
def evaluate_project(
    ctx: RunContextWrapper["MunicipalContext"],
    project_id: str,
    decision: str,
    confidence: int,
    reason_codes: list[str],
    rationale: str
) -> str:
    """
    Make a policy decision on a project candidate.
    
    YOU MUST DECIDE. No hedging. Choose APPROVE or REJECT.
    The system will determine if human approval is needed based on rules.
    
    Args:
        project_id: The project to evaluate
        decision: Your decision - must be "APPROVE" or "REJECT"
        confidence: Your confidence (0-100). Below 65 triggers human review.
        reason_codes: List of codes explaining the decision. Valid codes:
            - HIGH_COST: Project costs over $10M
            - LEGAL_MANDATE: Required by law
            - BUDGET_SHORTFALL: Not enough budget
            - LOW_CONFIDENCE: Uncertain about decision
            - HIGH_RISK: Risk score >= 6
            - SAFETY_CRITICAL: Safety concern
            - HIGH_POPULATION_IMPACT: Affects >200K people
            - WITHIN_POLICY: Standard approval
            - LOW_PRIORITY: Can be deferred
            - BUDGET_OPTIMIZED: Good value for money
        rationale: 2-3 sentence explanation of your decision
    
    Returns:
        Confirmation of the decision and authorization status
    """
    candidate = ctx.context.get_candidate_by_id(project_id)
    if not candidate:
        return f"Project {project_id} not found."
    
    # Validate decision
    if decision not in ["APPROVE", "REJECT"]:
        return "ERROR: decision must be 'APPROVE' or 'REJECT'. No hedging."
    
    # Validate confidence
    confidence = max(0, min(100, confidence))
    
    # Parse reason codes
    valid_codes = []
    for code in reason_codes:
        try:
            valid_codes.append(ReasonCode(code))
        except ValueError:
            pass  # Skip invalid codes
    
    # Determine authorization based on policy rules
    authorization = "AUTO"
    escalation_reasons = []
    
    # Rule 1: High cost projects require human approval
    if candidate['estimated_cost'] > COST_THRESHOLD:
        authorization = "HUMAN_REQUIRED"
        escalation_reasons.append(f"Cost ${candidate['estimated_cost']:,.0f} exceeds $10M threshold")
        if ReasonCode.HIGH_COST not in valid_codes:
            valid_codes.append(ReasonCode.HIGH_COST)
    
    # Rule 2: Legal mandates with budget issues require human approval
    if candidate['legal_mandate'] and decision == "REJECT":
        authorization = "HUMAN_REQUIRED"
        escalation_reasons.append("Legal mandate rejection requires council approval")
        if ReasonCode.LEGAL_MANDATE not in valid_codes:
            valid_codes.append(ReasonCode.LEGAL_MANDATE)
    
    # Rule 3: Low confidence requires human review
    if confidence < CONFIDENCE_THRESHOLD:
        authorization = "HUMAN_REQUIRED"
        escalation_reasons.append(f"Confidence {confidence}% below 65% threshold")
        if ReasonCode.LOW_CONFIDENCE not in valid_codes:
            valid_codes.append(ReasonCode.LOW_CONFIDENCE)
    
    # Rule 4: High risk + high population requires human review
    if (candidate['risk_score'] >= HIGH_RISK_THRESHOLD and 
        candidate['population_affected'] >= HIGH_POPULATION_THRESHOLD):
        authorization = "HUMAN_REQUIRED"
        escalation_reasons.append(f"High risk ({candidate['risk_score']}/8) affecting {candidate['population_affected']:,} people")
        if ReasonCode.HIGH_RISK not in valid_codes:
            valid_codes.append(ReasonCode.HIGH_RISK)
    
    # Create the decision object
    policy_decision = PolicyDecision(
        project_id=project_id,
        title=candidate['title'],
        decision=decision,
        authorization=authorization,
        confidence=confidence,
        reason_codes=valid_codes,
        rationale=rationale,
        estimated_cost=candidate['estimated_cost'],
        risk_score=candidate['risk_score']
    )
    
    # Generate RAG-assisted briefing for escalated decisions
    briefing_msg = ""
    if authorization == "HUMAN_REQUIRED":
        try:
            rag_service = get_rag_service()
            briefing = generate_briefing(candidate, policy_decision, rag_service)
            policy_decision.briefing = briefing
            briefing_msg = "\n\n📋 DECISION BRIEFING GENERATED for human reviewer."
        except Exception as e:
            print(f"Warning: Failed to generate briefing: {e}")
            briefing_msg = "\n\n⚠️ Briefing generation failed - human will review without RAG context."
    
    # Store in database
    ctx.context.insert_policy_decision(policy_decision, final=(authorization == "AUTO"))
    
    # Log audit
    ctx.context.log_audit(
        event_type="POLICY_DECISION",
        agent_name="governance_agent",
        payload={
            "project_id": project_id,
            "decision": decision,
            "authorization": authorization,
            "confidence": confidence,
            "reason_codes": [rc.value for rc in valid_codes],
            "has_briefing": policy_decision.briefing is not None
        }
    )
    
    # Format response
    auth_status = "✅ AUTO-EXECUTED" if authorization == "AUTO" else "⏳ AWAITING HUMAN APPROVAL"
    
    result = f"""
DECISION RECORDED
=================
Project: {candidate['title']}
Decision: {decision}
Authorization: {auth_status}
Confidence: {confidence}%

Reason Codes: {', '.join(rc.value for rc in valid_codes)}

Rationale:
{rationale}
"""
    
    if escalation_reasons:
        result += f"""
ESCALATION TRIGGERS:
"""
        for reason in escalation_reasons:
            result += f"  • {reason}\n"
    
    result += briefing_msg
    
    return result


@function_tool
def get_budget_status(ctx: RunContextWrapper["MunicipalContext"]) -> str:
    """
    Get current budget allocation status.
    """
    budget = ctx.context.get_budget_status()
    candidates = ctx.context.get_project_candidates()
    
    total_requested = sum(c['estimated_cost'] for c in candidates)
    
    return f"""
BUDGET STATUS
=============
Quarterly Budget: ${budget['total']:,.0f}
Already Approved: ${budget['allocated']:,.0f}
Remaining: ${budget['remaining']:,.0f}

Total Requested (all candidates): ${total_requested:,.0f}
Budget Gap: ${max(0, total_requested - budget['total']):,.0f}
"""


@function_tool
def get_governance_summary(ctx: RunContextWrapper["MunicipalContext"]) -> str:
    """
    Get summary of all governance decisions made.
    """
    decisions = ctx.context.get_all_decisions()
    
    if not decisions:
        return "No decisions made yet."
    
    auto_approved = [d for d in decisions if d['authorization'] == 'AUTO' and d['decision'] == 'APPROVE']
    auto_rejected = [d for d in decisions if d['authorization'] == 'AUTO' and d['decision'] == 'REJECT']
    pending = [d for d in decisions if d['authorization'] == 'HUMAN_REQUIRED' and not d['final_decision']]
    
    budget = ctx.context.get_budget_status()
    
    # Calculate pending cost
    pending_approve_cost = sum(d['estimated_cost'] for d in pending if d['decision'] == 'APPROVE')
    
    result = f"""
GOVERNANCE SUMMARY
==================

AUTO-APPROVED ({len(auto_approved)}):
"""
    for d in auto_approved:
        result += f"  ✅ {d['project_id']}: ${d['estimated_cost']:,.0f}\n"
    
    result += f"""
AUTO-REJECTED ({len(auto_rejected)}):
"""
    for d in auto_rejected:
        result += f"  ❌ {d['project_id']}: {d['rationale'][:50]}...\n"
    
    result += f"""
AWAITING HUMAN APPROVAL ({len(pending)}):
"""
    for d in pending:
        result += f"  ⏳ {d['project_id']}: {d['decision']} (confidence: {d['confidence']}%)\n"
    
    result += f"""
BUDGET IMPACT:
  Approved: ${budget['allocated']:,.0f}
  Pending (if approved): ${pending_approve_cost:,.0f}
  Remaining: ${budget['remaining']:,.0f}
"""
    
    return result


# ============ Agent Definition ============

GOVERNANCE_AGENT_INSTRUCTIONS = """
You are the Governance Agent for a municipal project management system.

YOUR JOB: Make funding decisions on project candidates.

⚠️ CRITICAL: You must DECIDE. You are not an advisor. You are a decision-maker.

POLICY RULES (you must follow these):

1. COST ESCALATION
   - Projects over $10,000,000 → Always requires human approval
   - You still DECIDE (APPROVE/REJECT), but authorization = HUMAN_REQUIRED

2. LEGAL MANDATES
   - If rejecting a legal mandate → Requires human approval
   - Legal mandates should generally be approved if budget allows

3. CONFIDENCE THRESHOLD
   - If your confidence < 65% → Requires human approval
   - Be honest about uncertainty

4. HIGH RISK + HIGH IMPACT
   - Risk score ≥ 6 AND population ≥ 200,000 → Requires human approval

5. LOW PRIORITY REJECTION
   - Risk score < 3, no legal mandate → You can REJECT autonomously

6. BUDGET CONSTRAINT
   - Never approve projects that exceed remaining budget
   - Prioritize by risk score (higher = more urgent)

PROCESS:
1. Use get_project_candidates() to see all pending projects
2. Use get_budget_status() to check available funds
3. For EACH project, use evaluate_project() to record your decision
4. Use get_governance_summary() to show final status

DECISION GUIDELINES:
- APPROVE if: Legal mandate, high risk (≥5), within budget
- REJECT if: Low risk (<3), budget exhausted, low priority
- Always provide 2-3 sentence rationale
- Set confidence honestly (0-100)

DO NOT:
- Skip any project
- Hedge your decisions
- Ask for more information
- Suggest alternatives without deciding

Evaluate ALL projects before finishing.
"""


def create_governance_agent(context: MunicipalContext) -> Agent:
    """Create the Governance Agent"""
    return Agent(
        name="GovernanceAgent",
        instructions=GOVERNANCE_AGENT_INSTRUCTIONS,
        tools=[
            get_project_candidates,
            get_budget_status,
            evaluate_project,
            get_governance_summary,
        ],
        model="gpt-4o-mini",
    )
