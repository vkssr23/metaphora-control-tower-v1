# Metaphora Control Tower — Complete Handoff

## 1. Product

**Company:** Metaphora AI
**Product:** Metaphora Control Tower
**Tagline:** AI Operating System for Freight Operations
**Positioning:** SaaS-style trucking TMS control tower for USA carriers (5–100 trucks). Runs Amazon Relay, broker freight, dedicated contracts, direct shipper freight.

**Core promise:** Load decisions. Dispatch execution. Safety compliance. Profit control.

**Deployed:** https://metaphora.ai (production). Preview also active on Emergent.

---

## 2. Tech Stack

- **Backend:** FastAPI (Python) at `0.0.0.0:8001`, MongoDB via Motor async driver
- **Frontend:** React + Tailwind + shadcn/ui, craco build, at `:3000`
- **Auth:** JWT (bcrypt-hashed passwords), self-signup only (no demo/general logins)
- **AI:** Claude Sonnet 4.6 via `emergentintegrations` library + Emergent Universal LLM Key
- **Charts:** recharts
- **Icons:** lucide-react
- **Toasts:** sonner
- **Routing:** react-router-dom v6
- **Fonts:** Chivo (display) + IBM Plex Sans (body) + IBM Plex Mono (data)
- **Supervisor** manages both processes; hot reload enabled
- **Env vars (backend/.env):** `MONGO_URL`, `DB_NAME`, `CORS_ORIGINS`, `EMERGENT_LLM_KEY`, `JWT_SECRET`
- **Env vars (frontend/.env):** `REACT_APP_BACKEND_URL`

---

## 3. Design System

- **Colors** (CSS variables, dark/light):
  - Dark navy background `#070B14`, graphite `#1A2438`, white text
  - Electric green brand `#00E28A` (dark) / `#00D084` (light)
  - Green / Yellow / Red risk system for compliance + load decisions
- **Theme switcher:** Dark / Light / Automatic (system). Persisted in `localStorage['metaphora_theme']`. Cycle button in Topbar + full picker in Settings.
- **Component style:** "Control tower / Bloomberg terminal" — dense mono data tables, KPI cards, colored badges, Kanban.

---

## 4. Backend Endpoints (all prefixed `/api`)

### Auth
- `POST /auth/signup` — `{name, email, password, role}` → `{token, user}`
- `POST /auth/login` — `{email, password}` → `{token, user}`
- `GET /auth/me` — decode Bearer token

### Loads / Dispatch
- `GET /loads`
- `GET /loads/{id}`
- `POST /loads`
- `PUT /loads/{id}`
- `DELETE /loads/{id}`
- `POST /loads/{id}/stage` — `{stage, updated_by, notes}` (auto-updates BOL/POD/invoice statuses, writes activity log)

### AI Decision Engine
- `POST /loads/analyze` — `{offered_rate, loaded_miles, deadhead_miles, driver_type, fuel_price?, mpg?, driver_pay_cpm?, tolls?, pickup_city, delivery_city, ...}` → `{decision(Book|Negotiate|Reject), risk(Green|Yellow|Red), score, net_profit, margin_pct, rpm, target_rate, min_acceptable_rate, reasoning, ...breakdown}`

### Compliance
- `GET /compliance` → `{summary:{green,yellow,red,dispatch_blocked}, items:[{entity_type, entity_id, entity_name, status, blockers, warnings, dispatch_allowed, details}]}`

### Cost Assumptions
- `GET /assumptions` — returns fuel_price, mpg, driver_pay_solo_cpm, driver_pay_team_cpm, insurance_per_week, rental_per_week, factoring_fee_pct, default_toll, target_margin_pct, min_rpm, min_net_profit
- `PUT /assumptions`

### Fleet
- `GET /trucks`, `POST /trucks`, `PUT /trucks/{id}`, `DELETE /trucks/{id}`
- `GET /drivers`, `POST /drivers`, `PUT /drivers/{id}`, `DELETE /drivers/{id}`

### Documents & Invoices
- `GET /documents?load_id=X`, `POST /documents`
- `GET /invoices`, `POST /invoices`, `PUT /invoices/{id}`

### Activity Log
- `GET /activity?load_id=X`

### Dashboard
- `GET /dashboard/stats` — 24 KPIs (revenue, profit, active/booked/transit/delivered loads, BOL pending, invoice pending, RPM, PPM, idle trucks, etc.)
- `GET /dashboard/charts` — revenue_by_week, stage_distribution, profit_by_truck, profit_by_driver, fuel_trend

