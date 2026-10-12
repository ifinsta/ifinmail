# Edge cases (215)

Every case below is handled. **Proof** says how we know:

| Code | Meaning |
| --- | --- |
| `M` | `backend/apps/core/plugins/tests/test_manifest.py` |
| `L` | `backend/apps/core/plugins/tests/test_lifecycle.py` |
| `S` | `backend/apps/core/plugins/tests/test_submissions.py` |
| `P` | `backend/apps/core/plugins/tests/test_postfix_sync.py` (the real watcher script, stubbed binaries) |
| `B` | `backend/apps/core/plugins/tests/test_scheduling.py` |
| `V` | `backend/apps/accounts/tests/test_marketplace.py` (HTTP, real views and templates) |
| code | Enforced in code, reviewed, no dedicated test |
| decision | A deliberate choice documented in the skill |

Counts: 182 tested, 31 code, 2 decision (215 numbered, contiguous). When behaviour changes, change the row and its test together.

## A. Manifest format and parsing

| # | Case | Handling | Proof |
| --- | --- | --- | --- |
| 1 | Text is not TOML | "is not valid TOML" with the parser's position | M |
| 2 | Bytes are not UTF-8 | "is not UTF-8 text" | M |
| 3 | Upload larger than 32 KiB | Refused before parsing | M |
| 4 | Text larger than 32 KiB (counted in UTF-8 bytes) | Refused before parsing | M |
| 5 | UTF-8 byte-order mark | Stripped, then parsed | M |
| 6 | A table declared twice | TOML error | M |
| 7 | A key repeated inside a table | TOML error from `tomllib` | code |
| 8 | Unknown top-level key | "is not a recognised key" (typos never pass silently) | M |
| 9 | `manifest_version` missing, wrong or `true` | Refused (`true == 1` in Python is not accepted) | M |
| 10 | No `[plugin]` table | Refused | M |
| 11 | Unknown key in `[plugin]` (e.g. `homepage`) | Refused | M |
| 12 | Many problems | All reported at once, each with its location | M |
| 13 | A field that is too long and also malformed | One problem per field | M |
| 14 | Same manifest validated repeatedly | Parsed once per process (LRU by content) | M |
| 15 | Many different manifests | Cache bounded to 128 entries | code |
| 16 | Two texts differing only in whitespace | Different SHA-256, parsed separately (the hash identifies exact text) | code |
| 17 | CRLF line endings | Accepted by the TOML parser | code |
| 18 | Tab or control character in a one-line field | Refused | M |
| 19 | Line breaks in the description | Allowed; blank lines become paragraphs | M |
| 20 | Other control characters in the description | Refused | M |
| 21 | Description over 4000 characters | Refused | M |
| 22 | No description | Allowed | M |
| 23 | Paragraph splitting | On blank lines, trimmed, empties dropped | M |
| 24 | Summary out of bounds (1-160) | Refused | M |
| 25 | Name empty, too long or with control characters | Refused | M |
| 26 | Publisher missing | Refused | M |
| 27 | Category not in the fixed list | Refused, list shown | M |
| 28 | `requires_core` not `X.Y.Z` | Refused | M |
| 29 | Leading or trailing spaces in text fields | Trimmed | code |
| 30 | A number where text is expected | "must be text" | M |

## B. Identity and versions

| # | Case | Handling | Proof |
| --- | --- | --- | --- |
| 31 | Uppercase id | Refused | M |
| 32 | Id shorter than 3 or longer than 40 | Refused | M |
| 33 | Id starting with a digit | Refused | M |
| 34 | Id with `--` | Refused | M |
| 35 | Id ending with `-` | Refused | M |
| 36 | Id with `_` | Refused (ids are URL slugs) | M |
| 37 | Version not `MAJOR.MINOR.PATCH` | Refused | M |
| 38 | Leading zeros (`01.0.0`) | Refused | M |
| 39 | Pre-release suffix (`1.0.0-beta`) | Refused (v1 has no pre-releases) | M |
| 40 | `v` prefix | Refused | M |
| 41 | Component above 9999 | Refused | M |
| 42 | `1.10.0` versus `1.9.0` | Compared numerically, not as text | code |
| 43 | Submission reusing a built-in id | Refused | S |
| 44 | Built-in folder name differs from `plugin.id` | Skipped and reported | code |
| 45 | Invalid built-in manifest | Skipped, logged, shown to administrators as a banner; the rest of the catalog works | code |

