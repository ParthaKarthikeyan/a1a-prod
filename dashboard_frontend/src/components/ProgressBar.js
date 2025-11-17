import React from 'react';
import './ProgressBar.css';

function ProgressBar({ statistics }) {
  const progress = statistics.progress_percent || 0;

  return (
    <div className="progress-section">
      <h2>📊 Processing Progress</h2>
      <div className="progress-container">
        <div className="progress-bar">
          <div 
            className="progress-fill" 
            style={{ width: `${progress}%` }}
          ></div>
        </div>
        <div className="progress-text">
          Processed: {statistics.processed_files.toLocaleString()} / {statistics.total_audio_files.toLocaleString()} ({progress.toFixed(1)}%)
        </div>
      </div>
    </div>
  );
}

export default ProgressBar;

