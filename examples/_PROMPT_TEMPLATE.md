# Prompt template for generating a quiz

Copy the block below into a chat or agent. Fill in the `«…»` fields.
The reply must be **JSON only** (or a ` ```json ` … ` ``` ` fence), with no surrounding commentary.

---

Create a quiz in schema_version 1 format.

## Parameters
- Section (examples folder): «for example k8s»
- File name: «for example networking.json»
- title: «…»
- description: «…»
- tags: [«section», «…»]
- Number of questions: «8–12»
- Difficulty (1–5): «2–3»
- Types: single / multiple / true_false (mix them)
- Code blocks: «yes/no», languages: yaml, bash, python, json
- Audience: «DevOps junior/middle»
- Topic focus: «…»
- Extra requirements: «…»

## Strict JSON rules
1. Root object:
   - schema_version: 1
   - external_id: «{section}/{file name without .json}» (stable id)
   - title, description, tags[], questions[]
2. Each question:
   - type: single | multiple | true_false
   - topic, difficulty (1–5)
   - question (non-empty), explanation (non-empty)
   - options: object with 2–8 keys (A/B/C… or true/false), non-empty texts
   - correct: array of keys from options
     - single and true_false → exactly 1 key
     - multiple → 1 or more
   - code (optional): { "language": "…", "content": "…" }
   - option_explanations (optional): notes on the wrong options
3. Do not invent flags or APIs that do not exist. Code samples should be short and realistic.
4. Return one valid JSON object, ready to save as
   `examples/<section>/<name>.json`.

## Minimal structure
```json
{
  "schema_version": 1,
  "external_id": "k8s/example",
  "title": "Example",
  "description": "…",
  "tags": ["k8s"],
  "questions": [
    {
      "type": "single",
      "topic": "Pods",
      "difficulty": 2,
      "question": "…",
      "options": { "A": "…", "B": "…", "C": "…", "D": "…" },
      "correct": ["B"],
      "explanation": "…",
      "option_explanations": { "A": "…" }
    }
  ]
}
```
