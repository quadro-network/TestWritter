# Interactive quizzes

A local app for multiple-choice quizzes. The web UI and the Telegram bot share one API. Questions live in an external MariaDB or MySQL database.

You can take a quiz, review stats and mistakes, import a ready JSON file, drop JSON into `examples/` or `inbox/`, or upload a PDF. PDF text is sent to a local Ollama model, which returns a set of quizzes.

Stack: FastAPI, SQLAlchemy 2, Alembic, static HTML/JS, aiogram 3. Compose does not start the database.

## Prerequisites

- Docker and Docker Compose
- MariaDB or MySQL already running, with an empty database created
- A Telegram bot token, if you want the bot
- Ollama on the host with a pulled model, if you want PDF import (any model; checked with `qwen2.5:7b` and `granite 8b`)

## Deploy

```bash
cp .env.example .env
```

Create a database and a user with the same names as `DB_NAME` and `DB_USER` in `.env`. Take the password, host, and port from `.env` as well. Alembic creates the schema when the container starts. `schema.sql` is the manual alternative (the database name inside that file must match `DB_NAME`).

Set at least `DB_PASSWORD` and `IMPORT_TOKEN` in `.env`. For the bot, add `BOT_TOKEN` and, if you want an allowlist, `ALLOWED_USER_IDS` (Telegram user ids, comma-separated). `WEB_URL` is the link the bot shows to users.

```bash
docker compose up -d --build
```

The site is at `http://127.0.0.1:2323` (host port is `WEB_PORT`). Check:

```bash
curl -s http://127.0.0.1:2323/api/health
```

Expect `"status": "ok"` and `"database": true`.

Stop with `docker compose down`. The `inbox/`, `examples/`, and `books/` directories are mounted from the host. Database rows stay on the MariaDB server.

## Environment variables

| Variable | Purpose |
|---|---|
| `DB_HOST` / `DB_PORT` / `DB_NAME` | MariaDB or MySQL server |
| `DB_USER` / `DB_PASSWORD` | Credentials |
| `IMPORT_TOKEN` | Secret for the `X-Import-Token` header |
| `WEB_PORT` | Web port on the host |
| `WEB_URL` | Public web URL (shown by the bot) |
| `BOT_TOKEN` | Telegram bot token |
| `ALLOWED_USER_IDS` | Who may use the bot; empty means no id restriction |
| `API_URL` | API URL from other containers (`http://app:8000`) |
| `TG_PROXY` | Optional proxy for Telegram |
| `REMINDER_TIME` | Daily reminder time (`09:00`) |
| `TZ` | Time zone |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Local model used for PDFs |
| `BOOK_QUESTIONS_PER_TEST` | How many questions to generate per quiz |
| `BOOK_PAGES_PER_CHUNK` | How many pages to send to the model per call |

`.env` stays out of the repository.

## Quiz format

A JSON file with `schema_version: 1`:

```json
{
  "schema_version": 1,
  "external_id": "section/file-name",
  "title": "Quiz title",
  "description": "Description",
  "tags": ["section"],
  "questions": [
    {
      "type": "single",
      "topic": "Topic",
      "difficulty": 2,
      "question": "Question text",
      "code": { "language": "yaml", "content": "kind: Pod" },
      "options": { "A": "option", "B": "option" },
      "correct": ["A"],
      "explanation": "Why this is correct",
      "option_explanations": { "B": "Why this is wrong" }
    }
  ]
}
```

- `type`: `single`, `multiple`, or `true_false`
- `options` has 2 to 8 unique keys
- every key in `correct` exists in `options`
- `single` and `true_false` have exactly one correct key; `multiple` has one or more
- `question` and `explanation` are non-empty

Importing the same `external_id` or the same content again updates the existing quiz.

Sample files live in `examples/<section>/*.json`. The model prompt is `examples/_PROMPT_TEMPLATE.md` and the “AI prompt” tab in the web UI.

## Where quizzes come from

**examples directory.** The `runner` service scans `examples/<section>/*.json` every 5 seconds. The folder name is added to `tags`. If `external_id` is missing, it becomes `{section}/{file name}`. Imported files are remembered by sha256 in `examples/.runner_state.json` (that file stays local).

**inbox directory.** The API reads `inbox/*.json` every 5 seconds. A successful file moves to `inbox/processed/`. A failed file moves to `inbox/failed/` next to an error text file.

**Web and bot.** The Import tab and the `/import` command accept the same JSON.

**PDF.** The “PDF books” tab or the `/book` command stores the file in `books/`, splits the text, asks Ollama for JSON, and writes files under `examples/`. The runner imports them. This needs `OLLAMA_BASE_URL` and `OLLAMA_MODEL`.

Runner without Docker:

```bash
EXAMPLES_DIR=./examples API_URL=http://127.0.0.1:2323 IMPORT_TOKEN=change_me \
  python -m runner.examples_runner
```

## Web

The site has the quiz list, a run, stats, mistake review, an editor, JSON import, and PDF upload. API calls other than the health check send the `X-Import-Token` header. Correct answers are returned only after the learner answers a question. The editor shows them immediately.

## Telegram

The `bot` service is in the same Compose file. Commands: `/start`, `/tests`, `/random`, `/mistakes`, `/stats`, `/continue`, `/stop`, `/import`, `/quiz`, `/remind on|off`, `/book`, `/books`. Answers use inline buttons in the chat.

## Tests

```bash
pip install -r requirements.txt
pytest -q
```

Import from the host:

```bash
curl -s -H "X-Import-Token: change_me" -H "Content-Type: application/json" \
  --data @examples/k8s/kubernetes-osnovy.json \
  http://127.0.0.1:2323/api/import
```

Use your own `IMPORT_TOKEN` and any JSON file from `examples/`.
