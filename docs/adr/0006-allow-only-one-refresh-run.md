# Allow only one Refresh Run

Paper Monitor will allow only one Refresh Run per Windows user across Task Scheduler, the Tray Host, and the visible dashboard. A later request reuses the active run status instead of queuing or starting more network work, and only the process that owns the run may persist its final outcome or deliver notifications.
