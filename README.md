# A-share AI Trader

This repository contains the initial implementation for an instruction-driven A-share paper trading system.

## Structure

- `frontend/`: React + Vite trading dashboard
- `backend/`: Express + Prisma API and Tencent quote proxy
- `docs/`: product and data model documentation

## Quick Start

### Backend

```bash
cd backend
npm install
npm run prisma:generate
npm run prisma:push
npm run dev
```

Backend runs on `http://localhost:3001`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:5173`.

## Current Scope

- Real-time position dashboard
- Today orders table
- History ledger table
- Daily PnL calendar
- Instruction input and Excel/CSV import placeholder
- Tencent quote polling every second during market open windows only
