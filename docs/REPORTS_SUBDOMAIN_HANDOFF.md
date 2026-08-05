# Handoff: put the monthly reports on a real subdomain

**Written:** 2026-08-04 (Georgia time, UTC+4)
**For:** the terminal that holds website / DNS access
**Repo this document lives in:** `geganoza/MARTIVI-Presentations`

Every fact below was verified live against Vercel, DNS and the cPanel API on 2026-08-04.
Anything not verified is marked `(inferred)` or `UNKNOWN`. Do not fill an UNKNOWN with a guess.

---

## 0. AS BUILT (2026-08-04, later the same day)

**This is done, and it works.** The implementation deviated from the recommendation below in
one significant way, which created a live data exposure. Read this section before section 1.

### What shipped

| Thing | Value |
|---|---|
| Domain chosen | **`reports.casacalda.com`** (a client-owned domain, not a MARTIVI one) |
| Added to Vercel | `casacalda.com`, attached to project `martivi-presentations` |
| DNS | `CNAME reports -> cname.vercel-dns.com.` Resolves to `76.76.21.22`, `66.33.60.129` |
| TLS | valid, serving HTTP 200 |
| Landing page | host-scoped redirect in `vercel.json`: on host `reports.casacalda.com`, `/` → `/casa-calda` (307) |
| New content | `casa-calda/index.html`, `casa-calda/july-2026.html`, `casa-calda/june-2026.html` |
| Old URL | `martivi-presentations.vercel.app/thermorum/july-2026` still returns 200. Nothing broke. |

The CNAME pattern and the host-scoped landing redirect were both done well. The redirect trick
is a genuinely good addition that was not in the original plan and is worth reusing.

### ✅ RESOLVED 2026-08-04 23:25 Georgia time, commit `443908a`

The exposure described below was real and is now **closed**, by a better mechanism than the one
this document originally proposed. Keeping the problem description because the reasoning is
what stops it recurring on the next client domain.

**What was done:** `middleware.ts` (42 lines) implements a **host-scoped allowlist**. On host
`reports.casacalda.com`, only `/`, `/casa-calda` and `/casa-calda/*` are served; everything
else returns a bare `404`, with no hint the path exists elsewhere. All other hosts pass through
untouched. The interim 54-line deny-list of host-scoped redirects in `vercel.json` was removed
in the same commit.

**Why this beats the deny-list this doc first suggested:** an allowlist fails closed. Every new
directory added to the repo is denied on the client host by default, so nobody has to remember
to add a rule. The deny-list leaked by default.

**Verified live after the fix, 9 bypass attempts, all 404:**

| Probe | Result |
|---|---|
| `/hr`, `/autograph`, `/interview`, `/thermorum/july-2026` | 404 |
| `/thermorum/july-2026.html` (cleanUrls) | 308 → same host → **404** |
| `/hr/`, `/hr/index.html` (trailingSlash) | 308 → same host → **404** |
| `//thermorum/july-2026` (double slash) | 308 → same host → **404** |
| `/THERMORUM/july-2026` (case) | 404 |
| `/casa-calda/../thermorum/july-2026` (traversal) | 404 |
| `/casa-calda/%2e%2e/thermorum/july-2026` (encoded traversal) | 404 |
| `/casa-calda/..%2fthermorum%2fjuly-2026` (encoded slash) | 404 |
| `Host: reports.casacalda.com:443` header | 404 |
| `/casa-calda/july-2026` (must still work) | **200** |

Note the 308s: Vercel's `cleanUrls` / `trailingSlash` normalization runs **before** middleware,
so extension and slash variants redirect first. They stay on the same host and then hit the
404, so they are safe. Worth knowing if you ever debug this, because a 308 looks like a hole
until you follow it.

**Main host unaffected:** `martivi-presentations.vercel.app` still returns 200 on `/`,
`/thermorum/july-2026`, `/hr`, `/interview` and `/casa-calda/july-2026`.

**Still owed:** one Vercel project per client, so cross-client leakage is structurally
impossible rather than middleware-dependent. The commit message says so too. Until then, this
middleware is the only thing standing between a client domain and other clients' data, so
**anyone editing `middleware.ts` must re-run the probe table above.**

---

