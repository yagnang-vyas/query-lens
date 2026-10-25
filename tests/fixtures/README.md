# Test fixtures

Every file in this directory is **synthetic**. The data was invented for testing: e-mail addresses
use `example.com`, names are obviously fake (`jane.fake`, `bob.fake`), and "secrets" such as
`sk_test_FAKE_...` are made-up strings that match no real service. No log in this repository
comes from a real system.

| File | Purpose |
|---|---|
| `privacy_postgres.log` | PostgreSQL log whose statements, malformed lines and `DETAIL:  parameters:` lines carry fake personal data and secrets that must never appear in any report |
| `privacy_mysql.log` | The same idea for the MySQL slow log |

The larger demo logs live in [`../../examples/`](../../examples) and double as inputs for the golden
JSON files in [`../golden/`](../golden).
