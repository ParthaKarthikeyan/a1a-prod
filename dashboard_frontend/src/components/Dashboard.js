import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './Dashboard.css';
import StatisticsCards from './StatisticsCards';
import ProgressBar from './ProgressBar';
import FileTabs from './FileTabs';
import RecentActivity from './RecentActivity';

function Dashboard({ apiUrl, connectionString, containerName, autoRefresh, refreshInterval }) {
  const [statistics, setStatistics] = useState(null);
  const [pendingFiles, setPendingFiles] = useState([]);
  const [processedFiles, setProcessedFiles] = useState([]);
  const [formattedTranscripts, setFormattedTranscripts] = useState([]);
  const [rawTranscripts, setRawTranscripts] = useState([]);
  const [recentActivity, setRecentActivity] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filesLoading, setFilesLoading] = useState(false); // Start as false, set to true when loading
  const [error, setError] = useState(null);
  const [processing, setProcessing] = useState(false);
  const [processingMessage, setProcessingMessage] = useState(null);
  const [processingStatus, setProcessingStatus] = useState(null);
  const [voicegainStats, setVoicegainStats] = useState(null);

  const fetchData = async () => {
    // Don't fetch if connection string is not configured
    if (!connectionString || connectionString.trim() === '') {
      setLoading(false);
      setFilesLoading(false);
      setError('Please configure your blob connection string in the sidebar');
      return;
    }

    try {
      // Only set loading on initial load, not on auto-refresh
      if (!statistics) {
        setLoading(true);
      }
      setError(null);

      const requestData = {
        connection_string: connectionString,
        container_name: containerName
      };

      // Fetch only recent activity first (fastest) - show UI immediately
      try {
        const activityRes = await axios.post(`${apiUrl}/api/recent-activity`, { ...requestData, limit: 10 }, { timeout: 30000 });
        setRecentActivity(activityRes.data.activity || []);
      } catch (e) {
        console.log('Activity fetch failed, continuing...');
      }

      // Fetch statistics (can be slow with many files)
      const statsRes = await axios.post(`${apiUrl}/api/statistics`, requestData, { timeout: 120000 });
      setStatistics(statsRes.data);
      setLoading(false); // Show dashboard immediately with stats

      // Skip file list loading by default - too slow with 145K files
      // Files will be loaded on-demand when user clicks a tab
      setFilesLoading(false);
      
    } catch (err) {
      console.error('Error fetching data:', err);
      let errorMessage = 'Failed to fetch data';
      if (err.code === 'ECONNABORTED' || err.message?.includes('timeout')) {
        errorMessage = 'Request timed out. The container may have many files. Please try again.';
      } else if (err.code === 'ECONNREFUSED' || err.message?.includes('Network Error')) {
        errorMessage = 'Cannot connect to backend API. Please ensure the backend server is running on port 5001.';
      } else if (err.response?.data?.error) {
        errorMessage = err.response.data.error;
      } else if (err.message) {
        errorMessage = err.message;
      }
      setError(errorMessage);
      setLoading(false);
      setFilesLoading(false);
    }
  };
  
  // Load files on-demand when tab is clicked
  const loadFilesForTab = async (tabId) => {
    if (filesLoading) return;
    
    const requestData = {
      connection_string: connectionString,
      container_name: containerName,
      limit: 20
    };
    
    setFilesLoading(true);
    try {
      if (tabId === 0 && pendingFiles.length === 0) {
        const res = await axios.post(`${apiUrl}/api/files/pending`, requestData, { timeout: 60000 });
        setPendingFiles(res.data.files || []);
      } else if (tabId === 1 && processedFiles.length === 0) {
        const res = await axios.post(`${apiUrl}/api/files/processed`, requestData, { timeout: 60000 });
        setProcessedFiles(res.data.files || []);
      } else if (tabId === 2 && formattedTranscripts.length === 0) {
        const [formattedRes, rawRes] = await Promise.all([
          axios.post(`${apiUrl}/api/files/formatted`, requestData, { timeout: 60000 }),
          axios.post(`${apiUrl}/api/files/raw`, requestData, { timeout: 60000 })
        ]);
        setFormattedTranscripts(formattedRes.data.files || []);
        setRawTranscripts(rawRes.data.files || []);
      }
    } catch (err) {
      console.error('Error loading files:', err);
    }
    setFilesLoading(false);
  };

  const startProcessing = async () => {
    try {
      setProcessing(true);
      setProcessingMessage('Starting transcription processing...');
      setError(null);

      const response = await axios.post(`${apiUrl}/api/process/start`, {
        connection_string: connectionString,
        container_name: containerName
      }, { timeout: 120000 }); // 2 minutes

      setProcessingMessage('Processing started! Monitoring progress...');
      
      // Start polling for status
      pollProcessingStatus();
    } catch (err) {
      console.error('Error starting processing:', err);
      setError(err.response?.data?.error || err.message || 'Failed to start processing');
      setProcessingMessage(null);
    } finally {
      setProcessing(false);
    }
  };
  
  // Poll processing status and VoiceGain stats
  const pollProcessingStatus = async () => {
    const poll = async () => {
      try {
        // Get processing status
        const res = await axios.get(`${apiUrl}/api/process/status`, { timeout: 5000 });
        setProcessingStatus(res.data);
        
        // Get VoiceGain stats
        try {
          const vgRes = await axios.get(`${apiUrl}/api/voicegain/stats`, { timeout: 5000 });
          setVoicegainStats(vgRes.data);
        } catch (e) {
          console.log('VoiceGain stats not available');
        }
        
        if (res.data.is_running) {
          // Keep polling while running - continue even if there are errors
          setTimeout(poll, 2000);
        } else {
          // Processing finished - but keep checking in case it restarts
          if (processingStatus && processingStatus.is_running) {
            // Only clear message if it was actually running before
            setProcessingMessage(null);
            fetchData(); // Refresh stats
          }
          // Continue polling every 5 seconds to catch new starts
          setTimeout(poll, 5000);
        }
      } catch (err) {
        console.error('Error polling status:', err);
        // Continue polling even on error
        setTimeout(poll, 5000);
      }
    };
    poll();
  };
  
  // Fetch VoiceGain stats periodically
  useEffect(() => {
    const fetchVoicegainStats = async () => {
      try {
        const res = await axios.get(`${apiUrl}/api/voicegain/stats`, { timeout: 5000 });
        setVoicegainStats(res.data);
      } catch (e) {
        // Silently fail - stats may not be available
      }
    };
    
    fetchVoicegainStats();
    const interval = setInterval(fetchVoicegainStats, 10000); // Every 10 seconds
    return () => clearInterval(interval);
  }, [apiUrl]);

  useEffect(() => {
    fetchData();

    if (autoRefresh && connectionString && connectionString.trim() !== '') {
      // Use longer interval for statistics to avoid resetting counters
      // Statistics update less frequently, but processing status polls every 2 seconds
      const interval = setInterval(() => {
        // Only refresh statistics, don't reset loading state
        fetchData();
      }, refreshInterval * 1000);
      return () => clearInterval(interval);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionString, containerName, autoRefresh, refreshInterval, apiUrl]);
  
  // Start polling for processing status on mount - check periodically if processing is running
  useEffect(() => {
    let isMounted = true;
    let pollTimeout = null;
    
    const checkAndPoll = async () => {
      if (!isMounted) return;
      
      try {
        const res = await axios.get(`${apiUrl}/api/process/status`, { timeout: 5000 });
        if (res.data.is_running) {
          // Processing is running, start active polling if not already
          if (!processingStatus?.is_running) {
            pollProcessingStatus();
          }
        }
      } catch (e) {
        // Silently fail
      }
      
      // Check again in 5 seconds
      if (isMounted) {
        pollTimeout = setTimeout(checkAndPoll, 5000);
      }
    };
    
    // Start checking
    checkAndPoll();
    
    return () => {
      isMounted = false;
      if (pollTimeout) clearTimeout(pollTimeout);
    };
  }, [apiUrl]);

  if (loading && !statistics) {
    return (
      <div className="dashboard-loading">
        <div className="spinner"></div>
        <p>Loading dashboard data...</p>
        <p style={{ fontSize: '12px', color: '#666', marginTop: '10px' }}>
          This may take a while if you have many files. Please wait...
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="dashboard-error">
        <h2>⚠️ Error</h2>
        <p>{error}</p>
        <button onClick={fetchData} className="retry-button">
          🔄 Retry
        </button>
      </div>
    );
  }

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <h1>🎙️ Transcription Processing Dashboard</h1>
        <div className="dashboard-header-right">
          <div className="last-updated">
            Last updated: {new Date().toLocaleString()}
          </div>
          {statistics && statistics.pending_files > 0 && (
            <button 
              onClick={startProcessing} 
              disabled={processing}
              className="start-processing-button"
              title="Start processing pending files"
            >
              {processing ? '⏳ Starting...' : '▶️ Start Processing'}
            </button>
          )}
        </div>
      </div>

      {(processingMessage || (processingStatus && processingStatus.is_running)) && (
        <div className="processing-panel">
          <div className="processing-header">
            <span className="processing-indicator">⚡</span>
            <strong>Processing Status</strong>
            {processingStatus?.is_running && <span className="pulse-badge">RUNNING</span>}
          </div>
          {processingStatus && (
            <div className="processing-details">
              <div className="processing-stats">
                {processingStatus.files_submitted > 0 && (
                  <span>📊 Progress: {processingStatus.current_progress || 0} / {processingStatus.files_submitted}</span>
                )}
                <span>✅ Completed: {processingStatus.files_completed}</span>
                <span>❌ Failed: {processingStatus.files_failed}</span>
              </div>
              {processingStatus.current_file && (
                <div className="current-file">📄 {processingStatus.current_file}</div>
              )}
              {processingStatus.log_messages && processingStatus.log_messages.length > 0 && (
                <div className="processing-log">
                  {processingStatus.log_messages.slice(-5).map((msg, idx) => (
                    <div key={idx} className="log-line">{msg}</div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* VoiceGain Status Panel */}
      {voicegainStats && (voicegainStats.total_submitted > 0 || voicegainStats.total_in_progress > 0) && (
        <div className="voicegain-panel">
          <div className="voicegain-header">
            <span className="vg-icon">🎤</span>
            <strong>VoiceGain API Status</strong>
            {voicegainStats.total_in_progress > 0 && (
              <span className="vg-active-badge">{voicegainStats.total_in_progress} In Progress</span>
            )}
          </div>
          <div className="voicegain-stats">
            <div className="vg-stat">
              <span className="vg-stat-value">{voicegainStats.total_submitted}</span>
              <span className="vg-stat-label">Submitted</span>
            </div>
            <div className="vg-stat success">
              <span className="vg-stat-value">{voicegainStats.total_completed}</span>
              <span className="vg-stat-label">Completed</span>
            </div>
            <div className="vg-stat danger">
              <span className="vg-stat-value">{voicegainStats.total_failed}</span>
              <span className="vg-stat-label">Failed</span>
            </div>
            <div className="vg-stat info">
              <span className="vg-stat-value">{voicegainStats.avg_duration_seconds}s</span>
              <span className="vg-stat-label">Avg Duration</span>
            </div>
          </div>
          {voicegainStats.recent_jobs && voicegainStats.recent_jobs.length > 0 && (
            <div className="voicegain-jobs">
              <div className="vg-jobs-header">Recent Jobs:</div>
              <div className="vg-jobs-list">
                {voicegainStats.recent_jobs.slice(0, 5).map((job, idx) => (
                  <div key={idx} className={`vg-job ${job.status}`}>
                    <span className="vg-job-file">{job.file_name?.substring(0, 40)}...</span>
                    <span className={`vg-job-status ${job.status}`}>
                      {job.status === 'completed' ? '✅' : job.status === 'failed' ? '❌' : job.status === 'processing' ? '⏳' : '📤'}
                      {job.status}
                    </span>
                    {job.duration_seconds && <span className="vg-job-duration">{job.duration_seconds}s</span>}
                    {job.last_phase && job.status === 'processing' && (
                      <span className="vg-job-phase">{job.last_phase}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          {voicegainStats.errors && voicegainStats.errors.length > 0 && (
            <div className="voicegain-errors">
              <div className="vg-errors-header">⚠️ Recent Errors:</div>
              {voicegainStats.errors.slice(-3).map((err, idx) => (
                <div key={idx} className="vg-error">
                  <span className="vg-error-file">{err.file_name?.substring(0, 30)}...</span>
                  <span className="vg-error-msg">{err.error?.substring(0, 50)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {statistics && (
        <>
          <StatisticsCards statistics={statistics} />
          <ProgressBar statistics={statistics} />
          
          <div className="dashboard-grid">
            <div className="dashboard-section">
              <h2>📈 Statistics</h2>
              <StatisticsTable statistics={statistics} />
            </div>
            <div className="dashboard-section">
              <h2>📋 Recent Activity</h2>
              <RecentActivity activity={recentActivity} />
            </div>
          </div>

          <FileTabs
            pendingFiles={pendingFiles}
            processedFiles={processedFiles}
            formattedTranscripts={formattedTranscripts}
            rawTranscripts={rawTranscripts}
            apiUrl={apiUrl}
            connectionString={connectionString}
            containerName={containerName}
            filesLoading={filesLoading}
            onTabChange={loadFilesForTab}
          />
        </>
      )}
    </div>
  );
}

function StatisticsTable({ statistics }) {
  const statsData = [
    { label: 'Total Audio Files', value: statistics.total_audio_files.toLocaleString() },
    { label: 'Processed Files', value: statistics.processed_files.toLocaleString() },
    { label: 'Pending Files', value: statistics.pending_files.toLocaleString() },
    { label: 'Formatted Transcripts', value: statistics.formatted_transcripts.toLocaleString() },
    { label: 'Raw Transcripts', value: statistics.raw_transcripts.toLocaleString() },
    { label: 'Success Rate', value: `${statistics.success_rate.toFixed(1)}%` }
  ];

  return (
    <table className="stats-table">
      <tbody>
        {statsData.map((stat, idx) => (
          <tr key={idx}>
            <td className="stat-label">{stat.label}</td>
            <td className="stat-value">{stat.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default Dashboard;

