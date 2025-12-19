# -*- coding: utf-8 -*-
"""
Briefing Service for Municipal HITL System

Generates structured briefings for human decision-makers when projects are escalated.
The briefing is ASSISTIVE only - it does NOT recommend decisions.
"""

import json
import os
from typing import Any, Dict, Optional
from pathlib import Path

# Load environment variables
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)
except ImportError:
    pass

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

from .models import Briefing, PolicyDecision
from .rag_service import RagService


# ============ System Prompt (User-Specified) ============
# This prompt is designed to be STRICTLY ASSISTIVE, not conversational.
# The LLM must NOT recommend, argue, question, or accept instructions.

BRIEFING_SYSTEM_PROMPT = """You are a municipal policy briefing assistant.

Your role is to SUPPORT a human decision-maker.
You do NOT make decisions.
You do NOT recommend approval or rejection.

You are given:
- An escalated project
- The reason for escalation
- Retrieved policy and historical documents

Your task:
1. Summarize why escalation was triggered (1–2 bullets)
2. Cite relevant policy clauses or rules (with document names)
3. Cite 1–2 similar historical projects and outcomes
4. List key risks and trade-offs the human should consider

Constraints:
- Be factual and neutral
- No opinions or recommendations
- No questions
- Max 150 words
- Use bullet points only

Output format (JSON):
{
    "escalation_reason": ["reason 1", "reason 2"],
    "relevant_policies": ["policy excerpt 1", "policy excerpt 2"],
    "historical_precedents": ["precedent 1", "precedent 2"],
    "key_risks": ["risk 1", "risk 2"]
}
"""


