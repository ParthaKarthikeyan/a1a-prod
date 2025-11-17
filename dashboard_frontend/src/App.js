import React, { useState, useEffect } from 'react';
import './App.css';
import Dashboard from './components/Dashboard';
import Sidebar from './components/Sidebar';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:5001';

function App() {
  const [connectionString, setConnectionString] = useState('');
  const [containerName, setContainerName] = useState('audiofiles');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [refreshInterval, setRefreshInterval] = useState(30);
  const [isConfigured, setIsConfigured] = useState(false);

  useEffect(() => {
    // Load saved configuration from localStorage
    const savedConnStr = localStorage.getItem('blob_connection_string');
    const savedContainer = localStorage.getItem('container_name');
    const savedAutoRefresh = localStorage.getItem('auto_refresh');
    const savedInterval = localStorage.getItem('refresh_interval');

    if (savedConnStr) setConnectionString(savedConnStr);
    if (savedContainer) setContainerName(savedContainer);
    if (savedAutoRefresh !== null) setAutoRefresh(savedAutoRefresh === 'true');
    if (savedInterval) setRefreshInterval(parseInt(savedInterval));

    setIsConfigured(!!savedConnStr);
  }, []);

  const handleConfigSave = () => {
    localStorage.setItem('blob_connection_string', connectionString);
    localStorage.setItem('container_name', containerName);
    localStorage.setItem('auto_refresh', autoRefresh.toString());
    localStorage.setItem('refresh_interval', refreshInterval.toString());
    setIsConfigured(!!connectionString);
  };

  return (
    <div className="App">
      <Sidebar
        connectionString={connectionString}
        setConnectionString={setConnectionString}
        containerName={containerName}
        setContainerName={setContainerName}
        autoRefresh={autoRefresh}
        setAutoRefresh={setAutoRefresh}
        refreshInterval={refreshInterval}
        setRefreshInterval={setRefreshInterval}
        onSave={handleConfigSave}
        isConfigured={isConfigured}
      />
      <div className="main-content">
        {isConfigured ? (
          <Dashboard
            apiUrl={API_BASE_URL}
            connectionString={connectionString}
            containerName={containerName}
            autoRefresh={autoRefresh}
            refreshInterval={refreshInterval}
          />
        ) : (
          <div className="welcome-screen">
            <h1>🎙️ Transcription Processing Dashboard</h1>
            <p>Please configure your settings in the sidebar to get started.</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;

