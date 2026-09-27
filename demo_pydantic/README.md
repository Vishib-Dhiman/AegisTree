# Northwind Schema Registry

Microservice for data serialization and API payload schemas.
The current standard enforces Pydantic v2 model_dump() (ADR-032).
Legacy Pydantic v1 .dict() calls (ADR-008) are deprecated and forbidden.
