# Municipal HITL System

A Human-in-the-Loop municipal project management system using OpenAI Agents SDK.

## Overview

This system demonstrates **agentic behavior** with a human approval gateway:

1. **Formation Agent** - Converts citizen issues into costed project proposals
2. **Governance Agent** - Makes policy decisions 
3. **Human Approval Gateway** - Pauses for human review on high-cost/risk items
4. **Scheduling Agent** - Allocates crews and schedules approved projects

## Key Features

- **PolicyDecision Model** - Separates decision from authorization
- **$10M Escalation Threshold** - Projects > $10M require human approval
- **Confidence Thresholds** - Low confidence triggers human review
- **Legal Mandate Protection** - Cannot auto-reject mandated projects
- **React UI** - Visual approval workflow

## Setup

### Backend

```bash
cd municipal_hitl

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# or: source venv/bin/activate  # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Set your OpenAI API key
# Edit api.env and add your key

# Run Flask server
python app.py
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start React dev server
npm start
```

The app will be available at http://localhost:3000

## Architecture

```
municipal_hitl/
├── app.py                    # Flask API
├── requirements.txt
├── api.env                   # OpenAI API key
├── database/
│   └── municipal.db          # SQLite database (auto-created)
├── municipal_agents/
│   ├── models.py             # Pydantic models (PolicyDecision, etc.)
│   ├── database.py           # Schema and seeding
│   ├── context.py            # Shared context
│   ├── formation_agent.py    # Agent 1
│   ├── governance_agent.py   # Agent 2 (AGENTIC with HITL)
│   ├── scheduling_agent.py   # Agent 3
│   └── pipeline.py           # Pipeline orchestration
└── frontend/
    ├── public/
    └── src/
        ├── App.js            # Main React component
        └── index.css         # Styles
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/init` | POST | Initialize database |
| `/api/run-pipeline` | POST | Run formation + governance |
| `/api/pending-approvals` | GET | Get items needing approval |
| `/api/submit-approvals` | POST | Submit human decisions |
| `/api/run-scheduling` | POST | Run scheduling agent |
| `/api/results` | GET | Get final results |

## HITL Escalation Rules

The Governance Agent escalates to human review when:

1. **Cost > $10M** - Major budget impact
2. **Legal Mandate + Rejection** - Cannot auto-reject mandated items
3. **Confidence < 65%** - Agent is uncertain
4. **High Risk + Large Population** - Risk ≥ 6 AND population ≥ 200K

## Demo Workflow

1. Enter quarterly budget ($75M default)
2. Click "Run Pipeline"
3. Formation Agent creates projects
4. Governance Agent evaluates each project
5. **HITL Pause** - Review pending approvals
6. Override or confirm agent recommendations
7. Submit decisions
8. Scheduling Agent creates Gantt chart
9. View final results
