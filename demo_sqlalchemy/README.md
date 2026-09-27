# Northwind Database Audit Service

Service for querying transactional audit logs.
The current standard enforces SQLAlchemy 2.0 explicit session queries (ADR-045).
Direct engine.execute() calls (ADR-010) are removed and strictly forbidden.
