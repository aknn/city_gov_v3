# -*- coding: utf-8 -*-
"""
Flask API for Municipal HITL System

Provides REST endpoints for:
- Running the pipeline (stages 1-2)
- Getting pending approvals
- Submitting human decisions
- Continuing to scheduling (stage 3)
- Getting final results
"""

import asyncio
import os
import sys
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from municipal_agents import (
    MunicipalContext,
    init_database,
    seed_sample_data,
    clear_agent_outputs,
    run_formation_stage,
    run_governance_stage,
    run_scheduling_stage,
    get_pending_approvals,
    submit_human_decisions,
)

app = Flask(__name__)
CORS(app)

# Global context (in production, use proper session management)
_context: MunicipalContext = None


def get_context() -> MunicipalContext:
    global _context
    if _context is None:
        _context = MunicipalContext(quarterly_budget=75_000_000)
    return _context


def reset_context(budget: float = 75_000_000):
    global _context
    _context = MunicipalContext(quarterly_budget=budget)
    return _context


# ============ API Endpoints ============

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "municipal-hitl"})


@app.route('/api/init', methods=['POST'])
def initialize_system():
    """
    Initialize/reset the database and start fresh.
    
    Body: { "budget": 75000000 }
    """
    data = request.get_json() or {}
    budget = float(data.get('budget', 75_000_000))
    
    try:
        init_database()
        seed_sample_data()
        clear_agent_outputs()
        context = reset_context(budget)
        
        return jsonify({
            "success": True,
            "message": "System initialized",
            "budget": budget
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/run-formation', methods=['POST'])
def run_formation():
    """
    Run Stage 1: Formation Agent
    
    Creates project candidates from open issues.
    """
    try:
        context = get_context()
        result = asyncio.run(run_formation_stage(context, verbose=False))
        
        return jsonify({
            "success": True,
            "stage": "FORMATION",
            "candidates_formed": result['candidates_formed'],
            "total_cost": result['total_cost']
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/run-governance', methods=['POST'])
def run_governance():
    """
    Run Stage 2: Governance Agent
    
    Makes policy decisions. May require human approval for some projects.
    """
    try:
        context = get_context()
        result = asyncio.run(run_governance_stage(context, verbose=False))
        
        return jsonify({
            "success": True,
            "stage": "GOVERNANCE",
            "total_decisions": result['total_decisions'],
            "auto_approved": result['auto_approved'],
            "auto_rejected": result['auto_rejected'],
            "pending_human_approval": result['pending_human_approval'],
            "requires_approval": result['requires_approval']
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/pending-approvals', methods=['GET'])
def get_pending():
    """
    Get all decisions awaiting human approval.
    
    Returns pending decisions with full project details.
    """
    try:
        context = get_context()
        result = get_pending_approvals(context)
        
        # Format pending decisions for UI
        pending = []
        for d in result['pending']:
            pending.append({
                "project_id": d['project_id'],
                "title": d['title'],
                "category": d['category'],
                "estimated_cost": d['estimated_cost'],
                "risk_score": d['risk_score'],
                "population_affected": d['population_affected'],
                "legal_mandate": bool(d['legal_mandate']),
                "agent_decision": d['decision'],
                "confidence": d['confidence'],
                "reason_codes": d['reason_codes'],
                "rationale": d['rationale']
            })
        
        auto_approved = []
        for d in result['auto_approved']:
            auto_approved.append({
                "project_id": d['project_id'],
                "title": d['title'],
                "estimated_cost": d['estimated_cost'],
                "risk_score": d['risk_score'],
                "rationale": d['rationale']
            })
        
        auto_rejected = []
        for d in result['auto_rejected']:
            auto_rejected.append({
                "project_id": d['project_id'],
                "title": d['title'],
                "estimated_cost": d['estimated_cost'],
                "rationale": d['rationale']
            })
        
        return jsonify({
            "success": True,
            "pending": pending,
            "auto_approved": auto_approved,
            "auto_rejected": auto_rejected,
            "budget": result['budget'],
            "requires_approval": result['requires_approval']
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/submit-approvals', methods=['POST'])
def submit_approvals():
    """
    Submit human decisions for pending approvals.
    
    Body: {
        "decisions": [
            {"project_id": "PRJ-001", "decision": "APPROVE", "reason": "..."},
            {"project_id": "PRJ-002", "decision": "REJECT", "reason": "..."}
        ]
    }
    """
    try:
        data = request.get_json()
        if not data or 'decisions' not in data:
            return jsonify({"success": False, "error": "Missing decisions"}), 400
        
        context = get_context()
        result = submit_human_decisions(context, data['decisions'])
        
        return jsonify({
            "success": True,
            "submitted": result['submitted'],
            "approved": result['approved'],
            "rejected": result['rejected']
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/run-scheduling', methods=['POST'])
def run_scheduling():
    """
    Run Stage 3: Scheduling Agent
    
    Schedules all approved projects.
    """
    try:
        context = get_context()
        result = asyncio.run(run_scheduling_stage(context, verbose=False))
        
        return jsonify({
            "success": True,
            "stage": "SCHEDULING",
            "total_tasks": result['total_tasks'],
            "scheduled": result['scheduled'],
            "blocked": result['blocked']
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/results', methods=['GET'])
def get_results():
    """
    Get final results including schedule.
    """
    try:
        context = get_context()
        
        decisions = context.get_all_decisions()
        tasks = context.get_schedule_tasks()
        budget = context.get_budget_status()
        
        # Format schedule for Gantt chart
        schedule = []
        for t in tasks:
            candidate = context.get_candidate_by_id(t['project_id'])
            schedule.append({
                "project_id": t['project_id'],
                "title": t.get('title', candidate['title'] if candidate else ''),
                "start_week": t['start_week'],
                "end_week": t['end_week'],
                "crew_type": t['crew_type'],
                "crew_size": t['crew_size'],
                "status": t['status']
            })
        
        # Summary stats
        approved = [d for d in decisions if d['final_decision'] == 'APPROVE']
        rejected = [d for d in decisions if d['final_decision'] == 'REJECT']
        scheduled = [t for t in tasks if t['status'] == 'SCHEDULED']
        blocked = [t for t in tasks if t['status'] == 'BLOCKED']
        
        return jsonify({
            "success": True,
            "summary": {
                "total_projects": len(decisions),
                "approved": len(approved),
                "rejected": len(rejected),
                "scheduled": len(scheduled),
                "blocked": len(blocked),
                "budget_allocated": budget['allocated'],
                "budget_remaining": budget['remaining']
            },
            "schedule": schedule,
            "decisions": [
                {
                    "project_id": d['project_id'],
                    "title": d['title'],
                    "final_decision": d['final_decision'],
                    "estimated_cost": d['estimated_cost'],
                    "human_override": bool(d.get('human_override'))
                }
                for d in decisions
            ]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/run-pipeline', methods=['POST'])
def run_full_pipeline_endpoint():
    """
    Run the complete pipeline (stages 1 and 2).
    
    Returns status and pending approvals if any.
    """
    try:
        data = request.get_json() or {}
        budget = float(data.get('budget', 75_000_000))
        
        # Initialize
        init_database()
        seed_sample_data()
        clear_agent_outputs()
        context = reset_context(budget)
        
        # Run stages 1 and 2
        formation_result = asyncio.run(run_formation_stage(context, verbose=False))
        governance_result = asyncio.run(run_governance_stage(context, verbose=False))
        
        # Get pending approvals
        approvals = get_pending_approvals(context)
        
        return jsonify({
            "success": True,
            "formation": {
                "candidates_formed": formation_result['candidates_formed'],
                "total_cost": formation_result['total_cost']
            },
            "governance": {
                "total_decisions": governance_result['total_decisions'],
                "auto_approved": governance_result['auto_approved'],
                "auto_rejected": governance_result['auto_rejected'],
                "pending_human_approval": governance_result['pending_human_approval']
            },
            "pending_approvals": approvals['pending'],
            "auto_approved": approvals['auto_approved'],
            "auto_rejected": approvals['auto_rejected'],
            "budget": approvals['budget'],
            "requires_approval": approvals['requires_approval']
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    print("Starting Municipal HITL API Server...")
    print("API available at http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
