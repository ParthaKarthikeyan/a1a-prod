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
  const [error, setError] = useState(null);

  const fetchData = async () => {
    // Don't fetch if connection string is not configured
    if (!connectionString || connectionString.trim() === '') {
      setLoading(false);
      setError('Please configure your blob connection string in the sidebar');
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const requestData = {
        connection_string: connectionString,
        container_name: containerName
      };

      // Fetch all data in parallel
      const [statsRes, pendingRes, processedRes, formattedRes, rawRes, activityRes] = await Promise.all([
        axios.post(`${apiUrl}/api/statistics`, requestData),
        axios.post(`${apiUrl}/api/files/pending`, { ...requestData, limit: 100 }),
        axios.post(`${apiUrl}/api/files/processed`, { ...requestData, limit: 500 }),
        axios.post(`${apiUrl}/api/files/formatted`, { ...requestData, limit: 100 }),
        axios.post(`${apiUrl}/api/files/raw`, { ...requestData, limit: 100 }),
        axios.post(`${apiUrl}/api/recent-activity`, { ...requestData, limit: 10 })
      ]);

      setStatistics(statsRes.data);
      setPendingFiles(pendingRes.data.files || []);
      setProcessedFiles(processedRes.data.files || []);
      setFormattedTranscripts(formattedRes.data.files || []);
      setRawTranscripts(rawRes.data.files || []);
      setRecentActivity(activityRes.data.activity || []);
      setLoading(false);
    } catch (err) {
      console.error('Error fetching data:', err);
      const errorMessage = err.response?.data?.error || err.message || 'Failed to fetch data';
      setError(errorMessage);
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();

    if (autoRefresh && connectionString && connectionString.trim() !== '') {
      const interval = setInterval(fetchData, refreshInterval * 1000);
      return () => clearInterval(interval);
    }
  }, [connectionString, containerName, autoRefresh, refreshInterval, apiUrl]);

  if (loading && !statistics) {
    return (
      <div className="dashboard-loading">
        <div className="spinner"></div>
        <p>Loading dashboard data...</p>
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
        <div className="last-updated">
          Last updated: {new Date().toLocaleString()}
        </div>
      </div>

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

