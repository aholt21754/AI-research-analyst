# Lessons Learned

## Spec Consistency Across Parallel Documents

**Mistake:** When writing Phase 1B and Phase 1C specs in parallel, the two specs treated SSM Parameter Store differently. Phase 1B used deploy-time SSM resolution (injected into env vars via `AWS::SSM::Parameter::Value<String>`), while Phase 1C used the correct runtime fetch with in-memory caching.

**Rule:** Before finalizing parallel specs, explicitly cross-check every shared concern (secrets handling, logging, error handling, data contracts). Any decision that appears in two specs must be identical. When in doubt, align to the more secure/correct approach.

**Checklist for parallel spec review:**
- [ ] Secrets/API keys handled the same way in all specs
- [ ] Logging approach consistent (same library, same event names)
- [ ] Data contracts (e.g. Article dict, output dict) identical
- [ ] Error handling philosophy consistent (retry strategy, partial success semantics)
- [ ] Environment variable names consistent across handler + template + local scripts

---

## HTTP Mocking: Match the Library Used by the Code Under Test

**Mistake:** The `responses` library only intercepts calls made via the `requests` library. Code that uses `urllib` (e.g., original `arxiv.py`) or `feedparser` (which has its own internal HTTP via `urllib`) is not intercepted — tests hit real network URLs.

**Rules:**
1. If source code uses `requests` → mock with `responses` library (`@responses.activate`)
2. If source code uses `feedparser.parse(url)` → mock `feedparser.parse` directly with `patch`
3. If source code uses `urllib` → either switch to `requests`, or mock `urllib.request.urlopen`
4. When a test hits the real network unexpectedly, check which HTTP library the production code actually calls — don't assume `responses` covers everything.

---

## Python 3.14: Reserved Keys in `logging.LogRecord`

**Mistake:** Python 3.14 changed `logging.makeRecord()` to raise `KeyError: "Attempt to overwrite 'message' in LogRecord"` when `extra={"message": ...}` is passed to any logger call. The `message` key is reserved by the logging system.

**Rule:** Never use these reserved key names in `extra={}` dict passed to logger calls: `message`, `name`, `levelname`, `levelno`, `pathname`, `filename`, `module`, `exc_info`, `exc_text`, `stack_info`, `lineno`, `funcName`, `created`, `msecs`, `relativeCreated`, `thread`, `threadName`, `process`, `processName`.

**Fix:** Use `error_msg` instead of `message` for exception strings in log extra data.