### 🔴 P0 (historical, now fixed): the client domain served other clients' data

Section 3 recommended a MARTIVI-owned domain and warned against a client domain, precisely
because this project hosts more than one client. A client domain was used, and the host-scoped
redirect only covers `/`. Every other path still serves on Casa Calda's own domain. Verified
live:

| URL on `reports.casacalda.com` | Status | What it serves |
|---|---|---|
| `/hr` | **200**, 392 KB | `<title>MARTIVI HR — Candidates</title>`. Candidate personal data. **Content verified.** |
| `/thermorum/july-2026` | **200** | `<title>Thermorum - July 2026 Social Media Report</title>`. Another client's ad spend. All 8 monthly Thermorum reports were reachable. **Content verified.** |
| `/interview` | **200** | Candidate booking page |
| `/autograph` | 200 status | ⚠️ [corrected 2026-08-05] **Status only, no content.** The body is Vercel's `NOT_FOUND` page. `autograph/` is untracked AND listed in `.vercelignore`, so the deck was never actually served. My original entry here claimed it exposed client material; that was inferred from the status code and was wrong. Lesson: on this project a 200 does not prove content, check the body. |
| `/thermorum` | 404 | (no directory index, but the reports underneath it served) |
| `/api` | 404 | |

So Casa Calda's own domain currently publishes Thermorum's confidential ad performance and
MARTIVI's HR candidate dashboard. Anyone who thinks to try the path gets it. Fix before this
URL is shared with the client.

### How it was fixed (see the RESOLVED block above for the verified detail)

A host-scoped **allowlist in `middleware.ts`** returning 404 for everything outside
`/casa-calda/*`. That is the pattern to reuse.

A deny-list of host-scoped `redirects` in `vercel.json` was tried first and then removed. Do not
reach for it again: it enumerates what to hide, so every directory added to the repo later is
exposed by default until someone remembers to add a rule.

The structural fix, still owed, is one Vercel project per client. Then no middleware is load
bearing.

### Consequences for the rest of this document

- Section 3's decision is **resolved differently than recommended**: a client domain was used.
  The MARTIVI DIGITAL vs MARTIVI CONSULTING question is therefore moot for Casa Calda, but
  returns the moment a second client needs a reports host. Do not attach another client domain
  to this project until the P0 above is fixed.
- Step D is **still open**, and the email script is more Thermorum-bound than step D says.
  Two lines are hardcoded, not one:

  ```python
  24: BASE_URL = "https://martivi-presentations.vercel.app"
  50: link = f"{BASE_URL}/thermorum/{slug}-{args.year}"
  ```

  Line 50 pins the **client path**, so `send_report_email.py` can only ever email a Thermorum
  report. Casa Calda has no report email at all yet. Both the host and the path need to become
  per-client before Casa Calda gets an automated email.

  Silver lining: because `BASE_URL` was never changed, Thermorum's email still links the
  neutral `vercel.app` host rather than Casa Calda's domain. Leave it that way until the
  per-client refactor.

- Root `index.html` contains **no** links to `casa-calda/` (verified: 0 matches). Casa Calda's
  reports are reached only via the host redirect to `/casa-calda`. That is good isolation and
  should stay: adding Casa Calda cards to the root index would list them for anyone browsing
  the Thermorum-facing host.

- The 1st-of-month cron is **safe**: the anchor `    <div class="presentations">` still appears
  exactly once in `index.html` (verified 2026-08-04 after the Casa Calda work landed).
- Trap 3 and trap 5 below were not hypothetical. They both happened.

---

## 1. Goal

Today the monthly client reports are served from a path on Vercel's own domain:

```
https://martivi-presentations.vercel.app/thermorum/july-2026
```

Wanted: the same reports on a branded subdomain, keeping the same path layout, so each
client gets its own section.

```
https://reports.martividigital.com/thermorum/july-2026
https://reports.martividigital.com/casa-calda/july-2026     (once Casa Calda reports exist)
```

Success means: the branded URL serves the existing reports over valid HTTPS, the old
vercel.app URLs keep working, and the monthly automation still deploys without changes to
its logic.

**Out of scope:** building the Casa Calda report pipeline itself. That is a separate piece of
work. This task only prepares the hosting so a `/casa-calda/` section can be dropped in.

