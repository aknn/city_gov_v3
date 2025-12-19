# -*- coding: utf-8 -*-
"""
Agent 1: Formation Agent

Converts citizen issues into structured project candidates.
Uses deterministic risk scoring with LLM-generated scope descriptions.
"""

from agents import Agent, function_tool, RunContextWrapper
from .context import MunicipalContext
import uuid


# ============ Risk Scoring Logic ============

def calculate_risk_score(issue: dict) -> float:
    """
    Deterministic risk calculation.
    
    Weights:
    - Severity (1-5): 40%
    - Population impact: 30%
    - Legal mandate: 30%
    
    Returns score 0-8
    """
    severity = issue.get('severity', 3)
    population = issue.get('population_affected', 0)
    legal = issue.get('legal_mandate', 0)
    
    # Normalize population (log scale, max ~1M)
    if population > 0:
        import math
        pop_score = min(5, math.log10(population) / 6 * 5)
    else:
        pop_score = 0
    
    # Calculate weighted score
    risk = (severity * 0.4 * 1.6) + (pop_score * 0.3 * 1.6) + (legal * 3 * 0.3 * 1.6)
    
    return round(min(8, max(0, risk)), 1)


def estimate_project_params(issue: dict) -> dict:
    """
    Estimate project parameters based on category and severity.
    
    Returns: cost, duration, crew_type, crew_size
    """
    category = issue.get('category', 'general')
    severity = issue.get('severity', 3)
    population = issue.get('population_affected', 0)
    
    # Base estimates by category
    category_params = {
        'water_infrastructure': {
            'crew_type': 'water_crew',
            'base_cost': 8_000_000,
            'base_weeks': 12,
            'crew_size': 8
        },
        'healthcare_facility': {
            'crew_type': 'electrical_crew',
            'base_cost': 6_000_000,
            'base_weeks': 10,
            'crew_size': 6
        },
        'flood_control': {
            'crew_type': 'general_construction',
            'base_cost': 10_000_000,
            'base_weeks': 16,
            'crew_size': 12
        },
        'transportation': {
            'crew_type': 'road_crew',
            'base_cost': 5_000_000,
            'base_weeks': 8,
            'crew_size': 10
        },
        'public_buildings': {
            'crew_type': 'electrical_crew',
            'base_cost': 4_000_000,
            'base_weeks': 8,
            'crew_size': 5
        },
        'road_maintenance': {
            'crew_type': 'road_crew',
            'base_cost': 2_000_000,
            'base_weeks': 4,
            'crew_size': 8
        },
        'parks_recreation': {
            'crew_type': 'general_construction',
            'base_cost': 1_500_000,
            'base_weeks': 6,
            'crew_size': 4
        },
        'electrical': {
            'crew_type': 'electrical_crew',
            'base_cost': 2_500_000,
            'base_weeks': 6,
            'crew_size': 5
        },
        'accessibility': {
            'crew_type': 'road_crew',
            'base_cost': 3_000_000,
            'base_weeks': 8,
            'crew_size': 6
        },
    }
    
    params = category_params.get(category, {
        'crew_type': 'general_construction',
        'base_cost': 3_000_000,
        'base_weeks': 8,
        'crew_size': 6
    })
    
    # Scale by severity and population
    severity_multiplier = 0.6 + (severity * 0.2)  # 0.8 to 1.6
    pop_multiplier = 1.0 + (min(population, 500000) / 1_000_000)  # 1.0 to 1.5
    
    return {
        'estimated_cost': round(params['base_cost'] * severity_multiplier * pop_multiplier, -3),
        'estimated_weeks': max(2, round(params['base_weeks'] * severity_multiplier)),
        'required_crew_type': params['crew_type'],
        'crew_size': params['crew_size']
    }


# ============ Agent Tools ============

@function_tool
def get_open_issues(ctx: RunContextWrapper["MunicipalContext"]) -> str:
    """
    Retrieve all open citizen issues from the database.
    
    Returns a list of issues with their details.
    """
    issues = ctx.context.get_open_issues()
    
    if not issues:
        return "No open issues found."
    
    result = f"Found {len(issues)} open issues:\n\n"
    for issue in issues:
        result += f"""
Issue #{issue['issue_id']}: {issue['title']}
  Category: {issue['category']}
  Severity: {issue['severity']}/5
  Population Affected: {issue['population_affected']:,}
  Legal Mandate: {'Yes' if issue['legal_mandate'] else 'No'}
  Description: {issue['description'][:200]}...
"""
    return result


