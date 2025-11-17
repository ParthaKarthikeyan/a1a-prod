import React, { useState } from 'react';
import './FileTabs.css';
import FileTable from './FileTable';
import AudioPlayer from './AudioPlayer';

function FileTabs({ pendingFiles, processedFiles, formattedTranscripts, rawTranscripts, apiUrl, connectionString, containerName }) {
  const [activeTab, setActiveTab] = useState(0);

  const tabs = [
    { id: 0, label: '📁 Pending Files', data: pendingFiles, count: pendingFiles.length },
    { id: 1, label: '✅ Processed Files', data: processedFiles, count: processedFiles.length },
    { id: 2, label: '📝 Transcripts', data: { formatted: formattedTranscripts, raw: rawTranscripts }, count: formattedTranscripts.length + rawTranscripts.length },
    { id: 3, label: '🎧 Audio Player', data: null, count: 0 }
  ];

  const formatFileSize = (bytes) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
  };

  return (
    <div className="file-tabs-container">
      <div className="tabs-header">
        {tabs.map(tab => (
          <button
            key={tab.id}
            className={`tab-button ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label} ({tab.count})
          </button>
        ))}
      </div>

      <div className="tabs-content">
        {activeTab === 0 && (
          <div className="tab-panel">
            <h3>Pending Audio Files</h3>
            {pendingFiles.length > 0 ? (
              <>
                <FileTable
                  files={pendingFiles.map(f => ({
                    name: f.name,
                    size: formatFileSize(f.size || 0),
                    modified: f.last_modified ? new Date(f.last_modified).toLocaleString() : 'N/A'
                  }))}
                  columns={['File Name', 'Size', 'Last Modified']}
                />
                {pendingFiles.length >= 100 && (
                  <p className="table-note">Showing first 100 of {pendingFiles.length} files</p>
                )}
              </>
            ) : (
              <div className="empty-state">✅ No pending files! All files have been processed.</div>
            )}
          </div>
        )}

        {activeTab === 1 && (
          <div className="tab-panel">
            <h3>Processed Files</h3>
            {processedFiles.length > 0 ? (
              <>
                <FileTable
                  files={processedFiles.map(f => ({
                    name: f.name,
                    size: formatFileSize(f.size || 0),
                    modified: f.processed_at ? new Date(f.processed_at).toLocaleString() : 'N/A'
                  }))}
                  columns={['File Name', 'Size', 'Processed At']}
                />
                <p className="table-note">Showing {processedFiles.length} most recently processed files</p>
              </>
            ) : (
              <div className="empty-state">No processed files yet</div>
            )}
          </div>
        )}

        {activeTab === 2 && (
          <div className="tab-panel">
            <h3>Transcripts</h3>
            <div className="transcripts-grid">
              <div className="transcript-column">
                <h4>Formatted Transcripts</h4>
                {formattedTranscripts.length > 0 ? (
                  <>
                    <FileTable
                      files={formattedTranscripts.map(f => ({
                        name: f.name,
                        size: formatFileSize(f.size || 0),
                        modified: f.created ? new Date(f.created).toLocaleString() : 'N/A'
                      }))}
                      columns={['File Name', 'Size', 'Created']}
                    />
                    <p className="table-note">Showing {formattedTranscripts.length} formatted transcripts</p>
                  </>
                ) : (
                  <div className="empty-state">No formatted transcripts yet</div>
                )}
              </div>
              <div className="transcript-column">
                <h4>Raw Transcripts (JSON)</h4>
                {rawTranscripts.length > 0 ? (
                  <>
                    <FileTable
                      files={rawTranscripts.map(f => ({
                        name: f.name,
                        size: formatFileSize(f.size || 0),
                        modified: f.created ? new Date(f.created).toLocaleString() : 'N/A'
                      }))}
                      columns={['File Name', 'Size', 'Created']}
                    />
                    <p className="table-note">Showing {rawTranscripts.length} raw transcripts</p>
                  </>
                ) : (
                  <div className="empty-state">No raw transcripts yet</div>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 3 && (
          <div className="tab-panel audio-player-tab">
            <AudioPlayer 
              apiUrl={apiUrl}
              connectionString={connectionString}
              containerName={containerName}
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default FileTabs;