---

## 2. Verified current state

| Thing | Value | How it was verified |
|---|---|---|
| GitHub repo | `geganoza/MARTIVI-Presentations` | `git remote -v` |
| Vercel project | `martivi-presentations` | `.vercel/project.json` |
| Vercel project ID | `prj_6sQZpkco5uUOEw4lhyO5bGGd242A` | `.vercel/project.json` |
| Vercel org / team | `team_ZGPjeMwrMWRLANzpUfTWCtmQ` (`giorgis-projects-cea59354`) | `.vercel/project.json` |
| Current domains on project | only `martivi-presentations.vercel.app` | `vercel project ls` |
| Report files | `thermorum/<month>-<year>.html`, 8 files, `december-2025` to `july-2026` | `ls thermorum/` |
| URL form | `.html` is dropped because `vercel.json` sets `cleanUrls: true` | `vercel.json` |
| Access control | none. Reports are fully public static HTML | `vercel.json` has no auth config |
| Deploy trigger | git push to `main`. Vercel builds from the repo | `.github/workflows/thermorum-monthly-report.yml` |
| Monthly automation | GitHub Actions cron `0 6 1 * *` UTC = **10:00 on the 1st, Georgia time** | workflow line 5-6 |

### Existing sections in the repo root

`api/`, `autograph/`, `hr/`, `interview/`, `scripts/`, `thermorum/`, `index.html`, `vercel.json`

Note that `interview/` and `api/` are a live booking app on this same project, with a rewrite
rule in `vercel.json`. Attaching a new domain exposes those paths on the new domain too.
See trap 6.

### DNS reality

| Domain | Nameservers | Apex points to | Notes |
|---|---|---|---|
| `martividigital.com` | `ns1.hostnodes.ge`, `ns2.hostnodes.ge` | `195.54.179.33` (hostnodes shared hosting) | Vercel reports the apex as NOT configured for Vercel, which is fine and must stay that way |
| `martiviconsulting.com` | same | Vercel project `martivi-consulting-website` | |
| `thermorum.com` | same | `app.thermorum.com` on Vercel | |
| `bkhipsters.com` | same | Vercel | |

**DNS is not managed by Vercel.** All four domains show `Third Party` nameservers. Records must
be created at hostnodes.

**`reports.martividigital.com` does not resolve today.** Verified with `dig +short
reports.martividigital.com`, which returned nothing. The name is free.

### Who controls the DNS zone

The zone lives on the hostnodes cPanel account whose API token is already in the operator's
global config (`~/.claude/CLAUDE.md`, section "cPanel API (bebias.ge)"). Host
`cp8.co.hostnodes.ge:2083`, user `bebias`. **Do not paste the token into this repo or any
committed file.**

That account hosts the zone. Verified:

```
GET /execute/DomainInfo/list_domains
-> main_domain: bebias.ge
   addon_domains: catshop.ge, gngrp.ge, martiviconsulting.com, martividigital.com
   sub_domains: ai.martividigital.com
```

Both write and read DNS functions are present on this cPanel build:

- `DNS::parse_zone?zone=martividigital.com` works (returns base64-encoded zone lines)
- `DNS::mass_edit_zone` exists (probing it without arguments returns `Provide the "zone"
  argument.`, not "function not found")
- `DNS::list_zones` does **not** exist on this build. Do not use it.

### Precedent to copy

Two subdomains on these zones already point at Vercel, using two different and both-valid
patterns:

| Subdomain | Record | Resolves to |
|---|---|---|
| `app.thermorum.com` | `CNAME cname.vercel-dns.com` | `76.76.21.241`, `66.33.60.193` |
| `ai.martividigital.com` | `A 76.76.21.21` | Vercel anycast, project `martividigital-ai-page-anh1` |

Use the **CNAME** pattern. It is Vercel's current recommendation for subdomains and survives
Vercel changing its IPs.

---

## 3. Decision needed from the user before step 1

**Which domain should host the reports?** Both candidates sit on the same cPanel account, so
the work is identical either way. This is a branding call, not a technical one.

