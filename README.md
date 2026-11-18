# Private PR review agent

Lightweight Python 3.12+ standard-library service: signed GitHub webhook → SQLite queue → isolated Pi/Copilot run → private SHA-bound draft. No framework, Redis, database server, GitHub App, or second GitHub token. **No review is published.**

## Implemented

- `pull_request.review_requested` for the explicitly configured numeric GitHub user ID (`REVIEWER_ID`, required; no personal default), explicit repository allowlist, open/non-draft PRs. Assignee/team events are intentionally not treated as personal review requests.
- HMAC-SHA256 on raw request bytes, body limit, durable SQLite WAL admission before acknowledgement.
- Delivery and semantic deduplication; retries/backoff, failure state, crash lease recovery.
- Re-fetch current PR before and after review; discard drafts if head SHA, open state or requested reviewer changes.
- Fetch paginated PR file patches through the single PAT. Diff-only review, no checkout or execution of PR code.
- Pi in a constrained disposable Docker container: no GitHub PAT, host home, repository mount, tools, extensions, skills, MCP or context files. Timeout/output caps. Local JSON drafts only.

## Quick start

```sh
python3 -m unittest discover -s tests -v
python3 app.py --help
```

Configure environment variables using `.env.example` as a reference (it is not auto-loaded). Set `ALLOWED_REPOS` to a comma-separated list of exact `owner/repo` names. Store real secrets outside git. The webhook secret is separate from your GitHub PAT.

Token: select only the needed repositories, `Contents: read`, `Pull requests: read and write`. This MVP only reads; write permission is reserved for a later explicit publication step. A fine-grained PAT is limited to one resource owner and any organization policies/approval. Webhook setup is manual in repository Settings; this service does not require webhook-administration permission.

Run the receiver and **one** worker as separate processes under a service manager:

```sh
python3 app.py serve
python3 app.py worker
# Inspect job state or process one queued job:
python3 app.py status
python3 app.py once
```

Receiver binds `127.0.0.1:8787`. For GitHub delivery, put a TLS reverse proxy with connection, request-rate and body limits in front of `/webhooks/github`. Select the Pull requests event and enter your random webhook secret. Do not expose the Python HTTP server directly. It is a small serial receiver, not a production edge server. Monitor 503 responses and manually redeliver missed GitHub events. Back up the data directory and prune old jobs/deliveries/drafts as appropriate; automatic retention is not implemented.

## Pi and Copilot

You connect Copilot separately through Pi. Build a pinned Pi image after choosing/testing its release:

```sh
docker build -f Dockerfile.pi --build-arg PI_VERSION=YOUR_TESTED_VERSION -t pr-review-pi:local .
```

Set `PI_MODEL` to a model available to your Copilot account. Set `PI_AUTH_DIR` to a **dedicated** directory containing only Pi's Copilot `auth.json`, not your normal Pi directory or other providers' credentials. Make it readable to the image's `node` UID (1000) without making it world-readable. The worker mounts it read-only and sets `PI_CODING_AGENT_DIR=/auth`. Perform OAuth login/refresh outside the worker, for example using the same pinned Pi release and dedicated agent directory. An expired credential requiring persistence may fail in the read-only runtime; refresh it outside and retry. Never paste a PAT into prompts.

The runtime uses `pi -p --no-session --provider github-copilot ... --no-tools` with context/extension/skill/MCP discovery disabled. Review input goes over stdin. Pin and verify these flags against the selected Pi version. No Pi package or Docker image has been downloaded by this project. Live Copilot authentication/model compatibility still needs an integration test on your host.

Docker is required only for the worker. Copilot needs outbound network access; this Docker configuration is not a domain allowlist. For stronger isolation use a dedicated worker VM and egress proxy restricted to the provider's required endpoints. Container hardening is defense in depth, not a guarantee against prompt injection. Private diff content is sent to the configured Copilot provider; ensure this is allowed for the selected repositories.

The Docker build context is allowlisted to the Dockerfile and `.dockerignore` only, so local credentials, private drafts and Git history are not sent to the build daemon.

## Drafts and publication

Successful jobs write `data/draft-ID.json` with repository, PR number, exact `commit_id`, `event: COMMENT`, body and `published: false`. Read and edit the body before any posting. This MVP deliberately has **no publish endpoint or command** and never calls GitHub mutation APIs. Future publication should require an explicit human approval of the final body and SHA, recheck the head, and record/reconcile the resulting review ID before retrying uncertain submissions. No automatic APPROVE or REQUEST_CHANGES.

## Limits and safety

- Diff-only: no whole-repository context, tests or dependency execution. Missing patches (binary/large files) must be reported as gaps. Oversized diffs fail closed instead of silently truncating.
- Listings reaching 3,000 files fail closed before invoking Pi, including PRs with exactly 3,000 files. [GitHub caps the PR-files endpoint at 3,000](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files), so an empty next page cannot prove completeness. These PRs require manual review.
- GitHub's PR-files API reads the current PR, not an immutable SHA-pinned snapshot. Head checks before and after review reject ordinary updates, but do not prove a consistent snapshot if a PR changes and returns to the original SHA during pagination. Immutable diff capture is still needed before production publication.
- Trigger is only the original personal review request; no polling/backfill or `synchronize` handling yet. A new commit makes an existing job stale rather than re-triggering automatically.
- Worker max run 5 minutes, lease 15 minutes; run only one worker. Retried jobs can incur extra provider usage after a crash, but cannot duplicate public reviews because publication is absent.
- Failed jobs stop after three handled failures. Inspect configuration, then deliberately requeue in SQLite or request a fresh review after a new commit; no administrative HTTP surface.
- Model Markdown is untrusted; inspect it before rendering, following links or publishing.
- GitHub/Copilot/Docker end-to-end behavior has not been verified without credentials and a target repo. Unit tests use fake GitHub/Pi and do not establish live integration success.

## References

[Hermes webhook guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/guides/webhook-github-pr-review.md), [GitHub webhook verification](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries), [GitHub PR reviews](https://docs.github.com/en/rest/pulls/reviews), [Pi CLI](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/cli.md).
