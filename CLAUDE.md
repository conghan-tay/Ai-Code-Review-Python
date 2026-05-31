## Orientation brief format

When producing a codebase orientation brief (e.g. `CODEBASE_ANALYSIS.md`), use the following eight-section structure:

1. **Key Entry Points** — table of files/routes that are the top-level handles into the system (CLI entry, root URL router, route definitions, dev seeders), followed by a plain-text list of all API endpoints with HTTP method, path, and handler name.

2. **Key Functions — Hard Core of the Codebase** — per-file tables with columns `Function | Lines | Role`. Annotate inline bugs or gotchas with `**BUG**:` or `⚠️` notes directly in the Role cell.

3. **Class Hierarchy and Data Models** — ASCII tree showing inheritance from the framework base class, with each model's fields (name, type, constraints) indented beneath it. Follow the tree with a one-line entity-relationship summary using `──<` / `>──` notation.

4. **Architectural Patterns** — a short prose summary of the overall approach, then two tables: one for layers present (Layer | Location | Description) and one for patterns observed; finish with a bullet list of notable absent patterns.

5. **Existing Tests** — state coverage honestly (including "No tests exist"). Follow with a table of missing test areas (Area | Missing Tests) covering each view/service function plus integration and concurrency scenarios.

6. **Constraints and Assumptions** — two tables: *Configuration Constraints* (Constraint | Location | Value/Risk) for settings-level risks, and *Code-Level Assumptions* (Assumption | Location | Detail) for implicit invariants baked into the code.

7. **Architecture Diagram** — full-width ASCII box diagram showing the request path from HTTP client → URL router → views → services → models → database, plus any in-memory global state boxes.

8. **Mermaid Sequence Diagrams — All Application Flows** — one `sequenceDiagram` per endpoint/flow (labelled Flow A, B, C …), annotating race conditions, N+1 queries, missing transactions, and other bugs with `⚠️` notes inline.

Close the document with a **Critical Issues Summary** table: Priority (P0–P3) | Issue | Location.
