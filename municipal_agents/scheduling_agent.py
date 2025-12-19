# -*- coding: utf-8 -*-
"""
Agent 3: Scheduling Agent

Schedules approved projects within resource constraints.
Uses greedy scheduling with LLM-driven conflict resolution.
"""

from agents import Agent, function_tool, RunContextWrapper
from .context import MunicipalContext


# ============ Scheduling Logic ============

def check_crew_availability(
    crew_type: str, 
    crew_needed: int, 
    start_week: int, 
    end_week: int,
    existing_tasks: list,
    capacity: dict
) -> bool:
    """
    Check if crew is available for the given time window.
    """
    total_capacity = capacity.get(crew_type, 10)
    
    for week in range(start_week, end_week + 1):
        used = sum(
            t['crew_size'] for t in existing_tasks
            if t['crew_type'] == crew_type
            and t['start_week'] <= week <= t['end_week']
        )
        if used + crew_needed > total_capacity:
            return False
    
    return True


def find_earliest_slot(
    crew_type: str,
    crew_needed: int,
    duration_weeks: int,
    existing_tasks: list,
    capacity: dict,
    max_week: int = 13  # Quarter = 13 weeks
) -> int:
    """
    Find the earliest week where the project can start.
    Returns -1 if no slot available in the quarter.
    """
    for start in range(1, max_week - duration_weeks + 2):
        end = start + duration_weeks - 1
        if end > max_week:
            return -1
        if check_crew_availability(crew_type, crew_needed, start, end, existing_tasks, capacity):
            return start
    return -1


# ============ Agent Tools ============

@function_tool
def get_approved_projects(ctx: RunContextWrapper["MunicipalContext"]) -> str:
    """
    Get all projects approved for scheduling.
    """
    projects = ctx.context.get_approved_projects()
    
    if not projects:
        return "No approved projects found. Complete governance stage first."
    
    result = f"Found {len(projects)} approved projects for scheduling:\n\n"
    
    for p in projects:
        result += f"""
{p['project_id']}: {p['title']}
  Duration: {p['estimated_weeks']} weeks
  Crew: {p['crew_size']} {p['required_crew_type']}
  Risk: {p['risk_score']}/8
"""
    
    return result


@function_tool
def get_resource_status(ctx: RunContextWrapper["MunicipalContext"]) -> str:
    """
    Get current crew capacity and scheduled utilization.
    """
    capacity = ctx.context.get_crew_capacity()
    tasks = ctx.context.get_schedule_tasks()
    
    result = "RESOURCE STATUS\n===============\n\n"
    
    for crew_type, total in capacity.items():
        # Calculate peak usage
        peak_usage = 0
        for week in range(1, 14):
            week_usage = sum(
                t['crew_size'] for t in tasks
                if t['crew_type'] == crew_type
                and t['start_week'] <= week <= t['end_week']
            )
            peak_usage = max(peak_usage, week_usage)
        
        utilization = (peak_usage / total * 100) if total > 0 else 0
        result += f"{crew_type}: {peak_usage}/{total} workers (peak {utilization:.0f}% utilization)\n"
    
    return result


