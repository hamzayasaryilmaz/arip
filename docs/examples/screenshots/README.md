# Screenshots — capture guide

ARIP's investigation engine runs locally, so the binary screenshots
for README/walkthrough need to be captured during a live demo run.
The Markdown artifacts in `../*.md` are reproducible, byte-stable
outputs of the same pipeline — those don't need recapture.

## What to capture (and where to save)

| Filename                          | URL / view                                                                            |
|-----------------------------------|---------------------------------------------------------------------------------------|
| `jaeger-retry-storm.png`          | `http://localhost:16686/trace/<retry_storm_trace_id>` (Jaeger UI, full span tree)     |
| `jaeger-pool-exhaustion.png`      | `http://localhost:16686/trace/<pool_exhaustion_trace_id>` (`db.acquire_connection` highlighted) |
| `jaeger-services.png`             | `http://localhost:16686/search` → service dropdown listing all 4 emitting services    |
| `pr-comment.png`                  | A PR with the sticky `arip-investigation` comment expanded, two failures visible      |
| `pr-comment-rerun.png`            | Same PR after a re-run — comment updated in place, not duplicated                     |
| `pr-artifact.png`                 | Actions run summary showing `arip-reports` artifact + the markdown report inside      |

Save them all here:

```
docs/examples/screenshots/
├── jaeger-retry-storm.png
├── jaeger-pool-exhaustion.png
├── jaeger-services.png
├── pr-comment.png
├── pr-comment-rerun.png
└── pr-artifact.png
```

## Reproducible setup

```bash
# 1. clean state
docker compose down -v
rm -rf reports .arip arip-pr-comment.md

# 2. bring everything up
docker compose up -d --wait

# 3. run the demo
bin/arip-e2e.sh

# 4. find the trace IDs to screenshot
ls -1 reports/*.md | while read f; do
  rule=$(grep -m1 'Rule: ' "$f" | sed 's/.*`\(.*\)`.*/\1/')
  trace=$(grep -m1 'Trace:' "$f" | sed 's/.*`\(.*\)`.*/\1/')
  printf "%-25s %s\n" "$rule" "http://localhost:16686/trace/$trace"
done
```

That last block prints a clickable URL per scenario. Open each in a
browser and screenshot the trace tree.

## After capturing

Reference the screenshots from the README / walkthrough using
ordinary relative-path markdown image syntax. Use the filenames
listed in the table above.

Do not commit any sensitive data — these are demo screenshots only.
