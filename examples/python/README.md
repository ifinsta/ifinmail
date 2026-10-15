# Python examples for the ifinmail API

Small, readable programs for the things integrations usually do: provision mailboxes, send mail,
watch deliverability. They share one client file you can copy into your own project.

```
pip install requests
export IFINMAIL_URL=https://mail.example.com
export IFINMAIL_KEY=ifm_xxxxxxxxxxxx
export IFINMAIL_SECRET=ifs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
python 01_hello.py
```

## Get a key

In the console open **Settings → API keys**, create a key, and pick only the scopes the program
needs. The key (`ifm_…`) is safe to log; the secret (`ifs_…`) is shown **once**. Put both in
your secret store or environment, never in the code. For mail sending, add the addresses the key
may send as (`billing@example.com`, or `*@example.com`).

| Scope | What it allows | Examples |
| --- | --- | --- |
| `console.access` | Read counts | 01 |
| `dns.manage` | Domains and DNS checks | 02 |
| `mail.manage` | Mailboxes and aliases | 03, 04, 08 |
| `mail.send` | Send as the key's allowed addresses | 05 |
| `audit.view` | Health, delivery and error reports | 06, 07 |

A key can never do more than the person who created it can; narrowing that person's role
narrows the key at once.

## The examples

| File | What it shows |
| --- | --- |
| `ifinmail_client.py` | The client: auth, errors, rate limits, safe retries, paging |
| `01_hello.py` | Check the server and your key |
| `02_domains.py` | List and add domains, ask for a DNS check |
| `03_mailboxes.py` | Create (invited or with a password), list, quota, pause, delete |
| `04_bulk_provision.py` | Create mailboxes from a CSV: dry run, safe to rerun |
| `05_send_message.py` | Send mail with an idempotency key, and what each error means |
| `06_delivery_report.py` | What happened to what you sent, and why |
| `07_monitor.py` | Exit codes for cron, Nagios or a CI gate |
| `08_aliases.py` | Aliases |

## Using the client in your code

```python
from ifinmail_client import Client, IfinmailError

api = Client.from_env()                     # or Client("https://mail.example.com", key, secret)

for box in api.mailboxes(domain="example.com"):      # pages are followed for you
    print(box["address"], box["quota_bytes"])

try:
    api.create_mailbox("ana@example.com")            # no password: she is invited to set one
except IfinmailError as exc:
    if exc.status == 409:
        print("already exists")
    else:
        raise

api.send("billing@example.com", ["ana@example.org"], "Your invoice", text="Thank you.")
```

## Things worth knowing

- **Errors are JSON with a `detail` message.** `401` is a refused credential (the same answer for
  every reason, on purpose), `403` a missing scope or a forbidden sender, `404` not found, `409`
  already exists or a duplicate in progress, `422` a value that was not acceptable.
- **Rate limits.** Each key has a calls-per-minute budget. A `429` carries `Retry-After`; the
  client waits and retries a few times.
- **Retries.** Reads and anything with an `Idempotency-Key` are retried on a gateway error. A
  plain write is never retried blindly. `send` always carries a key (generated if you do not
  pass one), so repeating it with the same key never sends a second message.
- **`202` from `send` means accepted, not delivered.** Use the delivery report (06) to see what
  became of mail. "Accepted" by the receiving server is also not "in the inbox".
- **Logins with console access cannot be changed through the API,** and domains cannot be
  removed through it. Keys never create console logins.
- **The contract** is at `/api/v1/openapi.json` on your server (and `/api` lists the versions).
  Generate a typed client from it with any OpenAPI tool if you prefer. Within version 1 only
  additions are made.
- **Do not put a secret on a command line** that others can read (`ps`). The examples read the
  environment on purpose.
