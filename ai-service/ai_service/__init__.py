"""ai-service: LLM providers, client, agent engine, structured output,
prompt registry, and observability.

Extracted from backend/app/ai (Pre-Phase 5 AI Service Extraction) as a
standalone, independently-installable package so that a future move to a
real standalone deployment (HTTP/gRPC/queue transport) is a transport
swap, not a business-logic rewrite. See docs/ARCHITECTURE.md's "AI
Service Extraction" section for the dependency diagram and every disclosed
scoping decision.

This package depends only on `shared` (contracts/interfaces) and vendor
SDKs - never on `app.core` or `app.modules`.
"""