## C. Settings schema

| # | Case | Handling | Proof |
| --- | --- | --- | --- |
| 46 | `settings` not a list of tables | Refused | M |
| 47 | More than 20 settings | Refused | M |
| 48 | Unknown key in a setting (e.g. `placeholder`) | Refused | M |
| 49 | Setting without `key` | Refused | M |
| 50 | Key not lowercase snake case | Refused | M |
| 51 | Same key declared twice | Refused at the second | M |
| 52 | Unknown type | Refused | M |
| 53 | Setting without `label` | Refused | M |
| 54 | Help over 300 characters | Refused | M |
| 55 | `required` not a boolean | Refused | M |
| 56 | `min`/`max` on a non-integer | Refused | M |
| 57 | Boolean used as a bound | Refused | M |
| 58 | `min` above `max` | Refused | M |
| 59 | Choice without options | Refused | M |
| 60 | Choice with an empty option list | Refused | M |
| 61 | Duplicate options | Refused | M |
| 62 | Options on a non-choice | Refused | M |
| 63 | `max_length` on a non-text | Refused | M |
| 64 | `max_length` outside 1-500 | Refused | M |
| 65 | Default of the wrong type | Refused | M |
| 66 | Integer default outside the bounds | Refused | M |
| 67 | Choice default not among the options | Refused | M |
| 68 | Email default | Validated and lower-cased | M |
| 69 | Default on a `mailbox` setting | Refused (a live check cannot have a default) | M |
| 70 | Setting types added by a domain app (`mailbox`) | Resolve to a built-in base type plus a live check | M |
| 71 | Manifest using a type whose app is not loaded | Refused as an unknown type | code |
| 72 | Plugin with no settings | Allowed; the page says it has none | code |
| 73 | `required` on a boolean | Allowed; unchecked means false | code |
| 74 | Text without `max_length` | 200 | code |
| 75 | Option longer than 60 characters | Refused | code |

## D. Setting values

| # | Case | Handling | Proof |
| --- | --- | --- | --- |
| 76 | Integer with surrounding spaces | Accepted | M |
| 77 | Integer that is not a number | Refused | M |
| 78 | Integer outside the bounds | Refused with the bound | M |
| 79 | Boolean given for an integer | Refused | M |
| 80 | Decimal for an integer | Refused | M |
| 81 | Choice value not offered | Refused with the options | M |
| 82 | Text longer than allowed | Refused | M |
| 83 | Text with a line break | Refused | M |
| 84 | Email with capitals and spaces around it | Trimmed and lower-cased | M |
| 85 | Email with a space inside | Refused | M |
| 86 | Two addresses separated by a comma | Refused (would become a list) | M |
| 87 | Address without a dot in the domain | Refused | M |
| 88 | Quoted local part | Refused | M |
| 89 | Domain label starting with `-` | Refused | M |
| 90 | Address longer than 254 characters | Refused | code |
| 91 | Unchecked checkbox | False | M |
| 92 | Optional value left empty | None (the key is cleared) | M |
| 93 | Required value missing | Refused | M |
| 94 | Empty value with a default | The default | M |
| 95 | Extra form fields (CSRF token, action) | Ignored | M |
| 96 | Archive address that is not a mailbox here | Refused with the reason | L |
| 97 | Mailbox deleted after install, then re-enable | Refused; plugin stays disabled | L |
| 98 | Several bad settings | All reported, per field | M |
| 99 | Bad settings in the form | Shown on the field, input kept, `aria-invalid` set, nothing installed | V |
| 100 | A setting named `action` or `revision` | Cannot collide: form fields are prefixed `setting__` | code |

## E. Contributions and extension points

