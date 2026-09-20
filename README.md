# linkedin

Reserves future LinkedIn post slots from GitHub Actions, using **LinkedIn's own
scheduler**.

## How it works

The workflow never publishes anything at run time. Each run picks the next
unclaimed slots and asks LinkedIn to schedule a post into them. The actual
publishing happens inside LinkedIn, on LinkedIn's clock.

That design matters:

- A delayed, skipped or failed run cannot cause a missed post, because the post
  is already sitting in LinkedIn's scheduler.
- Slots are always spaced 15 minutes apart inside an 08:00 to 19:00 window, so a
  retry can never produce a burst.
- Runs are capped (`--max-batches`), so one run stays short and the next one
  simply continues from where it stopped.

The workflow runs **every 3 hours** and tops up the next 14 days. When the queue
runs dry it says so and stops.

## Layout

```
scripts/linkedin_poster.py      browser automation + LinkedIn native scheduling
scripts/batch_schedule.py       picks open slots, drives the poster in batches
auto_apply/core/                browser (cookie session) + schedule state
content/posts_queue.txt         the queue: posts waiting for a slot
content/posts_sent.txt          journal: every post that got a slot
content/posts_ambiguous.txt     slots that could not be confirmed
content/schedule_state.json     crash-safe journal for in-flight posts
content/posts_*.txt             the source batches the queue was built from
```

`content/posts_sent.txt` and `content/posts_ambiguous.txt` are what stop the same
slot being used twice. The workflow commits them back after every run. They are
the only files CI ever commits.

## Secrets

One repository secret is required.

| Secret | What it is |
|---|---|
| `LINKEDIN_STORAGE_STATE_B64` | base64 of the logged-in browser session (`storage.json`) |

Nothing else. No username, no password, no API key. The session file is the
credential.

### Where it goes

It is written to `browser_profile/storage.json` for the duration of the run only.
`browser_profile/` and `storage.json` are in `.gitignore`, and the commit step
refuses to run if a file named `storage.json` is ever staged.

### Refreshing the LinkedIn session

LinkedIn cookies last a long time but not forever. When a run reports `session
file has no linkedin cookies`, or the poster starts hitting a login wall,
re-export the session:

1. On the machine that has a display, run the login helper:
   ```bash
   cd ~/Desktop/jobs/linkedin
   python3 scripts/pre_login.py
   ```
   Sign in, press Enter, and it writes `browser_profile/storage.json`.
2. Trim it to LinkedIn cookies only, then base64 it:
   ```bash
   python3 scripts/trim_session.py browser_profile/storage.json
   base64 -i browser_profile/storage.json.trimmed | pbcopy
   ```
3. Paste it into the secret:
   ```bash
   gh secret set LINKEDIN_STORAGE_STATE_B64 --repo mrfentmen/linkedin
   ```
   (or GitHub > Settings > Secrets and variables > Actions)

Step 2 trims out unrelated cookies (Google, Indeed, ad networks). The poster only
signs into LinkedIn, so shipping anything else just widens what could leak.

## Adding posts

1. Add the new posts to `content/` as a `posts_<name>.txt` file, blocks separated
   by a `---` line, following the same shape as the existing batches.
2. Append them to `content/posts_queue.txt`.
3. Commit and push. The next scheduled run picks them up.

The next run also prints the queue count in its summary, so an empty queue is
visible without reading logs.

## Running it by hand

- Manual trigger: Actions > **linkedin-scheduler** > Run workflow.
- `plan_only` shows which slots would be filled and schedules nothing.
- Local dry run (no posts, no writes):
  ```bash
  python3 scripts/batch_schedule.py --start-date 2026-09-21 --end-date 2026-09-21 --show-plan
  ```

## What is deliberately not here

- No passwords, tokens, API keys or cookies. Empty by construction, not by
  convention.
- No personal profile data. `config.yaml` is gitignored and the poster runs
  without it.
- Third party data (scraped comments) is not part of this repo.
