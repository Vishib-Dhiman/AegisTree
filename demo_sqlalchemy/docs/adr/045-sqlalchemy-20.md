# ADR-045: SQLAlchemy 2.0 explicit session queries

- Status: Accepted
- Date: 2026-01-20
- Supersedes: ADR-010
- Tags: database, sql, sqlalchemy, postgres, session_execute

## Decision
Production queries must use session.execute(select(...)) within an explicit context block.
Calling engine.execute() is removed in SQLAlchemy 2.0 and strictly forbidden.

## Required
- session.execute
- select

## Forbidden
- engine.execute