| # | Case | Handling | Proof |
| --- | --- | --- | --- |
| 101 | No contributions | Refused (a plugin must do something) | M |
| 102 | More than 10 contributions | Refused | M |
| 103 | Unknown extension point | Refused | M |
| 104 | Unknown key in a contribution | Refused | M |
| 105 | Empty `values` | Refused | M |
| 106 | Key not on the point's allow-list (e.g. `relayhost`) | Refused | M |
| 107 | Value that is not text | Refused | M |
| 108 | Placeholder for an undeclared setting | Refused | M |
| 109 | Unmatched brace | Refused with the fix (`{{`, `}}`) | M |
| 110 | Placeholder that is not a setting key | Refused | M |
| 111 | Literal value invalid for the point | Refused at validation, not later at install | M |
| 112 | Literal value that is a list | Refused | M |
| 113 | Same key set twice in one manifest | Refused | M |
| 114 | `{{` and `}}` | Literal braces | M |
| 115 | Placeholder whose setting is empty | Expands to empty: the key is cleared | M |
| 116 | Line break smuggled through a setting value | Refused by the point | M |
| 117 | Value checked again at render time | Every render re-validates with the point grammar | M |
| 118 | Point missing at install although present at submission | Install refused ("extension point is not available") | code |
| 119 | `ready()` running twice (tests, autoreload) | Re-registration replaces, no duplicates | code |
| 120 | Point registered without key, keys or file | `ValueError` at start-up | code |
| 121 | Key no longer set by any plugin | Rendered as empty, so it is removed | L |
| 122 | Stable output | Keys sorted; unchanged state renders byte-identical text | L |
| 123 | Reader sees a half-written file | Impossible: temp file + atomic rename | code |
| 124 | Nothing changed | File not rewritten (no needless Postfix reload) | L |
| 125 | Plugins touching relaying | Separate file and allow-list; core keys refused in it | P |

## F. Installation state machine

| # | Case | Handling | Proof |
| --- | --- | --- | --- |
| 126 | Install | Only from not installed | L |
| 127 | Enable | Only from disabled | L |
| 128 | Disable | Only from enabled | L |
| 129 | Configure | From enabled or disabled | L |
| 130 | Retry | Only from failed | L |
| 131 | Uninstall | From enabled, disabled or failed | L |
| 132 | Any operation during installing/applying/uninstalling | None offered | L |
| 133 | Request while another is running | "busy", nothing changed | L |
| 134 | Invalid settings | Refused before any state is written | L |
| 135 | Incompatible core | Refused before any state is written | L |
| 136 | Conflict with another plugin | Refused inside the lock; no row created | L |
| 137 | Form older than the last change | Refused, "reload" | L, V |
| 138 | Revision | Increases with every operation | L |
| 139 | Saving identical settings | No operation, no revision bump | L |
| 140 | Configuring a disabled plugin | Saved; nothing written until enabled | L |
| 141 | Install pressed twice | Second refused | L, V |
| 142 | Two requests installing the same plugin at once | Unique id: the loser gets "busy" | code |
| 143 | Operations on different plugins at once (PostgreSQL) | Serialised by one advisory transaction lock, so conflict checks cannot race | code |
| 144 | Same under SQLite (development) | SQLite serialises writers | code |
| 145 | Writing the file fails (disk full, permissions) | Row `failed`, error kept, target kept | L |
| 146 | A failed plugin | Contributes nothing until retried | L |
| 147 | After a failure | Files rebuilt from the database | L |
| 148 | Retry | Heads for the target recorded when it failed | L |
| 149 | Failed uninstall, then retry | Completes the removal | L |
| 150 | Uninstall a failed plugin | Allowed | L |
| 151 | Request died between phases | Next page view finishes it after 120 s | L |
| 152 | Same, nobody visits | Reconcile job finishes it | L |
| 153 | Transient row younger than 120 s | Left alone (it may be running now) | L |
| 154 | Stale threshold | 120 s (`STALE_SECONDS`) | code |
| 155 | Uninstall then install again | Clean second install | L |
| 156 | Values after uninstall | Removed from the file | L |
| 157 | Every operation | Audited with plugin, version, `from -> to` | L |
| 158 | Every failure | Audited with severity `err` | L |
| 159 | Recovery performed by the system | Audited as actor `system` | code |
| 160 | Very long error message | Stored up to 2000 characters | code |

## G. Updates, retirement and compatibility