@function_tool
def schedule_project(
    ctx: RunContextWrapper["MunicipalContext"],
    project_id: str
) -> str:
    """
    Schedule an approved project in the earliest available slot.
    
    Args:
        project_id: The project to schedule
    
    Returns:
        Schedule confirmation or conflict explanation
    """
    project = ctx.context.get_candidate_by_id(project_id)
    if not project:
        return f"Project {project_id} not found."
    
    # Check if already scheduled
    existing_tasks = ctx.context.get_schedule_tasks()
    if any(t['project_id'] == project_id for t in existing_tasks):
        return f"Project {project_id} is already scheduled."
    
    capacity = ctx.context.get_crew_capacity()
    
    # Find earliest slot
    start_week = find_earliest_slot(
        crew_type=project['required_crew_type'],
        crew_needed=project['crew_size'],
        duration_weeks=project['estimated_weeks'],
        existing_tasks=existing_tasks,
        capacity=capacity
    )
    
    if start_week == -1:
        # Cannot schedule - create blocked task
        ctx.context.insert_schedule_task({
            'project_id': project_id,
            'start_week': 0,
            'end_week': 0,
            'crew_type': project['required_crew_type'],
            'crew_size': project['crew_size'],
            'status': 'BLOCKED'
        })
        
        return f"""
❌ SCHEDULING CONFLICT

Project: {project['title']}
Required: {project['crew_size']} {project['required_crew_type']} for {project['estimated_weeks']} weeks

Cannot schedule within the quarter due to resource constraints.
Status: BLOCKED

Suggestions:
1. Defer to next quarter
2. Reduce crew size (extend duration)
3. Consider alternative crew type if feasible
"""
    
    end_week = start_week + project['estimated_weeks'] - 1
    
    # Insert scheduled task
    ctx.context.insert_schedule_task({
        'project_id': project_id,
        'start_week': start_week,
        'end_week': end_week,
        'crew_type': project['required_crew_type'],
        'crew_size': project['crew_size'],
        'status': 'SCHEDULED'
    })
    
    # Log audit
    ctx.context.log_audit(
        event_type="PROJECT_SCHEDULED",
        agent_name="scheduling_agent",
        payload={
            'project_id': project_id,
            'start_week': start_week,
            'end_week': end_week
        }
    )
    
    return f"""
✅ PROJECT SCHEDULED

Project: {project['title']}
Weeks: {start_week} - {end_week}
Crew: {project['crew_size']} {project['required_crew_type']}
Duration: {project['estimated_weeks']} weeks
"""


@function_tool
def get_schedule_summary(ctx: RunContextWrapper["MunicipalContext"]) -> str:
    """
    Get the complete schedule for the quarter.
    """
    tasks = ctx.context.get_schedule_tasks()
    
    if not tasks:
        return "No projects scheduled yet."
    
    scheduled = [t for t in tasks if t['status'] == 'SCHEDULED']
    blocked = [t for t in tasks if t['status'] == 'BLOCKED']
    
    result = f"""
QUARTERLY SCHEDULE
==================
Scheduled: {len(scheduled)} projects
Blocked: {len(blocked)} projects

GANTT CHART (13-week quarter):
"""
    
    # Simple text-based Gantt
    for t in scheduled:
        bar = "·" * (t['start_week'] - 1) + "█" * (t['end_week'] - t['start_week'] + 1) + "·" * (13 - t['end_week'])
        result += f"\n{t['project_id'][:12]:12} |{bar}| W{t['start_week']}-{t['end_week']}"
    
    if blocked:
        result += "\n\nBLOCKED PROJECTS:\n"
        for t in blocked:
            result += f"  ❌ {t['project_id']}: Resource conflict\n"
    
    return result


# ============ Agent Definition ============

SCHEDULING_AGENT_INSTRUCTIONS = """
You are the Scheduling Agent for a municipal project management system.

YOUR JOB: Schedule approved projects within the 13-week quarter, respecting resource constraints.

CONSTRAINTS:
- Quarter is 13 weeks (weeks 1-13)
- Each crew type has limited capacity
- Projects cannot overlap if they exceed crew capacity
- Priority: Higher risk score = schedule earlier

PROCESS:
1. Use get_approved_projects() to see what needs scheduling
2. Use get_resource_status() to see current capacity
3. For EACH project (in risk order), use schedule_project() to schedule it
4. Use get_schedule_summary() to show the final schedule

SCHEDULING RULES:
- Schedule highest-risk projects first
- Use earliest available slot
- If blocked, record the conflict but continue with other projects

For blocked projects, explain:
- Why the conflict occurred
- What alternatives might help

Schedule ALL approved projects before finishing.
"""


def create_scheduling_agent(context: MunicipalContext) -> Agent:
    """Create the Scheduling Agent"""
    return Agent(
        name="SchedulingAgent",
        instructions=SCHEDULING_AGENT_INSTRUCTIONS,
        tools=[
            get_approved_projects,
            get_resource_status,
            schedule_project,
            get_schedule_summary,
        ],
        model="gpt-4o-mini",
    )
