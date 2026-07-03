# AI Dispatch OS — PRD

## Original Problem
Full trucking TMS "AI Dispatch OS" — a SaaS control tower for a USA trucking company. Manages every load through execution checkpoints from booked → assigned → pickup → transit → delivery → BOL/POD → invoice → payment → closed. Must feel like a live operations control tower, not a data-entry form app.

## User Choices (Feb 2026)
- LLM: Claude Sonnet 4.6 via Emergent Universal Key
- Auth: JWT + Emergent Google Auth (implemented JWT, Google Auth deferred)
- Integrations: mock placeholders for Maps/Weather/Samsara/Fuel/SMS
- Documents: metadata-only for MVP (object storage hook deferred)
- Seed data: yes — 15 loads, 8 trucks, 10 drivers

## Implemented (V1 - MVP)
- Backend: FastAPI with 40+ endpoints (auth, loads, trucks, drivers, invoices, docs, activity, dashboard stats/charts, seed, placeholder integrations, AI streaming)
- Frontend: 19-page sidebar, dense terminal-style UI (Chivo/IBM Plex Sans/Mono, #09090B)
- Dashboard with 24 KPI cards + 5 charts
- Operations Board with 14-column Kanban
- Load Execution Page (crown jewel) with timeline, quick actions, weather/road/fuel/samsara panels, docs checklist, activity log, driver alert generator
- Trucks & Drivers master tables with inline status editing
- In-Transit Control with live timers, Weather & Road Risk, Fuel Planner, Telematics
- Documents (with pending-POD alerts), Invoices with aging/status
- Trip P&L with auto-calc gross/net/PPM/margin
- Driver & Truck Scorecards, Reports (daily owner report + 7 sub-reports)
- AI Assistant (Claude Sonnet 4.6 streaming with live business context)
- JWT auth with 5 roles + 3 demo users seeded

## Deferred / P1 Backlog
- Wire real Google Maps Routes API
- Wire real Weather API (OpenWeatherMap)
- Wire real Samsara telematics API
- Wire WhatsApp/Telegram/SMS senders (Twilio, Telegram Bot)
- Emergent Google Auth (JWT is live)
- Real file uploads to Emergent object storage (metadata works now)
- Advanced drag-drop on Kanban
- Role-based UI gating (routes exist but not gated per role)

## Test Credentials
Located in /app/memory/test_credentials.md