| Option | Argument for |
|---|---|
| `reports.martividigital.com` **(recommended)** | MARTIVI DIGITAL is the entity that delivers the ads and reporting work. Thermorum's retainer and monthly billing run through MARTIVI DIGITAL. |
| `reports.martiviconsulting.com` | Casa Calda invoices are the MC-2026 series, which is MARTIVI CONSULTING. If reports are framed as a consulting deliverable, this fits better. |

There is a genuine wrinkle: the two clients sit under two different legal entities. Ask the
user which entity should own the reports subdomain. Recommend `martividigital.com` and move
on if they have no preference.

**Do not use a client domain** such as `thermorum.com`. The subdomain will host more than one
client, and a Thermorum-branded host serving Casa Calda numbers is wrong.

The rest of this document assumes `reports.martividigital.com`. Substitute if the user picks
otherwise.

---

## 4. Implementation

### Step A: attach the domain to the Vercel project

```bash
cd ~/Projects/AZON/MARTIVI-Presentations
vercel domains add reports.martividigital.com martivi-presentations
```

Verified syntax: `vercel domains add domain project [options]` (from `vercel domains add --help`).

Vercel will report the domain as added but unverified, and will tell you which record it
wants. Expect it to ask for a CNAME to `cname.vercel-dns.com`.

**Verify this step alone:**

```bash
vercel domains inspect reports.martividigital.com
```

It should list `martivi-presentations` under Projects.

### Step B: create the DNS record at hostnodes

Add to the `martividigital.com` zone:

```
Name:  reports
Type:  CNAME
Value: cname.vercel-dns.com.
TTL:   300   (raise later if you like; 300 keeps the first verification quick)
```

Two ways to do it, pick either:

1. **cPanel UI**, which is lower risk: log into `cp8.co.hostnodes.ge:2083` as `bebias`, open
   Zone Editor, select `martividigital.com`, Add Record.
2. **cPanel API**, using `DNS::mass_edit_zone`. Read the current zone first with
   `DNS::parse_zone?zone=martividigital.com` and preserve the serial. `mass_edit_zone` can
   overwrite a zone, so read before you write.

You do **not** need to create a cPanel "subdomain" entry with a document root. That is only
for content hosted on hostnodes itself. This subdomain's content lives on Vercel, so a DNS
record is all that is required. (`ai.martividigital.com` exists as a cPanel subdomain for
historical reasons; do not copy that part.)

**Verify this step alone:**

```bash
dig +short CNAME reports.martividigital.com     # expect cname.vercel-dns.com.
dig +short reports.martividigital.com           # expect Vercel anycast IPs
```

Allow a few minutes. TTL on the zone's existing records is the floor for propagation.

### Step C: confirm TLS and routing

Vercel provisions a Let's Encrypt certificate automatically once the record resolves. This is
usually under a minute, occasionally several.

```bash
curl -sI https://reports.martividigital.com/thermorum/july-2026 | head -5
```

Expect `HTTP/2 200`. If you get a certificate error, wait and retry before changing anything.

Also confirm the old URL still works, because the email history and any existing links depend
on it:

```bash
curl -sI https://martivi-presentations.vercel.app/thermorum/july-2026 | head -3
```

### Step D: update the one hardcoded URL

`scripts/send_report_email.py:24`

```python
BASE_URL = "https://martivi-presentations.vercel.app"
```

Change to the new subdomain. This is the URL that goes into the monthly report email sent to
the client, so it is the single most visible consequence of this whole task.

Grep confirmed this is the **only** hardcoded production URL in `scripts/` and `index.html`.

**Verify:**

```bash
grep -rn "vercel.app" scripts/ index.html
```

Should return nothing after the edit.

### Step E: decide on the apex and the old host

Leave both alone unless the user asks otherwise:

- `martividigital.com` apex keeps pointing at hostnodes (`195.54.179.33`). Do not add the
  Vercel apex A record that `vercel domains inspect` suggests. Doing so would take the main
  martividigital.com website offline.
- `martivi-presentations.vercel.app` keeps working. Vercel serves all attached domains
  simultaneously. No redirect is needed, and adding one would break nothing but is unnecessary.

---

## 5. Traps

