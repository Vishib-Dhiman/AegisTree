# ADR-032: Pydantic v2 serialization with model_dump

- Status: Accepted
- Date: 2025-11-15
- Supersedes: ADR-008
- Tags: pydantic, schema, serialize, dump, model_dump

## Decision
Production serialization must use model.model_dump().
The legacy Pydantic v1 method .dict() is deprecated and forbidden in production code.

## Required
- model_dump

## Forbidden
- .dict()
