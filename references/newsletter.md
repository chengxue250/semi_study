# Newsletter Setup

The Cloudflare Worker supports a real newsletter flow:

- `POST /api/subscribe` stores a pending subscriber in D1 and sends a confirmation email.
- `GET /api/confirm?token=...` confirms the subscriber.
- `GET /api/unsubscribe?token=...` unsubscribes the address.
- `POST /api/send-daily` sends the current `output/edition.json` digest to confirmed subscribers.

## Cloudflare Resources

The production Worker is `daily-semi`.

The newsletter database is D1:

```text
database_name = daily-semi-newsletter
database_id   = 1316c5b1-04e9-4c24-b64c-a3a561770cd8
binding       = DB
```

Schema migrations live in `migrations/`.

Apply migrations with:

```bash
node_modules/.bin/wrangler d1 migrations apply daily-semi-newsletter --remote
```

## Required Secrets

Set these in Cloudflare before expecting confirmation or daily emails to send:

```bash
node_modules/.bin/wrangler secret put RESEND_API_KEY
node_modules/.bin/wrangler secret put NEWSLETTER_FROM
node_modules/.bin/wrangler secret put NEWSLETTER_SEND_SECRET
```

`NEWSLETTER_FROM` should be a verified Resend sender, for example:

```text
Semi News Daily <news@example.com>
```

`NEWSLETTER_SEND_SECRET` protects the send endpoint. Generate a strong value:

```bash
openssl rand -hex 32
```

Use the same `NEWSLETTER_SEND_SECRET` locally so the Mac mini daily publish script can trigger sending after deploy. Put it in `.dev.vars` at the repo root; that file is gitignored:

```text
NEWSLETTER_SEND_SECRET=the_same_hex_value
```

## Daily Send Behavior

`scripts/publish_cloudflare_worker.sh` deploys the Worker first. After a successful deploy, it calls:

```bash
POST https://daily-semi.danielsgardenatbabylon.workers.dev/api/send-daily
```

The trigger is skipped when `NEWSLETTER_SEND_SECRET` is not available locally. Send failures are logged as warnings and do not make the site deployment fail.
