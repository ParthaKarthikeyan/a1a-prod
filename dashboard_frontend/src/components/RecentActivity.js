import React from 'react';
import './RecentActivity.css';

function RecentActivity({ activity }) {
  if (!activity || activity.length === 0) {
    return <div className="no-activity">No recent activity</div>;
  }

  return (
    <div className="recent-activity">
      {activity.map((item, idx) => (
        <div key={idx} className="activity-item">
          <div className="activity-file">{item.file_name}</div>
          <div className="activity-time">{item.time_ago}</div>
        </div>
      ))}
    </div>
  );
}

export default RecentActivity;

