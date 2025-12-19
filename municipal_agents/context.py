# -*- coding: utf-8 -*-
"""
Shared context object for all agents in the Municipal HITL System

This context holds the budget, database connection, and shared state.
"""

import sqlite3
import json
from dataclasses import dataclass, field
from typing import Optional

from .database import get_connection, DB_PATH
from .models import PolicyDecision, ProjectCandidate, Briefing


@dataclass
class MunicipalContext:
    """
    Shared context passed to all agents.
    
    Contains:
    - Budget constraints
    - Database access methods
    - Pending approval queue
    """
    quarterly_budget: float = 75_000_000  # $75M default
    
    # Internal state
    _pending_approvals: list[PolicyDecision] = field(default_factory=list)
    _auto_decisions: list[PolicyDecision] = field(default_factory=list)
    
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        return get_connection()
    
    def execute(self, query: str, params: tuple = ()) -> list:
        """Execute a query and return results"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.commit()
        conn.close()
        return results
    
    def execute_insert(self, query: str, params: tuple = ()) -> int:
        """Execute an insert and return the last row id"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        last_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return last_id
    
    # ============ Issue Methods ============
    
    def get_open_issues(self) -> list[dict]:
        """Get all open issues"""
        rows = self.execute("""
            SELECT * FROM issues WHERE status = 'open' ORDER BY severity DESC
        """)
        return [dict(row) for row in rows]
    
    def get_issue_by_id(self, issue_id: int) -> Optional[dict]:
        """Get a single issue by ID"""
        rows = self.execute("SELECT * FROM issues WHERE issue_id = ?", (issue_id,))
        return dict(rows[0]) if rows else None
    
    # ============ Project Candidate Methods ============
    
    def insert_project_candidate(self, candidate: dict) -> str:
        """Insert a new project candidate"""
        self.execute("""
            INSERT INTO project_candidates 
            (project_id, issue_id, title, scope, category, estimated_cost, 
             estimated_weeks, required_crew_type, crew_size, risk_score, 
             feasibility_score, population_affected, legal_mandate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            candidate['project_id'],
            candidate['issue_id'],
            candidate['title'],
            candidate.get('scope', ''),
            candidate['category'],
            candidate['estimated_cost'],
            candidate['estimated_weeks'],
            candidate['required_crew_type'],
            candidate['crew_size'],
            candidate['risk_score'],
            candidate.get('feasibility_score', 1.0),
            candidate.get('population_affected', 0),
            1 if candidate.get('legal_mandate') else 0
        ))
        return candidate['project_id']
    
    def get_project_candidates(self) -> list[dict]:
        """Get all project candidates"""
        rows = self.execute("SELECT * FROM project_candidates ORDER BY risk_score DESC")
        return [dict(row) for row in rows]
    
    def get_candidate_by_id(self, project_id: str) -> Optional[dict]:
        """Get a single project candidate"""
        rows = self.execute(
            "SELECT * FROM project_candidates WHERE project_id = ?", 
            (project_id,)
        )
        return dict(rows[0]) if rows else None
    
    # ============ Policy Decision Methods ============
    
    def insert_policy_decision(self, decision: PolicyDecision, final: bool = False):
        """Insert a policy decision"""
        final_decision = decision.decision if final else None
        
        # Serialize briefing if present
        briefing_json = None
        if decision.briefing:
            briefing_json = decision.briefing.model_dump_json()
        
        self.execute("""
            INSERT INTO policy_decisions 
            (project_id, decision, authorization, confidence, reason_codes, rationale, final_decision, briefing)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            decision.project_id,
            decision.decision,
            decision.authorization,
            decision.confidence,
            json.dumps([rc.value for rc in decision.reason_codes]),
            decision.rationale,
            final_decision,
            briefing_json
        ))
    
    def update_decision_with_human_input(
        self, 
        project_id: str, 
        human_decision: str, 
        human_reason: str = ""
    ):
        """Update a decision with human override"""
        self.execute("""
            UPDATE policy_decisions 
            SET human_override = 1, 
                human_decision = ?, 
                human_reason = ?,
                final_decision = ?
            WHERE project_id = ?
        """, (human_decision, human_reason, human_decision, project_id))
    
    def finalize_auto_decisions(self):
        """Finalize all AUTO authorization decisions"""
        self.execute("""
            UPDATE policy_decisions 
            SET final_decision = decision
            WHERE authorization = 'AUTO' AND final_decision IS NULL
        """)
    
    def get_approved_projects(self) -> list[dict]:
        """Get all finally approved projects"""
        rows = self.execute("""
            SELECT pc.*, pd.final_decision, pd.rationale
            FROM project_candidates pc
            JOIN policy_decisions pd ON pc.project_id = pd.project_id
            WHERE pd.final_decision = 'APPROVE'
            ORDER BY pc.risk_score DESC
        """)
        return [dict(row) for row in rows]
    
    def get_pending_decisions(self) -> list[dict]:
        """Get decisions awaiting human approval"""
        rows = self.execute("""
            SELECT pd.*, pc.title, pc.estimated_cost, pc.risk_score, 
                   pc.population_affected, pc.legal_mandate, pc.category
            FROM policy_decisions pd
            JOIN project_candidates pc ON pd.project_id = pc.project_id
            WHERE pd.authorization = 'HUMAN_REQUIRED' AND pd.final_decision IS NULL
            ORDER BY pc.risk_score DESC
        """)
        
        results = []
        for row in rows:
            d = dict(row)
            # Deserialize briefing if present
            if d.get('briefing'):
                try:
                    briefing_data = json.loads(d['briefing'])
                    d['briefing'] = Briefing(**briefing_data)
                except (json.JSONDecodeError, Exception):
                    d['briefing'] = None
            results.append(d)
        
        return results
    
    def get_all_decisions(self) -> list[dict]:
        """Get all policy decisions with project details"""
        rows = self.execute("""
            SELECT pd.*, pc.title, pc.estimated_cost, pc.risk_score, 
                   pc.population_affected, pc.legal_mandate, pc.category,
                   pc.estimated_weeks, pc.required_crew_type
            FROM policy_decisions pd
            JOIN project_candidates pc ON pd.project_id = pc.project_id
            ORDER BY pc.risk_score DESC
        """)
        return [dict(row) for row in rows]
    
    # ============ Schedule Methods ============
    
    def insert_schedule_task(self, task: dict):
        """Insert a schedule task"""
        self.execute("""
            INSERT INTO schedule_tasks 
            (project_id, start_week, end_week, crew_type, crew_size, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            task['project_id'],
            task['start_week'],
            task['end_week'],
            task['crew_type'],
            task['crew_size'],
            task.get('status', 'SCHEDULED')
        ))
    
    def get_schedule_tasks(self) -> list[dict]:
        """Get all scheduled tasks"""
        rows = self.execute("""
            SELECT st.*, pc.title 
            FROM schedule_tasks st
            JOIN project_candidates pc ON st.project_id = pc.project_id
            ORDER BY st.start_week
        """)
        return [dict(row) for row in rows]
    
    def get_crew_capacity(self) -> dict[str, int]:
        """Get crew capacity by type"""
        rows = self.execute("SELECT crew_type, total_capacity FROM crew_capacity")
        return {row['crew_type']: row['total_capacity'] for row in rows}
    
    # ============ Budget Methods ============
    
    def get_budget_status(self) -> dict:
        """Get current budget allocation status"""
        rows = self.execute("""
            SELECT COALESCE(SUM(pc.estimated_cost), 0) as allocated
            FROM project_candidates pc
            JOIN policy_decisions pd ON pc.project_id = pd.project_id
            WHERE pd.final_decision = 'APPROVE'
        """)
        allocated = rows[0]['allocated'] if rows else 0
        return {
            "total": self.quarterly_budget,
            "allocated": allocated,
            "remaining": self.quarterly_budget - allocated
        }
    
    # ============ Audit Methods ============
    
    def log_audit(self, event_type: str, agent_name: str, payload: dict):
        """Log an audit event"""
        self.execute("""
            INSERT INTO audit_log (event_type, agent_name, payload)
            VALUES (?, ?, ?)
        """, (event_type, agent_name, json.dumps(payload)))
