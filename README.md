# Inventory Service — Code Review Exercise

A small Django REST-ish service for a warehouse: products, stock levels,
customer orders. Written by a junior engineer who was moving fast.

## Your task (mirrors the real interview)

1. **Review** the codebase and identify the most important issues.
   Prioritize what matters — correctness, concurrency, performance,
   security — over style nitpicks.
2. **Triage out loud**: which 2–3 issues matter most and why?
3. **Fix in place**: pick ONE or TWO meaningful problems and solve them
   cleanly. Readable code, edge cases handled, overall quality improved.
   Not just a patch — a fix you'd be happy to merge.

Treat the AI assistant the way you would on the job. Stay in control:
you decide what's wrong and how to fix it; let the AI handle the typing.

## Where to look

- `inventory/models.py`   — data model
- `inventory/views.py`    — the HTTP endpoints (most issues live here)
- `inventory/services.py` — business-logic helpers
- `inventory/urls.py`     — routing

## Running it

    python3 -m venv .venv
    source .venv/bin/activate
    cp .env.example .env      # then edit DJANGO_SECRET_KEY
    python -m pip install -r requirements.txt
    python manage.py migrate
    python manage.py shell < seed.py      # prints alice's id + product ids
    python manage.py runserver

Example: GET /api/products/low-stock/?threshold=10

## Self-grading

Do the full review BEFORE opening `ANSWER_KEY.md`. Time yourself: aim for
~25 min review + triage, ~15 min on the clean fix. Then compare.