### Mocked External Integrations (return realistic random data, hooks ready for real APIs)
- `POST /routing/calc` — Google Maps route mileage
- `POST /weather/check` — Weather risk
- `POST /roads/check` — Road conditions
- `POST /samsara/vehicle` — Truck telematics
- `POST /fuel/plan` — Fuel stop recommendation
- `POST /truckstops/plan` — Truck stop recommendation
- `POST /alerts/generate` — Driver alert message generator

### AI Chat
- `POST /ai/chat` — `{session_id, message}` → streams plain text (Claude Sonnet 4.6 with live business-data context; falls back to rule-based if LLM unavailable)

### Seed
- `POST /seed?force=true` — wipes and reseeds 15 loads, 8 trucks, 10 drivers, invoices (does NOT create any demo users — self-signup only)

---

## 5. Frontend Routes (React Router)

- `/login` — signup + login tabs, hero with product pitch
- `/` — **Executive Dashboard**
- `/analyze` — **Load Market Analysis** (AI Decision Engine)
- `/board` — **Dispatch Board** (14-column Kanban with drag-and-drop stage changes)
- `/loads` — Loads master table
- `/loads/:id` — **Load Execution Page** (timeline, 13 quick actions, weather/road/fuel/samsara panels, docs checklist, activity log, driver alert generator)
- `/trucks` — Trucks master
- `/drivers` — Drivers master
- `/compliance` — **Safety & Compliance Tracker** (CDL, medical, MVR, Clearinghouse, insurance, registration, inspection with days-until-expiry)
- `/dispatch` — Dispatch queue (unassigned loads)
- `/in-transit` — In-Transit control panel with live timers
- `/weather` — Weather & Road Risk per active lane
- `/fuel` — Fuel Stop Planner
- `/telematics` — Samsara / Telematics feed
- `/documents` — Documents inbox (BOL, POD, Rate Con) + pending-POD alerts
- `/invoices` — Invoice tracker with aging + status
- `/pnl` — Trip P&L with auto-calc net/PPM/margin
- `/driver-scorecard` — Ranked driver performance
- `/truck-scorecard` — Ranked truck PPM performance
- `/reports` — Daily owner report + 7 sub-reports (memoized)
- `/ai` — AI Assistant chat (Claude Sonnet streaming with suggestion chips)
- `/settings` — User profile, theme switcher, cost assumptions form, integrations status, reseed

---

## 6. Sidebar Nav (20 items) + Role Gating

Sidebar filters items by user role (memoized).

Roles: `owner`, `operations`, `dispatcher`, `safety`, `compliance`, `finance`, `admin`, `driver`.

| Nav Item | Owner | Ops | Disp | Safety | Comp | Fin | Admin | Driver |
|---|---|---|---|---|---|---|---|---|
| Executive Dashboard | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Load Market Analysis | ✓ | ✓ | ✓ |  |  |  | ✓ |  |
| Dispatch Board | ✓ | ✓ | ✓ |  |  |  | ✓ |  |
| Loads | ✓ | ✓ | ✓ |  |  | ✓ | ✓ |  |
| Trucks | ✓ | ✓ | ✓ |  |  |  | ✓ |  |
| Drivers | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |
| Compliance | ✓ | ✓ |  | ✓ | ✓ |  | ✓ |  |
| Dispatch Queue | ✓ | ✓ | ✓ |  |  |  | ✓ |  |
| In-Transit | ✓ | ✓ | ✓ |  |  |  | ✓ |  |
| Weather & Roads | ✓ | ✓ | ✓ |  |  |  | ✓ |  |
| Fuel Stops | ✓ | ✓ | ✓ |  |  |  | ✓ |  |
| Telematics | ✓ | ✓ | ✓ |  |  |  | ✓ |  |
| Documents | ✓ | ✓ | ✓ |  |  | ✓ | ✓ |  |
| Invoices | ✓ |  |  |  |  | ✓ | ✓ |  |
| Profitability | ✓ |  |  |  |  | ✓ | ✓ |  |
| Driver Scorecard | ✓ |  | ✓ | ✓ |  | ✓ | ✓ |  |
| Truck Scorecard | ✓ | ✓ |  |  |  |  | ✓ |  |
| Reports | ✓ | ✓ |  |  |  | ✓ | ✓ |  |
| AI Assistant | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| Settings | ✓ |  |  |  |  |  | ✓ |  |

---

## 7. Data Model (MongoDB collections)