1. **The monthly automation edits `index.html` by exact string match.**
   `scripts/run_monthly_pipeline.py:71` looks for the anchor:

   ```python
   anchor = '    <div class="presentations">\n'
   ```

   and raises `SystemExit("index.html anchor not found")` if it is missing. Four leading
   spaces, exact. If you restructure `index.html` to group reports per client, **that exact
   line must survive**, or the 1st-of-month cron fails and no report ships. Verified at
   `scripts/run_monthly_pipeline.py:57-76`.

2. **Never run `vercel --prod` on this project.** Deploys come from git push to `main`.
   `vercel --prod` uploads your **local folder**, not the repo, so a stale clone silently
   replaces production. This exact mistake 404'd a live client report for 90 minutes on
   2026-08-03. Documented in the MAIA repo, commit `aa65763`
   ("docs(booking-page): record the vercel deploy-source trap"); this repo carries the
   follow-up `33f0781 chore: remove deploy-source marker`. Push, never deploy manually.

3. **The new domain exposes every path on the project**, not just `/thermorum/`. That includes
   `/interview` (the candidate booking page) and `/api/*`. So
   `reports.martividigital.com/interview` will answer. Decide whether that is acceptable. If
   not, the booking app needs splitting into its own Vercel project, which is a bigger job
   and should be raised with the user rather than improvised.

4. **`cleanUrls: true` means the extensionless path is canonical.** Link `/thermorum/july-2026`,
   not `/thermorum/july-2026.html`. Both resolve, but keep the repo consistent.

5. **Reports are public and unauthenticated.** Anyone with the URL sees the numbers. Once a
   second client is added, Thermorum's URL and Casa Calda's URL are both guessable from each
   other (`/thermorum/july-2026` vs `/casa-calda/july-2026`). If client confidentiality
   matters, that is a real problem and needs raising with the user. It is not made worse by
   this task, but a branded subdomain makes the URLs easier to guess than the vercel.app host did.

6. **Vercel env changes only reach new deployments.** Not relevant to DNS, but if you touch any
   project env var while in there, a redeploy is required for it to take effect.

7. **Georgian text, if you add any**, must be produced via the `ka` tool, never hand-written.
   See the operator's global instructions.

---

## 6. Verification checklist

```bash
# DNS
dig +short CNAME reports.martividigital.com          # cname.vercel-dns.com.

# Vercel knows about it
vercel domains inspect reports.martividigital.com    # lists martivi-presentations

# Reports serve over TLS on the new host
curl -sI https://reports.martividigital.com/thermorum/july-2026 | head -3    # HTTP/2 200
curl -sI https://reports.martividigital.com/                     | head -3    # HTTP/2 200

# Old host still serves
curl -sI https://martivi-presentations.vercel.app/thermorum/july-2026 | head -3

# Apex untouched
dig +short martividigital.com                        # still 195.54.179.33

# No stale URLs left in code
grep -rn "vercel.app" scripts/ index.html            # no output

# The cron's anchor still exists
grep -c '    <div class="presentations">' index.html # 1
```

---

## 7. Definition of done

- [ ] User has chosen the domain (`martividigital.com` vs `martiviconsulting.com`)
- [ ] `reports.<chosen>.com` attached to Vercel project `martivi-presentations`
- [ ] CNAME to `cname.vercel-dns.com` live in the hostnodes zone
- [ ] Valid HTTPS, `HTTP/2 200` on a real report URL
- [ ] `martivi-presentations.vercel.app` still serves
- [ ] Apex `martividigital.com` still resolves to `195.54.179.33`
- [ ] `scripts/send_report_email.py:24` `BASE_URL` updated, no `vercel.app` left in code
- [ ] `index.html` anchor `    <div class="presentations">` intact
- [ ] Changes committed and pushed to `main`, Vercel deploy green
- [ ] Decision recorded on whether `/interview` should be reachable on the new host

---

## 8. Open questions for the user

1. Which entity owns the reports subdomain: MARTIVI DIGITAL or MARTIVI CONSULTING?
2. Is it acceptable that `/interview` and `/api/*` become reachable on the reports subdomain?
3. Should report URLs stay public and guessable, or does client confidentiality require access
   control? (Vercel offers password protection and Vercel Authentication on paid plans;
   whether the current plan includes it is UNKNOWN, check before promising it.)
4. Once Casa Calda reports exist, should `index.html` split into per-client sections, or stay a
   single reverse-chronological list? This affects trap 1.
