# Data Source Licensing & Public-Launch Compliance

**Status:** Review for taking Jeanne Machine from an internal, password-gated tool
to a **public, for-profit** website.
**Last reviewed:** 2026-06 · **Owner:** Engineering (confirm flagged items with Legal before launch)

> This is a compliance survey of each data provider's terms, not legal advice.
> Two items (LegiScan, Legistar) should get written sign-off before a public
> launch — see [Action items](#action-items).

## How the tool uses the data (this drives the analysis)

- The public site serves visitors from **our own database**, showing
  **AI-generated summaries + a link back to the source** — it does not
  live-proxy provider APIs per page view, and does not reproduce full statutory
  text on the page. API keys stay **server-side**; provider calls happen only in
  background ingestion. This keeps us under every provider's rate cap and out of
  most redistribution concerns.
- The backend stores source **metadata and text** (`raw_document.raw_text`,
  `policy_item.full_text`). Caching/local storage is permitted by every source
  below (several explicitly encourage it).
- Going public removes the password gate, so terms that bind **public
  redistribution** now apply where they didn't for an internal tool.

## Summary table

| Source | Commercial + public OK? | License / status | Attribution | Verdict |
|---|---|---|---|---|
| Congress.gov | Yes | US public domain / CC0 | Not required; no logos/endorsement | 🟢 Go |
| Federal Register | Yes | US public domain | Not required; **no NARA/OFR seals** | 🟢 Go |
| BLS (CPI) | Yes | Public domain | Citation requested, not required | 🟢 Go |
| WA Legislature (WSL) | Yes | Statutes not copyrightable; no explicit license | Not required | 🟢 Go (mild) |
| OpenStates / Plural | Yes | Public-domain dedication, "no copyright claim" | Not required; **no implied endorsement**; paid tier for volume | 🟡 Conditions |
| LegiScan | Yes | **CC BY 4.0** | **Required** — credit "LegiScan LLC" + license link | 🟡 Conditions + confirm |
| CourtListener (Free Law Project) | Yes | Opinions public domain; FLP content **CC BY-ND 4.0** | Required; **ND term** vs. AI summaries | 🟡 Conditions + confirm |
| Legistar / Granicus | Unknown | **No public API terms found** | Unknown | 🔴 Clarify before launch |

## Per-source detail

### 🟢 Congress.gov API (Library of Congress)
- **Public domain / CC0.** LOC: works by federal employees "are in the public
  domain… available for worldwide use and reuse under CC0 1.0 Universal."
  OPEN Government Data Act framing: "no restrictions on copying, publishing,
  distributing… for any purpose, commercial or non-commercial."
- **Attribution:** not legally required. Do **not** use LOC/Congress logos or
  trademarks or imply endorsement.
- **Caching:** permitted. **Rate limit:** 5,000 req/hour per api.data.gov key —
  keep the key server-side, serve visitors from our DB.
- **robots.txt:** if we ever crawl the *website* (not the API), honor
  `congress.gov/robots.txt` or get blocked.
- Sources: congress.gov/help/using-data-offsite; loc.gov copyright policy;
  github.com/LibraryOfCongress/api.congress.gov README (rate limit, page-verified).

### 🟢 Federal Register API (OFR / NARA)
- **Public domain.** "Any person may reproduce or republish any material
  appearing in… the Federal Register… with no restrictions regarding what is
  reproduced, who can reproduce it, or where it can be reproduced."
- **Hard rule:** "Republishers of Federal Register material are not permitted to
  use official NARA or OFR logos or seals." No implied endorsement.
- **Attribution:** not required. **Caching:** explicitly encouraged. **API key:**
  none required; no published numeric rate limit — cache aggressively.
- Sources: federalregister.gov/reader-aids/developer-resources/rest-api.

### 🟢 BLS Public Data API (Bureau of Labor Statistics)
- **Public domain.** "everything that we publish… is in the public domain,
  except for previously copyrighted photographs and illustrations." "You are free
  to use our public domain material without specific permission."
- **Attribution:** requested, not required — "we do ask that you cite the Bureau
  of Labor Statistics as the source."
- **Rate limit:** 25/day unregistered, **500/day** with a free key (+50 requests
  per 10 seconds). Register a key; keep it server-side.
- **Open item:** the developer Terms-of-Service page could not be page-read
  (403); its specific "no implied endorsement" clause is unverified. Don't imply
  BLS endorsement as standard practice.
- Sources: bls.gov/opub/copyright-information.htm; bls.gov/bls/linksite.htm.

### 🟢 Washington State Legislature Web Services (WSL) — mild
- **Effectively open.** "The Legislature is providing information free of charge
  to all interested parties… allowing agencies, interest groups, and the general
  public to obtain real-time legislative information for their in-house
  applications." Statutory text isn't copyrightable.
- **Mild flags:** site footer says "© WA State Legislature — All Rights
  Reserved" (most plausibly covers site design/branding, not the legislative
  text) and the policies are "not… legally binding… subject to change." No
  explicit public-domain license — permission is inferred, not granted in
  writing. No published rate limits — self-throttle.
- Sources: wslwebservices.leg.wa.gov/lwsDetails.htm; RCW 1.08.

### 🟡 OpenStates / Plural
- **Public-domain dedication.** "We make no copyright claim over any of the data
  we collect & publish." "Unless otherwise noted data is provided under a public
  domain dedication."
- **Attribution:** "No attribution is required… Of course, attribution is always
  appreciated but **no affiliation or endorsement may be implied** on your
  derivative product." → Do not imply Plural/OpenStates endorsement.