- **users** — {id, email, password (bcrypt), name, role, created_at}
- **loads** — customer, broker, rate_con_number, pickup_*, delivery_*, miles, est_drive_hours, rate, rpm, truck_id, driver_id, dispatcher, stage, risk, eta, bol_status, pod_status, invoice_status, payment_status, fuel_cost, tolls, lumper, driver_pay, factoring_fee, other_expenses
- **trucks** — truck_number, vin, plate, make/model, year, status, current_location, assigned_driver_id, samsara_id, insurance_expiry, registration_expiry, annual_inspection_expiry, maintenance_status, weekly_revenue, weekly_miles, utilization, profit_per_mile
- **drivers** — name, phone, email, cdl_number, cdl_state, cdl_expiry, medical_expiry, mvr_status (Clear|Review|Expired), clearinghouse_status (Clear|Pending|Issue), employment_verification, driver_type (Solo|Team), pay_type, cents_per_mile, assigned_truck_id, status, on_time_pickup_pct, on_time_delivery_pct, missed_updates, late_deliveries, safety_issues, score
- **documents** — load_id, doc_type (rate_con|bol|pod|lumper|scale|invoice), filename, url, uploaded_by, uploaded_at, notes
- **invoices** — load_id, customer, amount, status (Not Ready|Docs Pending|Ready to Invoice|Invoice Created|Invoice Shared|Payment Pending|Paid|Disputed), due_date, paid_date, dispute
- **activity** — load_id, action, old_status, new_status, updated_by, timestamp, notes
- **assumptions** — id:"default", fuel_price, mpg, driver_pay_solo_cpm, driver_pay_team_cpm, insurance_per_week, rental_per_week, factoring_fee_pct, default_toll, target_margin_pct, min_rpm, min_net_profit

---

## 8. Load Decision Engine — Rule Set

**Auto-calcs on `POST /loads/analyze`:**
- total_miles = loaded_miles + deadhead_miles
- rpm = offered_rate / total_miles
- fuel_gallons = total_miles / mpg
- fuel_cost = fuel_gallons × fuel_price
- driver_pay = total_miles × driver_cpm (solo/team from assumptions)
- insurance = insurance_per_week / 5 (amortize per trip)
- rental = rental_per_week / 5
- factoring = offered_rate × factoring_fee_pct / 100
- trip_cost = fuel + driver + tolls + insurance + rental + factoring
- net_profit = offered_rate − trip_cost
- margin_pct = net_profit / offered_rate × 100
- profit_per_mile = net_profit / total_miles
- deadhead_pct = deadhead_miles / total_miles

**Decision rules:**
- **Reject** if net_profit < 0 OR rpm < min_rpm × 0.8
- **Negotiate** if net_profit < min_net_profit OR margin_pct < target_margin_pct × 0.6 OR rpm < min_rpm
- **Book** otherwise
- Bump risk to Yellow if deadhead_pct > 25%
- Target rate = trip_cost / (1 − target_margin_pct/100)
- Min acceptable = trip_cost × 1.08 (breakeven + 8%)
- Load score = 50 + (margin_pct − target_margin_pct) × 1.5, clamped 0–100

---

## 9. Compliance Rules

**Blocks dispatch when:**
- CDL expired
- Medical card expired
- Clearinghouse status = "Issue"
- MVR status = "Expired"
- Insurance expired
- Registration expired
- Annual inspection expired
- Maintenance status = "Bad"

**Warnings (30-45 day expiry windows):**
- CDL / medical expires within 30 days
- Clearinghouse status = "Pending"
- MVR status = "Review"
- Insurance / registration expires within 30 days
- Annual inspection expires within 45 days
- Employment verification = "Pending"
- Maintenance status = "Warn"

---

## 10. What's DONE (V1)

- ✅ Full rebrand to Metaphora
- ✅ 20-page sidebar, dark/light/auto theme
- ✅ Executive dashboard with 24 KPIs + 5 charts
- ✅ Dispatch Kanban with drag-and-drop stage changes (14 columns)
- ✅ Load Execution Page (crown jewel): timeline + 13 quick actions + weather/road/fuel/samsara + docs + activity log + driver alert generator
- ✅ Load Market Analysis with AI Decision Engine (Book/Negotiate/Reject + target rates + score)
- ✅ Safety & Compliance Tracker with dispatch blocking
- ✅ Cost Assumptions (11 tunable knobs)
- ✅ Trip P&L with per-load net/PPM/margin
- ✅ Driver & Truck Scorecards
- ✅ Invoices with aging, Documents with pending-POD alerts
- ✅ Reports (daily owner report + 7 sub-reports)
- ✅ AI Assistant (Claude Sonnet 4.6 streaming with live data context)
- ✅ JWT auth with 8 roles + self-signup only (no demo logins)
- ✅ Role-based sidebar gating
- ✅ Seeded sample data: 15 loads, 8 trucks, 10 drivers with realistic compliance expiries

---

## 11. What's DEFERRED (P1 backlog, next chat should tackle)

### External integrations (need API keys from user)
- **Google Maps Routes API** — replace `/routing/calc` mock with real Distance Matrix / Routes API
- **OpenWeatherMap** — replace `/weather/check` mock with real forecast
- **Samsara telematics** — replace `/samsara/vehicle` mock with real API (needs paid enterprise account)
- **Twilio SMS + WhatsApp** — actually send driver alerts via `/alerts/generate` endpoint
- **Telegram bot** — free via @BotFather, easiest to add first

