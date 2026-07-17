# Use local SQLite as canonical state

Paper Monitor will keep articles, refresh runs, and future visibility and notification outcomes in one local SQLite database shared by scheduled and interactive executions. JSON, Markdown, or text files may be optional exports or diagnostic snapshots, but they are never authoritative; this prevents split state and permits atomic notification decisions without a resident process.
