# -*- coding: utf-8 -*-
"""
Pydantic models for the Municipal HITL System

Key model: PolicyDecision - the structured output that makes Agent 2 *agentic*
The agent DECIDES, then the human APPROVES or OVERRIDES.
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional, List
from enum import Enum


class ReasonCode(str, Enum):
    """Canonical reason codes for escalation decisions"""
    # Authority escalation (hard rules)
    HIGH_COST = "HIGH_COST"  # > $10M threshold
    LEGAL_MANDATE = "LEGAL_MANDATE"
    BUDGET_SHORTFALL = "BUDGET_SHORTFALL"
    
    # Epistemic escalation (uncertainty)
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    CONFLICTING_PRIORITIES = "CONFLICTING_PRIORITIES"
    
    # Risk escalation
    HIGH_RISK = "HIGH_RISK"
    SAFETY_CRITICAL = "SAFETY_CRITICAL"
    HIGH_POPULATION_IMPACT = "HIGH_POPULATION_IMPACT"
    
    # Standard decisions
    WITHIN_POLICY = "WITHIN_POLICY"
    LOW_PRIORITY = "LOW_PRIORITY"
    BUDGET_OPTIMIZED = "BUDGET_OPTIMIZED"


class Briefing(BaseModel):
    """
    LLM-generated briefing for human reviewers.
    
    Provides context, precedents, and risks to aid decision-making.
    This is ASSISTIVE only - it does NOT recommend decisions.
    """
    escalation_reason: List[str] = Field(
        description="Why this decision was escalated to a human (1-2 bullets)"
    )
    relevant_policies: List[str] = Field(
        description="Cited policy clauses or rules with document names"
    )
    historical_precedents: List[str] = Field(
        description="Similar past projects and their outcomes (1-2 examples)"
    )
    key_risks: List[str] = Field(
        description="Key risks and trade-offs the human should consider"
    )


class PolicyDecision(BaseModel):
    """
    Structured decision output from Governance Agent.
    
    This is what makes the agent *agentic* - it commits to a decision,
    rather than just explaining options.
    """
    project_id: str = Field(description="The project ID being evaluated")
    title: str = Field(description="Project title for display")
    
    # The agent's decision (binary, no hedging)
    decision: Literal["APPROVE", "REJECT"] = Field(
        description="The agent's decision. Must choose one."
    )
    
    # Separate from decision - about authority, not confusion
    authorization: Literal["AUTO", "HUMAN_REQUIRED"] = Field(
        description="AUTO = agent can execute. HUMAN_REQUIRED = needs approval."
    )
    
    # Epistemic hygiene - force the agent to quantify uncertainty
    confidence: int = Field(
        ge=0, le=100,
        description="Confidence percentage (0-100). Below 65 triggers escalation."
    )
    
    # Auditability
    reason_codes: list[ReasonCode] = Field(
        description="Machine-readable codes explaining the decision"
    )
    
    rationale: str = Field(
        description="Human-readable explanation (2-3 sentences)"
    )
    
    # Context for display
    estimated_cost: float = Field(description="Project cost in dollars")
    risk_score: float = Field(description="Risk score (0-8)")
    
    # RAG-assisted briefing for human reviewers (only for escalated decisions)
    briefing: Optional[Briefing] = Field(
        default=None,
        description="Contextual briefing for human reviewer (only for HUMAN_REQUIRED decisions)"
    )


class ProjectCandidate(BaseModel):
    """A project candidate created by the Formation Agent"""
    project_id: str
    issue_id: int
    title: str
    scope: str
    category: str
    estimated_cost: float
    estimated_weeks: int
    required_crew_type: str
    crew_size: int
    risk_score: float
    feasibility_score: float
    population_affected: int
    legal_mandate: bool = False


class HumanDecision(BaseModel):
    """Human's response to an escalated decision"""
    project_id: str
    human_decision: Literal["APPROVE", "REJECT"]
    override_reason: str = ""


class ApprovalRequest(BaseModel):
    """Batch of decisions awaiting human approval"""
    pending_decisions: list[PolicyDecision]
    auto_approved: list[PolicyDecision]
    auto_rejected: list[PolicyDecision]
    budget_remaining: float
    budget_total: float


class ScheduleTask(BaseModel):
    """A scheduled project task"""
    project_id: str
    title: str
    start_week: int
    end_week: int
    crew_type: str
    crew_size: int
    status: Literal["SCHEDULED", "BLOCKED"] = "SCHEDULED"


class PipelineResult(BaseModel):
    """Final result of the complete pipeline"""
    phase: Literal["FORMATION", "AWAITING_APPROVAL", "GOVERNANCE_COMPLETE", "SCHEDULED"]
    candidates_formed: int = 0
    decisions_pending: int = 0
    projects_approved: int = 0
    projects_rejected: int = 0
    projects_scheduled: int = 0
    budget_allocated: float = 0
    budget_remaining: float = 0
