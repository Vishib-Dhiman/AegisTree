# Database Architecture Standards

SQLAlchemy 2.0 enforces 2.0-style execution: session.execute(select(...)).
Direct calls to engine.execute() are removed in 2.0.
