"""Shared contracts between backend and ai-service.

This package holds only data (DTOs), interfaces (Protocols), and an
exception taxonomy - never business logic and never a concrete
implementation. Both `backend` and `ai-service` depend on `shared`;
`shared` depends on neither, so the direction of every import in this
repository stays: backend -> ai-service -> shared, backend -> shared.

See docs/ARCHITECTURE.md's "AI Service Extraction" section for the full
rationale and the dependency diagram.
"""
