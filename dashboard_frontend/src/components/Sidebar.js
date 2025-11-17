import React from 'react';
import './Sidebar.css';

function Sidebar({
  connectionString,
  setConnectionString,
  containerName,
  setContainerName,
  autoRefresh,
  setAutoRefresh,
  refreshInterval,
  setRefreshInterval,
  onSave,
  isConfigured
}) {
  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h2>⚙️ Configuration</h2>
      </div>

      <div className="sidebar-section">
        <label>
          Blob Connection String
          <input
            type="password"
            value={connectionString}
            onChange={(e) => setConnectionString(e.target.value)}
            placeholder="Enter connection string"
            className="sidebar-input"
          />
        </label>
      </div>

      <div className="sidebar-section">
        <label>
          Container Name
          <input
            type="text"
            value={containerName}
            onChange={(e) => setContainerName(e.target.value)}
            placeholder="audiofiles"
            className="sidebar-input"
          />
        </label>
      </div>

      <div className="sidebar-section">
        <h3>Refresh Settings</h3>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
          />
          Auto Refresh
        </label>
        {autoRefresh && (
          <label>
            Refresh Interval (seconds)
            <input
              type="number"
              min="5"
              max="300"
              step="5"
              value={refreshInterval}
              onChange={(e) => setRefreshInterval(parseInt(e.target.value))}
              className="sidebar-input"
            />
          </label>
        )}
      </div>

      <div className="sidebar-section">
        <button onClick={onSave} className="save-button">
          💾 Save Configuration
        </button>
        {isConfigured && (
          <div className="status-badge success">
            ✓ Configured
          </div>
        )}
      </div>

      <div className="sidebar-footer">
        <p>Transcription Dashboard v1.0</p>
      </div>
    </div>
  );
}

export default Sidebar;

