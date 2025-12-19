# -*- coding: utf-8 -*-
"""
Database setup and seeding for Municipal HITL System

Simple SQLite database with issues, candidates, decisions, and schedule.
"""

import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "database" / "municipal.db"


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Initialize database schema"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Issues table - citizen complaints and problems
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT NOT NULL,
            severity INTEGER DEFAULT 3,
            population_affected INTEGER DEFAULT 0,
            legal_mandate INTEGER DEFAULT 0,
            status TEXT DEFAULT 'open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Project candidates - formed by Agent 1
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS project_candidates (
            project_id TEXT PRIMARY KEY,
            issue_id INTEGER,
            title TEXT NOT NULL,
            scope TEXT,
            category TEXT,
            estimated_cost REAL,
            estimated_weeks INTEGER,
            required_crew_type TEXT,
            crew_size INTEGER,
            risk_score REAL,
            feasibility_score REAL DEFAULT 1.0,
            population_affected INTEGER DEFAULT 0,
            legal_mandate INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (issue_id) REFERENCES issues(issue_id)
        )
    """)
    
    # Policy decisions - made by Agent 2
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS policy_decisions (
            decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            authorization TEXT NOT NULL,
            confidence INTEGER,
            reason_codes TEXT,
            rationale TEXT,
            human_override INTEGER DEFAULT 0,
            human_decision TEXT,
            human_reason TEXT,
            final_decision TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES project_candidates(project_id)
        )
    """)
    
    # Migration: Add briefing column if it doesn't exist (for existing DBs)
    cursor.execute("PRAGMA table_info(policy_decisions)")
    columns = [info[1] for info in cursor.fetchall()]
    if "briefing" not in columns:
        cursor.execute("ALTER TABLE policy_decisions ADD COLUMN briefing TEXT")
    
    # Schedule tasks - created by Agent 3
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schedule_tasks (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            start_week INTEGER,
            end_week INTEGER,
            crew_type TEXT,
            crew_size INTEGER,
            status TEXT DEFAULT 'SCHEDULED',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES project_candidates(project_id)
        )
    """)
    
    # Crew capacity - resource constraints
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crew_capacity (
            crew_type TEXT PRIMARY KEY,
            total_capacity INTEGER NOT NULL
        )
    """)
    
    # Audit log
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            agent_name TEXT,
            payload TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


def seed_sample_data():
    """Seed the database with realistic municipal issues"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Clear existing data
    cursor.execute("DELETE FROM schedule_tasks")
    cursor.execute("DELETE FROM policy_decisions")
    cursor.execute("DELETE FROM project_candidates")
    cursor.execute("DELETE FROM issues")
    cursor.execute("DELETE FROM crew_capacity")
    
    # Seed crew capacity
    crews = [
        ("water_crew", 15),
        ("electrical_crew", 12),
        ("road_crew", 20),
        ("general_construction", 25),
        ("emergency_response", 10),
    ]
    cursor.executemany(
        "INSERT INTO crew_capacity (crew_type, total_capacity) VALUES (?, ?)",
        crews
    )
    
    # Seed issues - mix of costs to trigger different escalation paths
    issues = [
        # High cost projects (> $10M) - will require human approval
        ("Major Water Pipeline Rupture - Downtown District", 
         "Critical infrastructure failure affecting water supply to 450,000 residents. Pipe is 60 years old and has multiple fracture points.",
         "water_infrastructure", 5, 450000, 1),
        
        ("Hospital Emergency Power System Upgrade",
         "Central Hospital backup generators failing safety inspections. Legal requirement to maintain 72-hour backup power.",
         "healthcare_facility", 5, 280000, 1),
        
        ("Urban Flood Management System",
         "Recurring flooding in Riverside district affecting 600,000 residents. Storm drains inadequate for climate change patterns.",
         "flood_control", 4, 600000, 0),
        
        # Medium cost projects ($5M - $10M) - agent can auto-decide with high confidence
        ("Bridge Structural Reinforcement - Highway 7",
         "Load-bearing capacity reduced to 80%. Heavy vehicles rerouted. Affects 50,000 daily commuters.",
         "transportation", 4, 50000, 0),
        
        ("School Electrical System Modernization",
         "Aging electrical systems in 12 schools. Fire safety concern flagged by inspectors.",
         "public_buildings", 4, 15000, 1),
        
        # Lower cost projects (< $5M) - agent can auto-approve/reject
        ("Pothole Repair Program - Zone A",
         "Accumulated road damage from winter. 847 reported potholes in residential areas.",
         "road_maintenance", 2, 80000, 0),
        
        ("Park Playground Equipment Replacement",
         "Safety inspection failed for 8 playground structures. Temporary closures in effect.",
         "parks_recreation", 2, 25000, 0),
        
        ("Street Lighting Upgrade - Industrial Zone",
         "LED conversion for 500 street lights. Energy savings and improved safety.",
         "electrical", 2, 120000, 0),
        
        ("Community Center HVAC Replacement",
         "20-year-old system failing. Building uncomfortable for 5,000 monthly visitors.",
         "public_buildings", 2, 5000, 0),
        
        ("Sidewalk Accessibility Improvements",
         "ADA compliance upgrades needed at 45 intersections. Legal mandate.",
         "accessibility", 3, 200000, 1),
    ]
    
    cursor.executemany("""
        INSERT INTO issues (title, description, category, severity, population_affected, legal_mandate)
        VALUES (?, ?, ?, ?, ?, ?)
    """, issues)
    
    conn.commit()
    conn.close()
    print(f"Seeded {len(issues)} sample issues")


def clear_agent_outputs():
    """Clear all agent-generated data (for re-runs)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM schedule_tasks")
    cursor.execute("DELETE FROM policy_decisions")
    cursor.execute("DELETE FROM project_candidates")
    conn.commit()
    conn.close()
    print("Cleared agent outputs")


if __name__ == "__main__":
    init_database()
    seed_sample_data()