@function_tool
def assess_issue_risk(
    ctx: RunContextWrapper["MunicipalContext"],
    issue_id: int
) -> str:
    """
    Calculate the risk score for a specific issue.
    
    Args:
        issue_id: The ID of the issue to assess
    
    Returns:
        Risk assessment with score breakdown
    """
    issue = ctx.context.get_issue_by_id(issue_id)
    if not issue:
        return f"Issue {issue_id} not found."
    
    risk_score = calculate_risk_score(issue)
    params = estimate_project_params(issue)
    
    return f"""
Risk Assessment for Issue #{issue_id}: {issue['title']}

RISK SCORE: {risk_score}/8 {'⚠️ HIGH RISK' if risk_score >= 5 else ''}

Factors:
- Severity: {issue['severity']}/5
- Population Affected: {issue['population_affected']:,}
- Legal Mandate: {'Yes (+2.4 points)' if issue['legal_mandate'] else 'No'}

Estimated Project Parameters:
- Cost: ${params['estimated_cost']:,.0f}
- Duration: {params['estimated_weeks']} weeks
- Crew Type: {params['required_crew_type']}
- Crew Size: {params['crew_size']} workers

Recommendation: {'FORM PROJECT' if risk_score >= 3 else 'DEFER - Low priority'}
"""


@function_tool
def create_project_candidate(
    ctx: RunContextWrapper["MunicipalContext"],
    issue_id: int,
    scope_description: str
) -> str:
    """
    Create a project candidate from an assessed issue.
    
    Args:
        issue_id: The issue to convert into a project
        scope_description: LLM-generated description of the project scope
    
    Returns:
        Confirmation with project details
    """
    issue = ctx.context.get_issue_by_id(issue_id)
    if not issue:
        return f"Issue {issue_id} not found."
    
    # Check if already created
    existing = ctx.context.get_project_candidates()
    if any(c['issue_id'] == issue_id for c in existing):
        return f"Project candidate already exists for issue {issue_id}"
    
    risk_score = calculate_risk_score(issue)
    params = estimate_project_params(issue)
    
    # Generate project ID
    project_id = f"PRJ-{issue_id:03d}-{uuid.uuid4().hex[:6].upper()}"
    
    candidate = {
        'project_id': project_id,
        'issue_id': issue_id,
        'title': issue['title'],
        'scope': scope_description,
        'category': issue['category'],
        'estimated_cost': params['estimated_cost'],
        'estimated_weeks': params['estimated_weeks'],
        'required_crew_type': params['required_crew_type'],
        'crew_size': params['crew_size'],
        'risk_score': risk_score,
        'feasibility_score': 1.0,
        'population_affected': issue['population_affected'],
        'legal_mandate': issue['legal_mandate']
    }
    
    ctx.context.insert_project_candidate(candidate)
    
    # Log audit
    ctx.context.log_audit(
        event_type="PROJECT_FORMED",
        agent_name="formation_agent",
        payload=candidate
    )
    
    return f"""
✅ Project Candidate Created

Project ID: {project_id}
Title: {issue['title']}
Risk Score: {risk_score}/8
Estimated Cost: ${params['estimated_cost']:,.0f}
Duration: {params['estimated_weeks']} weeks

Scope:
{scope_description}

Status: Ready for Governance Agent review
"""


@function_tool
def get_formation_summary(ctx: RunContextWrapper["MunicipalContext"]) -> str:
    """
    Get a summary of all formed project candidates.
    """
    candidates = ctx.context.get_project_candidates()
    
    if not candidates:
        return "No project candidates formed yet."
    
    total_cost = sum(c['estimated_cost'] for c in candidates)
    
    result = f"""
PROJECT FORMATION SUMMARY
========================
Total Candidates: {len(candidates)}
Total Estimated Cost: ${total_cost:,.0f}

Projects:
"""
    for c in candidates:
        mandate = " [LEGAL MANDATE]" if c['legal_mandate'] else ""
        result += f"""
• {c['project_id']}: {c['title']}{mandate}
  Risk: {c['risk_score']}/8 | Cost: ${c['estimated_cost']:,.0f} | Duration: {c['estimated_weeks']}w
"""
    
    return result


# ============ Agent Definition ============

FORMATION_AGENT_INSTRUCTIONS = """
You are the Formation Agent for a municipal project management system.

YOUR JOB:
Convert citizen issues into structured project candidates.

PROCESS:
1. Use get_open_issues() to see all pending issues
2. For each issue with risk score >= 3:
   a. Use assess_issue_risk(issue_id) to calculate risk
   b. Use create_project_candidate(issue_id, scope) to form the project
   c. Write a 2-3 sentence scope description
3. Use get_formation_summary() to show final results

SCOPE DESCRIPTION GUIDELINES:
- Be specific about what work will be done
- Mention key deliverables
- Keep it under 50 words

EXAMPLE SCOPE:
"Replace 2.4km of aging cast iron water main with ductile iron pipe. 
Install 12 new valve stations and upgrade 3 pump connections. 
Includes traffic management and surface restoration."

Process ALL high-risk issues (score >= 3) before finishing.
"""


def create_formation_agent(context: MunicipalContext) -> Agent:
    """Create the Formation Agent"""
    return Agent(
        name="FormationAgent",
        instructions=FORMATION_AGENT_INSTRUCTIONS,
        tools=[
            get_open_issues,
            assess_issue_risk,
            create_project_candidate,
            get_formation_summary,
        ],
        model="gpt-4o-mini",
    )
