# Family Dashboard — Requirements

A web application for a family to manage calendar, chores, reminders, inventory, and weekly meal planning.

> **Note:** An earlier plan targeted a serverless AWS stack (Lambda, DynamoDB, CloudFront/S3, Cognito, Bedrock). That plan was dropped. This document describes the architecture that was actually built.

---

## Architecture

| Concern | Choice |
|---|---|
| Hosting | Single host running Docker Compose |
| Frontend | React / JavaScript (Vite) |
| Backend | Python / Flask |
| Database | PostgreSQL (SQLAlchemy ORM + Alembic migrations) |
| Auth | Basic auth — single shared family login |
| AI | OpenAI GPT-4o (meal plan generation) |
| Reverse proxy | Caddy |
| Infrastructure | Defined as code (Terraform in `infra/`) |

---

## Authentication

- Single shared login for the whole family (basic auth).
- No per-member accounts; family member identity is selected contextually (e.g. when recording a chore completion).

---

## Family Members

Each family member has a profile stored as markdown (`familymembers/<name>.md`) containing:
- Role: `adult` or `child`
- Food likes and dislikes (used to steer meal generation)
- Any dietary requirements or allergies

Adults can manage chores and record completions. Children accumulate points that convert to pocket money.

---

## Features

### 1. Calendar

- Displays the embedded family Google Calendar.
- Calendar data is also used by the meal planner to determine which days require meals (e.g. skip days where the family is eating out or away).

---

### 2. Chores

#### Chore Management
- Any adult can create, edit, and delete chores.
- Each chore has:
  - Name and description
  - Assigned family member (any member, adult or child)
  - Point value
  - Reset frequency (weekly, monthly, or one-off)

#### Recording Completions
- Only adults can record a chore as complete.
- When recording, the adult selects which family member completed the chore.
- Points are awarded to that family member.

#### Points & Pocket Money
- All family members accumulate points.
- Children's points convert to pocket money weekly at a configurable rate (default: **1 point = 10p GBP**).
- The dashboard displays a "pocket money owed" summary per child.
- Adults can mark pocket money as paid, which clears the balance and logs the payment.
- Adult points are tracked and displayed but do not convert to money.

#### Chore Reset
- Each chore resets on its configured frequency (a weekly chore resets each Monday; a monthly chore appears on the week containing the 1st).
- After reset, the chore becomes available to be completed again.

---

### 3. Meal Planning

A three-stage weekly workflow: **Generate → Review → Shopping List**

#### Stage 1 — Generation
- Triggered manually (e.g. start of each week).
- Calls OpenAI GPT-4o to generate a meal plan for the coming week.
- Covers **lunch and dinner** for each day (7 days).
- The model is given:
  - The family calendar for the week (to skip days where meals aren't needed)
  - Per-member steering from each family member's profile file (likes, dislikes, dietary requirements)
- Each generated meal includes:
  - Meal name
  - Description
  - Required ingredients (with quantities)

#### Stage 2 — Review
- Each meal is presented for review. An adult can:
  - **Accept** — meal is confirmed for that slot
  - **Reject** — prompted to enter a reason; reason is passed back to the model and a replacement meal is generated for that slot
  - **Not required** — slot is marked as no meal needed (e.g. eating out)
- Process repeats until all slots are accepted or marked not required.

#### Stage 3 — Shopping List
- Once all meals are accepted, a consolidated ingredients list is generated.
- The list is pushed to **Todoist** via the Todoist REST API — each ingredient becomes an individual task.
- Family can check items off in Todoist as they shop, and add ad-hoc items via Google Home voice commands using the Todoist + Google Assistant integration.
- Requires a Todoist API token (stored in `git.env`).

---

## Out of Scope (for now)

- Per-member logins
- Mobile app (web only)
- Breakfast meal planning
- Historical meal plan archive

---

## Open Items

- Harden the single shared login (currently weak basic auth).
- Make family-specific seed data and lookups configurable (open-source goal).