def generate_briefing(
    project: Dict[str, Any], 
    decision: PolicyDecision, 
    rag_service: RagService
) -> Briefing:
    """
    Generate a structured briefing for a human reviewer.
    
    This briefing provides context to aid decision-making, but does NOT
    recommend approval or rejection. The human remains the sole decider.
    
    Args:
        project: The project candidate dictionary
        decision: The PolicyDecision made by the governance agent
        rag_service: The RAG service for retrieving policies and precedents
        
    Returns:
        A Briefing object with structured context for the human
    """
    
    # 1. Retrieve relevant context from RAG
    query = f"{project.get('title', '')} {project.get('category', '')} cost ${project.get('estimated_cost', 0):,.0f}"
    context = rag_service.retrieve_context(query)
    
    # 2. Build escalation reasons from reason codes
    escalation_reasons = []
    for code in decision.reason_codes:
        code_str = code.value if hasattr(code, 'value') else str(code)
        if code_str == "HIGH_COST":
            escalation_reasons.append(f"Project cost (${project.get('estimated_cost', 0):,.0f}) exceeds $10M threshold")
        elif code_str == "LOW_CONFIDENCE":
            escalation_reasons.append(f"Agent confidence ({decision.confidence}%) below 65% threshold")
        elif code_str == "HIGH_RISK":
            escalation_reasons.append(f"High risk score ({project.get('risk_score', 0)}/8) affecting large population")
        elif code_str == "LEGAL_MANDATE":
            escalation_reasons.append("Legal mandate rejection requires council authorization")
        elif code_str == "SAFETY_CRITICAL":
            escalation_reasons.append("Safety-critical project requires human oversight")
        elif code_str == "HIGH_POPULATION_IMPACT":
            escalation_reasons.append(f"Affects {project.get('population_affected', 0):,} residents")
    
    # 3. Check if we can use OpenAI for enhanced briefing
    openai_key = os.getenv("OPENAI_API_KEY")
    
    if not HAS_OPENAI or not openai_key:
        # Return structured briefing without LLM enhancement
        return Briefing(
            escalation_reason=escalation_reasons if escalation_reasons else ["Escalation criteria met"],
            relevant_policies=context.get("policies", [])[:2],
            historical_precedents=context.get("projects", [])[:2],
            key_risks=_extract_basic_risks(project, decision)
        )
    
    # 4. Use LLM to generate enhanced briefing
    try:
        client = openai.OpenAI(api_key=openai_key)
        
        user_content = f"""
PROJECT DETAILS:
- Title: {project.get('title', 'Unknown')}
- Category: {project.get('category', 'Unknown')}
- Estimated Cost: ${project.get('estimated_cost', 0):,.0f}
- Risk Score: {project.get('risk_score', 0)}/8
- Population Affected: {project.get('population_affected', 0):,}
- Legal Mandate: {'Yes' if project.get('legal_mandate') else 'No'}
- Duration: {project.get('estimated_weeks', 0)} weeks

AGENT DECISION:
- Decision: {decision.decision}
- Authorization: {decision.authorization}
- Confidence: {decision.confidence}%
- Reason Codes: {', '.join(rc.value if hasattr(rc, 'value') else str(rc) for rc in decision.reason_codes)}
- Rationale: {decision.rationale}

RETRIEVED POLICIES:
{json.dumps(context.get('policies', []), indent=2)}

HISTORICAL PRECEDENTS:
{json.dumps(context.get('projects', []), indent=2)}
"""
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Cost-effective for structured output
            messages=[
                {"role": "system", "content": BRIEFING_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"},
            max_tokens=500,
            temperature=0.3  # Low temperature for factual output
        )
        
        content = response.choices[0].message.content
        data = json.loads(content)
        
        return Briefing(
            escalation_reason=data.get("escalation_reason", escalation_reasons),
            relevant_policies=data.get("relevant_policies", context.get("policies", [])[:2]),
            historical_precedents=data.get("historical_precedents", context.get("projects", [])[:2]),
            key_risks=data.get("key_risks", _extract_basic_risks(project, decision))
        )
        
    except Exception as e:
        print(f"Warning: LLM briefing generation failed: {e}")
        # Fallback to structured briefing without LLM
        return Briefing(
            escalation_reason=escalation_reasons if escalation_reasons else ["Escalation criteria met"],
            relevant_policies=context.get("policies", [])[:2],
            historical_precedents=context.get("projects", [])[:2],
            key_risks=_extract_basic_risks(project, decision)
        )


def _extract_basic_risks(project: Dict[str, Any], decision: PolicyDecision) -> list[str]:
    """Extract basic risks from project data without LLM."""
    risks = []
    
    cost = project.get('estimated_cost', 0)
    if cost > 10_000_000:
        risks.append(f"Large budget commitment: ${cost:,.0f}")
    
    risk_score = project.get('risk_score', 0)
    if risk_score >= 6:
        risks.append(f"High technical/execution risk (score: {risk_score}/8)")
    
    population = project.get('population_affected', 0)
    if population >= 200_000:
        risks.append(f"Significant community impact: {population:,} residents affected")
    
    if project.get('legal_mandate') and decision.decision == "REJECT":
        risks.append("Legal compliance risk if mandate not addressed")
    
    if decision.confidence < 65:
        risks.append(f"Decision uncertainty: {decision.confidence}% confidence")
    
    if not risks:
        risks.append("Standard project risks apply")
    
    return risks[:4]  # Limit to 4 risks


def format_briefing_for_display(briefing: Briefing) -> str:
    """
    Format a briefing for human-readable display.
    
    Args:
        briefing: The Briefing object to format
        
    Returns:
        Formatted string for display
    """
    output = []
    output.append("=" * 60)
    output.append("DECISION BRIEFING")
    output.append("=" * 60)
    
    output.append("\n📋 ESCALATION REASON:")
    for reason in briefing.escalation_reason:
        output.append(f"  • {reason}")
    
    output.append("\n📜 RELEVANT POLICIES:")
    for policy in briefing.relevant_policies:
        output.append(f"  • {policy}")
    
    output.append("\n📊 HISTORICAL PRECEDENTS:")
    for precedent in briefing.historical_precedents:
        output.append(f"  • {precedent}")
    
    output.append("\n⚠️ KEY RISKS / TRADE-OFFS:")
    for risk in briefing.key_risks:
        output.append(f"  • {risk}")
    
    output.append("\n" + "=" * 60)
    output.append("This briefing is for informational purposes only.")
    output.append("The final decision rests with the human reviewer.")
    output.append("=" * 60)
    
    return "\n".join(output)