| # | Case | Handling | Proof |
| --- | --- | --- | --- |
| 161 | Update when nothing newer is listed | Refused | L |
| 162 | Update | Carries current settings over | L |
| 163 | New optional setting | Takes its default | L |
| 164 | Setting removed in the new version | Dropped | code |
| 165 | New required setting without a default | Update refused until a value is given | L |
| 166 | Enabled or disabled before update | Same after | L |
| 167 | Update of a disabled plugin | No conflict check (it writes nothing) | code |
| 168 | Listing retired or built-in removed | Installation keeps rendering from its stored manifest | L |
| 169 | Retired plugin | Can still be disabled, enabled and uninstalled | L |
| 170 | Retired plugin | Cannot be installed afresh | L |
| 171 | Core older than `requires_core` | Install and update refused | L |
| 172 | Development build without a version | Treated as compatible | L |
| 173 | `git describe` style version (`v0.0.4-2-g…`) | Parsed | L |
| 174 | Incompatible plugin in the catalog | Marked "Needs a newer ifinmail"; install button disabled | code |
| 175 | Older version in the catalog | Never offered as an update | L |

## H. Submissions

| # | Case | Handling | Proof |
| --- | --- | --- | --- |
| 176 | Invalid manifest submitted | Refused with every problem | S, V |
| 177 | Submitted, not approved | Not in the catalog | S |
| 178 | Approve | Explicit only; reviewer, time and note recorded | S |
| 179 | Approve twice, or reject after approval | Refused | S |
| 180 | Reject without a note | Refused | S, V |
| 181 | Same version after a rejection | May be resubmitted | S |
| 182 | Submitter withdraws | Allowed | S |
| 183 | Someone else withdraws | Refused unless a reviewer | S |
| 184 | Reviewer withdraws | Allowed | S |
| 185 | Retire | Unlisted; installed copies keep working | S, L |
| 186 | Same id and version live twice | Refused by the service and by a partial unique index | S |
| 187 | Version not above the published one | Refused | S |
| 188 | Built-in id | Refused | S |
| 189 | Core changed since submission | Validated again at approval | S |
| 190 | Malformed or unknown submission id | Not found (404 on pages) | S, V |
| 191 | Very long notes | Trimmed to 2000 characters | S |
| 192 | Reviewer approving their own submission | Allowed and audited (v1, internal, few users: no extra gate) | decision |

## I. Console and security

| # | Case | Handling | Proof |
| --- | --- | --- | --- |
| 193 | Finding the Marketplace | Sidebar item directly after Settings | V |
| 194 | Who can do what | Browse and submit: console access; install and review: `system.manage` | V |
| 195 | Anonymous or non-staff | Sent to sign-in | V |
| 196 | Developer posting "approve" | 403 | V |
| 197 | Refresh after an action | Every POST redirects; a repeat is refused, not repeated | V |
| 198 | GET on an action URL | Redirected to the page, never a server error | V |
| 199 | Unknown tab | Discover | V |
| 200 | Unknown plugin | 404 | V |
| 201 | HTML or script in a manifest | Escaped everywhere | V |
| 202 | Cross-site form posts | CSRF token on every form | code |
| 203 | Uploaded manifest | At most 32 KiB, read as bytes | code |
| 204 | Submit with nothing | "Paste a plugin.toml or choose the file" | V |
| 205 | Has Postfix applied it? | Applied / Applying / Not applied / Unknown, from the acknowledgement | L |
| 206 | Failed or unapplied plugin | System health error or warning with a link | V |
| 207 | No plugins installed | System health says nothing | code |

## J. Postfix watcher and background work

| # | Case | Handling | Proof |
| --- | --- | --- | --- |
| 208 | File unchanged | One hash per 10 s tick, no `postconf` | P |
| 209 | Acknowledgement file lost | Written again without re-applying | P |
| 210 | Empty value | `postconf -X` (Postfix default restored) | P |
| 211 | Status directory missing | Settings still applied | P |
| 212 | Core overrides file setting a plugin key | Ignored | P |
| 213 | Beat job naming an unregistered task | Test fails (autodiscovery is an explicit list) | B |
| 214 | File drifted or deleted | Reconcile rewrites it within 10 minutes | L |
| 215 | Postfix container recreated | Its state file is gone, so the next tick re-applies everything | decision |

Decisions not in the table: v1 sources are internal only (built-ins and approved submissions);
no automatic approval; the plugin layer adds no third-party package; DKIM-style secrets are never
plugin settings; a plugin can only act through registered extension points.
