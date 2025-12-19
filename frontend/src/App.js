import React, { useState } from 'react';
import axios from 'axios';

function App() {
  const [budget, setBudget] = useState('75000000');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [stage, setStage] = useState('input'); // input, approval, scheduling, complete
  const [data, setData] = useState(null);
  const [decisions, setDecisions] = useState({});

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  };

  // Run Formation + Governance stages
  const runPipeline = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await axios.post('/api/run-pipeline', {
        budget: parseFloat(budget.replace(/[,$]/g, ''))
      });

      if (response.data.success) {
        setData(response.data);
        
        // Initialize decisions for pending items
        const initialDecisions = {};
        response.data.pending_approvals.forEach(p => {
          initialDecisions[p.project_id] = p.agent_decision;
        });
        setDecisions(initialDecisions);

        if (response.data.requires_approval) {
          setStage('approval');
        } else {
          // No approvals needed, run scheduling
          await runScheduling();
        }
      } else {
        setError(response.data.error || 'Failed to run pipeline');
      }
    } catch (err) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
  };

  // Submit human decisions
  const submitApprovals = async () => {
    setLoading(true);
    setError(null);

    try {
      const decisionList = Object.entries(decisions).map(([project_id, decision]) => ({
        project_id,
        decision,
        reason: 'Human review'
      }));

      const response = await axios.post('/api/submit-approvals', {
        decisions: decisionList
      });

      if (response.data.success) {
        await runScheduling();
      } else {
        setError(response.data.error);
      }
    } catch (err) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
  };

  // Run scheduling stage
  const runScheduling = async () => {
    setLoading(true);
    setStage('scheduling');

    try {
      await axios.post('/api/run-scheduling');
      
      // Get final results
      const resultsResponse = await axios.get('/api/results');
      if (resultsResponse.data.success) {
        setData(prev => ({
          ...prev,
          results: resultsResponse.data
        }));
        setStage('complete');
      }
    } catch (err) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
  };

  // Toggle decision for a project
  const toggleDecision = (projectId) => {
    setDecisions(prev => ({
      ...prev,
      [projectId]: prev[projectId] === 'APPROVE' ? 'REJECT' : 'APPROVE'
    }));
  };

  // Render Gantt chart
  const renderGantt = (schedule) => {
    const weeks = Array.from({ length: 13 }, (_, i) => i + 1);
    const scheduled = schedule.filter(t => t.status === 'SCHEDULED');

    return (
      <div className="gantt-container">
        <div className="gantt-chart">
          <div className="gantt-header">
            <div className="gantt-label-col">Project</div>
            <div className="gantt-weeks">
              {weeks.map(w => (
                <div key={w} className="gantt-week">W{w}</div>
              ))}
            </div>
          </div>
          {scheduled.map(task => (
            <div key={task.project_id} className="gantt-row">
              <div className="gantt-row-label" title={task.title}>
                {task.title.substring(0, 25)}...
              </div>
              <div className="gantt-row-bars">
                <div
                  className={`gantt-bar ${task.crew_type}`}
                  style={{
                    left: `${((task.start_week - 1) / 13) * 100}%`,
                    width: `${((task.end_week - task.start_week + 1) / 13) * 100}%`
                  }}
                >
                  W{task.start_week}-{task.end_week}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="app">
      <header className="header">
        <h1>🏛️ Municipal HITL System</h1>
        <p>Human-in-the-Loop Project Management</p>
      </header>

      <main className="main">
        {/* Progress Steps */}
        <div className="progress-steps">
          <div className={`step ${stage === 'input' ? 'active' : (stage !== 'input' ? 'complete' : '')}`}>
            <div className="step-number">1</div>
            <div className="step-label">Budget Input</div>
          </div>
          <div className={`step ${stage === 'approval' ? 'active' : (stage === 'scheduling' || stage === 'complete' ? 'complete' : '')}`}>
            <div className="step-number">2</div>
            <div className="step-label">Human Approval</div>
          </div>
          <div className={`step ${stage === 'scheduling' ? 'active' : (stage === 'complete' ? 'complete' : '')}`}>
            <div className="step-number">3</div>
            <div className="step-label">Scheduling</div>
          </div>
          <div className={`step ${stage === 'complete' ? 'complete' : ''}`}>
            <div className="step-number">4</div>
            <div className="step-label">Complete</div>
          </div>
        </div>

        {error && <div className="error">❌ {error}</div>}

        {/* Stage 1: Budget Input */}
        {stage === 'input' && (
          <div className="card">
            <h2>Quarterly Budget Allocation</h2>
            <p style={{ marginBottom: '1rem', color: '#666' }}>
              Enter the quarterly budget. The system will form projects, make decisions, 
              and pause for your approval on high-cost items.
            </p>
            <div className="budget-form">
              <div className="form-group">
                <label>Budget (USD)</label>
                <input
                  type="text"
                  value={budget}
                  onChange={(e) => setBudget(e.target.value)}
                  placeholder="75,000,000"
                  disabled={loading}
                />
              </div>
              <button 
                className="btn btn-primary" 
                onClick={runPipeline}
                disabled={loading}
              >
                {loading ? 'Running Agents...' : 'Run Pipeline'}
              </button>
            </div>
          </div>
        )}

        {/* Loading State */}
        {loading && (
          <div className="loading">
            <div className="spinner"></div>
            <span>
              {stage === 'input' && 'Formation & Governance Agents working...'}
              {stage === 'scheduling' && 'Scheduling Agent working...'}
              {stage === 'approval' && 'Submitting decisions...'}
            </span>
          </div>
        )}

        {/* Stage 2: Human Approval */}
        {stage === 'approval' && data && !loading && (
          <>
            <div className="card">
              <h2>⏳ Decisions Requiring Your Approval</h2>
              <p style={{ marginBottom: '1rem', color: '#666' }}>
                The Governance Agent has made recommendations, but these projects exceed 
                the $10M threshold or have other escalation triggers. Review and confirm.
              </p>

              <div className="stats-grid">
                <div className="stat-item">
                  <div className="stat-value">{data.pending_approvals.length}</div>
                  <div className="stat-label">Pending Review</div>
                </div>
                <div className="stat-item">
                  <div className="stat-value">{data.auto_approved.length}</div>
                  <div className="stat-label">Auto-Approved</div>
                </div>
                <div className="stat-item">
                  <div className="stat-value">{data.auto_rejected.length}</div>
                  <div className="stat-label">Auto-Rejected</div>
                </div>
                <div className="stat-item">
                  <div className="stat-value">{formatCurrency(data.budget.remaining)}</div>
                  <div className="stat-label">Budget Remaining</div>
                </div>
              </div>

              <div className="approval-list">
                {data.pending_approvals.map(project => (
                  <div key={project.project_id} className="approval-card pending">
                    <div className="approval-card-header">
                      <div>
                        <div className="approval-card-title">{project.title}</div>
                        <div className="approval-card-meta">
                          <span>📁 {project.category}</span>
                          <span>⚠️ Risk: {project.risk_score}/8</span>
                          <span>👥 {project.population_affected.toLocaleString()} affected</span>
                          {project.legal_mandate && <span>⚖️ Legal Mandate</span>}
                        </div>
                      </div>
                      <div className="approval-card-cost">{formatCurrency(project.estimated_cost)}</div>
                    </div>

                    <div className="approval-card-rationale">
                      <strong>Agent Recommendation: </strong>
                      <span className={`agent-decision ${project.agent_decision.toLowerCase()}`}>
                        {project.agent_decision === 'APPROVE' ? '✅' : '❌'} {project.agent_decision}
                      </span>
                      <span style={{ marginLeft: '0.5rem' }}>
                        (Confidence: {project.confidence}%)
                      </span>
                      <div className="confidence-bar">
                        <div 
                          className={`confidence-fill ${project.confidence >= 80 ? 'high' : project.confidence >= 50 ? 'medium' : 'low'}`}
                          style={{ width: `${project.confidence}%` }}
                        />
                      </div>
                      <p style={{ marginTop: '0.5rem' }}>{project.rationale}</p>
                      <div className="reason-codes">
                        {JSON.parse(project.reason_codes || '[]').map((code, i) => (
                          <span key={i} className="reason-code">{code}</span>
                        ))}
                      </div>
                    </div>

                    <div className="approval-card-actions">
                      <button
                        className={`btn btn-small ${decisions[project.project_id] === 'REJECT' ? 'btn-danger' : ''}`}
                        onClick={() => setDecisions(prev => ({ ...prev, [project.project_id]: 'REJECT' }))}
                        style={decisions[project.project_id] === 'REJECT' ? {} : { background: '#e0e0e0', color: '#666' }}
                      >
                        ❌ Reject
                      </button>
                      <button
                        className={`btn btn-small ${decisions[project.project_id] === 'APPROVE' ? 'btn-success' : ''}`}
                        onClick={() => setDecisions(prev => ({ ...prev, [project.project_id]: 'APPROVE' }))}
                        style={decisions[project.project_id] === 'APPROVE' ? {} : { background: '#e0e0e0', color: '#666' }}
                      >
                        ✅ Approve
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              <div style={{ marginTop: '1.5rem', textAlign: 'right' }}>
                <button className="btn btn-primary" onClick={submitApprovals}>
                  Submit Decisions & Continue →
                </button>
              </div>
            </div>

            {/* Auto-Approved Summary */}
            {data.auto_approved.length > 0 && (
              <div className="card summary-section">
                <h3>✅ Auto-Approved Projects</h3>
                <div className="summary-list">
                  {data.auto_approved.map(p => (
                    <div key={p.project_id} className="summary-item">
                      <span className="summary-item-title">{p.title}</span>
                      <span className="summary-item-cost">{formatCurrency(p.estimated_cost)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Auto-Rejected Summary */}
            {data.auto_rejected.length > 0 && (
              <div className="card summary-section">
                <h3>❌ Auto-Rejected Projects</h3>
                <div className="summary-list">
                  {data.auto_rejected.map(p => (
                    <div key={p.project_id} className="summary-item">
                      <span className="summary-item-title">{p.title}</span>
                      <span style={{ fontSize: '0.85rem', color: '#666' }}>{p.rationale}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {/* Stage 4: Complete */}
        {stage === 'complete' && data?.results && (
          <>
            <div className="card">
              <h2>✅ Pipeline Complete</h2>
              
              <div className="stats-grid">
                <div className="stat-item">
                  <div className="stat-value">{data.results.summary.total_projects}</div>
                  <div className="stat-label">Total Projects</div>
                </div>
                <div className="stat-item">
                  <div className="stat-value">{data.results.summary.approved}</div>
                  <div className="stat-label">Approved</div>
                </div>
                <div className="stat-item">
                  <div className="stat-value">{data.results.summary.scheduled}</div>
                  <div className="stat-label">Scheduled</div>
                </div>
                <div className="stat-item">
                  <div className="stat-value">{data.results.summary.blocked}</div>
                  <div className="stat-label">Blocked</div>
                </div>
                <div className="stat-item">
                  <div className="stat-value">{formatCurrency(data.results.summary.budget_allocated)}</div>
                  <div className="stat-label">Budget Allocated</div>
                </div>
                <div className="stat-item">
                  <div className="stat-value">{formatCurrency(data.results.summary.budget_remaining)}</div>
                  <div className="stat-label">Budget Remaining</div>
                </div>
              </div>
            </div>

            <div className="card">
              <h2>📊 Quarterly Schedule (Gantt Chart)</h2>
              {renderGantt(data.results.schedule)}
            </div>

            <div className="card">
              <h2>📋 Final Decisions</h2>
              <div className="summary-list">
                {data.results.decisions.map(d => (
                  <div key={d.project_id} className="summary-item">
                    <span className={`status-badge ${d.final_decision === 'APPROVE' ? 'status-approved' : 'status-rejected'}`}>
                      {d.final_decision}
                    </span>
                    <span className="summary-item-title" style={{ marginLeft: '1rem' }}>
                      {d.title}
                      {d.human_override && <span style={{ marginLeft: '0.5rem', fontSize: '0.75rem', color: '#4361ee' }}>(Human Override)</span>}
                    </span>
                    <span className="summary-item-cost">{formatCurrency(d.estimated_cost)}</span>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ textAlign: 'center', marginTop: '1.5rem' }}>
              <button 
                className="btn btn-primary" 
                onClick={() => { setStage('input'); setData(null); setDecisions({}); }}
              >
                Start New Quarter
              </button>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

export default App;