### Auth expansions
- **Emergent Google Auth** — add "Sign in with Google" alongside JWT (needs cookie/session refactor, playbook exists)
- **Admin invite flow** — Owner sends signup link pre-tagged with role, instead of anyone self-selecting "Owner" (needs email service — Resend or SendGrid)

### Storage
- **Emergent Object Storage** — real file uploads for BOL/POD/Rate Con (currently metadata-only)

### AI upgrades
- **Tool-using AI Assistant** — teach the AI to call `/api/loads/analyze` and `/api/compliance` as tools so it can proactively say "That load = Reject, and Driver Mike's medical expires in 6d"
- **Alerts & Exception Center** — turn every compliance warning / low-margin load / missing POD / late payment into a triaged alert queue with owner assignment

### Perf / hardening
- MongoDB indexes on `loads.stage`, `loads.driver_id`, `loads.truck_id`, `activity.load_id`
- Query projections on `dashboard_stats`, `dashboard_charts`, AI context builder (currently fetch full docs)
- Rate limiting on `/auth/signup`
- Password strength policy beyond min-6

### Code hygiene (nice-to-have, not blockers)
- Migrate JWT from localStorage → httpOnly cookies (major refactor)
- Split LoadExecution (344 lines) into sub-components
- Split analyze_load / seed / compliance_overview into helper functions

---

## 12. Test Credentials

**None pre-seeded.** Every operator must self-register via `/login` → "Create Account" tab.

For QA: sign up with `qa@yourdomain.com / testpass123 / role=owner`.

---

## 13. Key Files (main agent should read these first in a new chat)

```
/app/backend/server.py                          # All 40+ endpoints, models, seed, AI, decision engine, compliance
/app/backend/.env                               # MONGO_URL, DB_NAME, EMERGENT_LLM_KEY, JWT_SECRET, CORS_ORIGINS
/app/backend/requirements.txt

/app/frontend/src/App.js                        # Router, ThemeProvider, AuthProvider, Protected route
/app/frontend/src/index.css                     # Full color system, light/dark CSS vars, badges
/app/frontend/src/lib/api.js                    # axios client with Bearer interceptor
/app/frontend/src/lib/auth.jsx                  # login/signup/logout, localStorage
/app/frontend/src/lib/theme.jsx                 # Dark/Light/Auto with matchMedia listener

/app/frontend/src/components/Sidebar.jsx        # 20-item nav with role gating
/app/frontend/src/components/Topbar.jsx         # Search + theme toggle + bell
/app/frontend/src/components/Shell.jsx          # Sidebar + Outlet layout
/app/frontend/src/components/Badges.jsx         # StageBadge / RiskBadge / Money / Num

/app/frontend/src/pages/Login.jsx               # Sign in ↔ Create Account tabs
/app/frontend/src/pages/Dashboard.jsx           # 24 KPIs + 5 charts
/app/frontend/src/pages/LoadAnalysis.jsx        # AI Decision Engine form + result
/app/frontend/src/pages/OperationsBoard.jsx     # 14-col Kanban with drag-drop
/app/frontend/src/pages/LoadExecution.jsx       # 344-line load command page (crown jewel)
/app/frontend/src/pages/Compliance.jsx          # Safety & compliance tracker
/app/frontend/src/pages/Settings.jsx            # Theme + Cost Assumptions
/app/frontend/src/pages/AIAssistant.jsx         # Streaming Claude chat
# + 12 more page files for the remaining sidebar items

/app/memory/PRD.md                              # Product requirements + backlog
/app/memory/test_credentials.md                 # Points at self-signup
/app/memory/HANDOFF.md                          # THIS DOCUMENT
```

---

## 14. Prompt for a Fresh Chat

> I'm continuing work on **Metaphora Control Tower**, an AI operating system for USA trucking carriers (Metaphora AI brand). The V1 is deployed at `https://metaphora.ai`. Full architecture docs are at `/app/memory/HANDOFF.md`.
>
> Tech stack: FastAPI + React + Tailwind + MongoDB + Motor + Claude Sonnet 4.6 (via emergentintegrations + Emergent Universal LLM Key) + JWT auth (self-signup, no demo users).
>
> Please read `/app/memory/HANDOFF.md` first. Do NOT rebuild anything already listed as done. My next priority is: _[YOUR NEXT ASK HERE — e.g., "wire the real Twilio SMS integration for driver alerts", or "build the Alerts & Exception Center", or "add tool-using AI so the assistant can call the Load Decision Engine directly"]_.