- **Caching:** permitted (no restriction; bulk data offered for local storage).
- **Rate limit:** free tier **250 req/day** (`Tier("default",10,0,250)` in their
  api-v3 source). Fine for background ingestion; a for-profit product at volume
  should move to a **paid commercial tier** (Plural explicitly gates
  commercial/high-volume use behind paid tiers).
- Sources: openstates.org/tos/; open.pluralpolicy.com/data/;
  help.pluralpolicy.com (page-verified from their repo).

### 🟡 LegiScan — *the primary source*
- **Licensed CC BY 4.0.** "LegiScan API by LegiScan LLC is licensed under
  CC BY 4.0." Offered to "both public and private entities" to "power product
  offerings." CC BY 4.0 permits commercial use, public display, adaptation
  (AI summaries), and storage.
- **Attribution is MANDATORY (the "BY").** Credit **"LegiScan LLC"** with a link
  to the CC BY 4.0 license (and, reasonably, the source). ToS §7.4: do not
  "remove, obscure, or alter any proprietary rights notices."
  - **Gap today:** our items link to the state legislature page (`state_link`),
    not LegiScan, and there is currently **no LegiScan credit on the site.** The
    site footer added alongside this doc closes that gap.
- **Rate limit:** free public key = **30,000 queries/month; the account is
  suspended on overage and extra keys are forbidden.** Guarded by
  `settings.legiscan_monthly_budget` (27,000). We sync to our DB, so visitor
  traffic never hits their API — do not change that.
- **Risk to confirm:** the permissive CC BY 4.0 grant conflicts with LegiScan's
  *generic* website ToS §3.5 ("will not reproduce, duplicate, copy, sell, trade
  or resell the Services"). The CC license should control for the data, but get a
  one-line written confirmation from **sales@legiscan.com** that CC BY 4.0
  governs public-facing use before a for-profit launch.
- Sources: api.legiscan.com/dl/LegiScan_API_User_Manual.pdf (page-verified);
  legiscan.com/legiscan and legiscan.com/terms-of-service (via Wayback,
  page-verified). Not verified: legiscan.com/pricing/api; exact preferred
  attribution string.

### 🟡 CourtListener (Free Law Project)
- **Split license.** Raw court opinions are **public domain** (safe to summarize
  and redistribute). FLP's **own value-added content** (headnotes, their
  summaries, curated metadata) is **CC BY-ND 4.0** — the **"No Derivatives"**
  term is in tension with publishing AI summaries built from *their* text.
- **Safe path:** summarize the **public-domain opinion text**, not FLP's
  annotations; **credit Free Law Project** (the "BY").
- **Rate limit (tightened 2026):** ~5/min, 50/hr, **125/day** for default/anon;
  higher limits require a **membership or commercial agreement + API token**.
- **Caching:** permitted (bulk data offered for local storage).
- Sources: courtlistener.com/help/api/; free.law/2026/05/07 (membership/API);
  site footer CC BY-ND notice (snippet-verified — confirm scope with FLP).

### 🔴 Legistar Web API (Granicus) — clarify before launch
- **No public terms of service** governing third-party commercial reuse could be
  found; the docs cover mechanics only. The API only returns records "marked as
  public and available for view on InSite," and responses cap at 1,000 items.
- **Reuse rights realistically flow from each municipality's public-records
  posture**, not from a Granicus grant — there is neither explicit permission nor
  explicit prohibition, and some clients require API tokens per their own policy.
- **Action:** get written confirmation from Granicus and/or rely on each
  jurisdiction's public-records status; do not assume a blanket redistribution
  right for a public commercial product.
- Sources: webapi.legistar.com/Help, /Home/Examples.

## Cross-cutting rules for the public site

1. **Never use government logos or seals** (NARA, OFR, Library of Congress) and
   never imply government endorsement. (Explicit hard rule for federal sources.)
2. **Show a data-source attribution footer** — required for LegiScan (CC BY) and
   CourtListener (BY), appreciated everywhere else. Implemented in
   `web/app/components/SiteFooter.tsx`.
3. **Keep API keys server-side and serve visitors from our DB.** Already the
   design; it is what keeps us within every rate limit.
4. **Do not republish CourtListener's proprietary annotations verbatim** — work
   from the public-domain opinion text.
5. **State that summaries are AI-generated and not legal advice**, and that no
   affiliation with or endorsement by any source is implied.

## Action items

- [ ] **Legal:** confirm CC BY 4.0 governs public use with LegiScan
      (sales@legiscan.com) — resolves the CC-vs-ToS §3.5 tension.
- [ ] **Legal:** confirm Legistar/Granicus reuse rights (or scope to
      jurisdictions whose public-records status clearly permits it).
- [ ] **Eng:** ship the data-source attribution footer (done alongside this doc).
- [ ] **Eng:** if CourtListener is used at public scale, obtain a membership/
      commercial agreement + API token, and ensure summaries derive from
      opinion text, not FLP annotations.
- [ ] **Eng/Product:** move OpenStates to a paid commercial tier before
      significant public volume.
- [ ] **Eng:** register a BLS API key (500/day tier).

## Verification note

OpenStates and LegiScan were **page-verified** (their own ToS/source, and the
LegiScan manual PDF + Wayback snapshots). The federal `.gov` pages blocked
automated fetching, so those quotes are **search-snippet-verified** — highly
consistent and low-risk (public-domain status is statutory), but not byte-exact.
For litigation-grade certainty, have Legal open the cited pages directly.
