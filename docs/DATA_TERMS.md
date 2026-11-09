# Data terms

What each data source allows, what it asks for, and how Rondo follows it. Read on 8 Nov 2026, before any data was downloaded. Each section names the exact text it was read from. Where a term is open to interpretation, the section says so and gives the reading Rondo follows until MJ decides otherwise.

**Rules that apply to every source**

- Raw provider files never go into git. They live under `data/` (gitignored), and CI uses small synthetic fixtures only.
- Every page of the site and the README carry the disclaimer and the credits below. A test (`tests/core/test_public_text.py`) fails if the README or the site footer drifts from this file.
- No player who was a minor during a covered season, and no player without a verified birth date, is named in anything published.
- Birth dates are used only to decide who may be named. Rondo never publishes a player's birth date.

## Disclaimer and credits (canonical text)

The README and the site footer copy these strings exactly.

<!-- BEGIN PUBLIC TEXT -->
| Key | Text | Link |
|---|---|---|
| disclaimer | Independent project by Moulik Jain. Not affiliated with any data provider, league, federation or club. | |
| statsbomb | Event and 360 data: StatsBomb open data. | https://github.com/statsbomb/open-data |
| wyscout | Event data: Wyscout open data (Pappalardo et al., 2019, Scientific Data 6:236), CC BY 4.0, converted and aggregated by Rondo. | https://doi.org/10.6084/m9.figshare.c.4415000.v5 |
| dfl | Tracking and event data: DFL open data (Bassek, Rein, Weber & Memmert, 2025, Scientific Data 12:195), CC BY 4.0, converted and aggregated by Rondo. | https://doi.org/10.6084/m9.figshare.28196177.v1 |
| wikidata | Player identity and birth dates used for the minors rule: Wikidata (CC0). | https://www.wikidata.org |
| ccby | Licence for the CC BY 4.0 datasets above. | https://creativecommons.org/licenses/by/4.0/ |
<!-- END PUBLIC TEXT -->

The StatsBomb logo must also appear wherever analysis is published (below). MJ downloaded it from StatsBomb's media pack. The two versions the site uses are in `web/public/brand/statsbomb/`; the rest of the media-pack files are kept in `docs/brand/statsbomb/` so they aren't deployed. The README and the site footer show the default version on light backgrounds and the reversed version on dark ones, and a test checks both are in place.

---

## StatsBomb open data

**Read from:** `README.md` and `LICENSE.pdf` ("StatsBomb Public Data User Agreement", "last updated 8 September 2023") in https://github.com/statsbomb/open-data at commit `4b73468`.

**What's allowed**
- Use for analysis and research, and to share ideas and understanding of the data (§1.1).
- Analysis and conclusions made from the data "may be shared publicly" (preamble).

**What's not allowed**
- §1.2.1: "edit, distort, distribute, reproduce, sell or in any way provide the data to any external or third party".
- §1.2.2: "commercially exploit the data or any analysis derived from the use of the Service".
- §1.2.4: publish material "that might be defamatory or damaging to any individual or organisation".
- §7: the data is StatsBomb's property. No modifying, transferring, distributing or licensing it without StatsBomb's written consent.

**Attribution and logo**
- README: anyone who publishes, shares or distributes research, analysis or insights based on the data must "state the data source as StatsBomb and use our logo", from the media pack.
- §1.4: every publication of analysis must be accredited with the StatsBomb brand logo.
- So the README and every site page carry the text credit above **and** the StatsBomb logo. This is the one provider logo Rondo shows, because the terms require it.
- The media-pack link (https://statsbomb.com/media-pack/) now redirects to an asset portal at hudl.bynder.com, which needs a browser. MJ downloads the logo and checks any usage guidance that comes with it. Rondo won't fetch it automatically.

**Redistribution, derived numbers and player names**
- Raw StatsBomb files are never committed or served.
- *Reading Rondo follows (confirmed by MJ on 9 Nov 2026):*
  - Published output carries Rondo's own analysis: model values, ratings, aggregates, rankings and charts.
  - Exported JSON (`web/public/data/`) must not be a bulk copy of StatsBomb events. Pages may show what a chart needs (for example, the shots in one match report), but no page or file republishes the event stream, the 360 frames, or StatsBomb's own fields wholesale (such as its xG value per shot).
  - This narrows the shot-explorer and match-report pages: they show what one chart needs, never an explorable dump of StatsBomb shots.
- Player names are not restricted by these terms. Rondo names players only where the minors rule allows.
- Copying data to MJ's own Bridges-2 allocation for training is MJ's own use, not provision to a third party (confirmed by MJ on 9 Nov 2026).

**Non-commercial**
- Rondo is a non-commercial portfolio project: no ads, no paid features, no selling outputs.
- The README states that published outputs may not be used commercially. The MIT licence covers Rondo's code only, never the data or outputs derived from StatsBomb data.

**Tone (§1.2.4)**
- Ratings and reports use neutral, factual language about players and clubs.

**Request etiquette**
- §2.2 asks every user to register their name and email at www.statsbomb.com/resource-centre before using the data. That's MJ's personal information, so MJ registers himself.
  - Checked 8 Nov 2026: that address (and statsbomb.com's old free-data page) redirects to Hudl's StatsBomb product page (hudl.com/en_gb/products/statsbomb), which has only a sales demo form, no free-data registration. Rondo proceeds without registering.
- Data is fetched once with a partial, sparse `git clone` pinned to one commit, then cached locally. No repeated or bulk API scraping.

## Wyscout open data (Pappalardo et al.)

**Read from:** figshare collection "Soccer match event dataset" (DOI 10.6084/m9.figshare.c.4415000.v5) and the licence field of each item in it, via the figshare API.

**Licence:** every item Rondo uses is CC BY 4.0: Competitions, Matches, Teams, Players, Events, and the event-id and tag-id mapping tables.

**What's allowed (CC BY 4.0)**
- Share and adapt the data for any purpose, including redistributing it and publishing derived numbers and player names.

**Obligations**
- Give credit, link the licence, and say that changes were made. The credit line above does all three.
- Don't suggest the authors or Wyscout endorse Rondo. The disclaimer covers this.

**Citation requests** (from the collection description, for anyone who uses the data in research or analyses):
- Pappalardo, L., Cintia, P., Rossi, A., Massucco, E., Ferragina, P., Pedreschi, D. & Giannotti, F. (2019). A public data set of spatio-temporal match events in soccer competitions. *Scientific Data* 6, 236. https://doi.org/10.1038/s41597-019-0247-7
- Pappalardo, L., Cintia, P., Ferragina, P., Massucco, E., Pedreschi, D. & Giannotti, F. (2019). PlayeRank: Data-driven performance evaluation and player ranking in soccer via a machine learning approach. *ACM TIST* 10(5), Article 59. https://doi.org/10.1145/3343172

**Rondo's own limits**
- Raw files still stay out of git, even though the licence would allow redistributing them.
- Wyscout's player file includes birth dates. These are used only for the minors rule and are never published.

**Request etiquette**
- Download each file once from figshare, record its DOI and checksum in `data/raw/wyscout/SOURCE.json`, and cache it.

## DFL open tracking data (Bassek et al.)

**Read from:**
- the figshare item "An integrated dataset of spatiotemporal and event data in elite soccer" (DOI 10.6084/m9.figshare.28196177.v1), its licence field and file list, via the figshare API;
- the paper's Data Records and Usage Notes sections: Bassek, Rein, Weber & Memmert (2025), *Scientific Data* 12, 195, https://doi.org/10.1038/s41597-025-04505-y.

**Licence:** CC BY 4.0. The paper says the dataset is "released under a CC-BY 4.0 license with the authorization from the DFL". Match video is not included because of licensing restrictions.

**What's allowed:** the same as Wyscout. Sharing, adapting, and publishing derived numbers and player names are allowed with attribution.

**Obligations:** credit, a licence link, and a statement that changes were made (the credit line above), and no implied endorsement by the DFL or the authors.

**Citation**
- Cite the paper (above) and the dataset: Bassek, M., Rein, R., Weber, H. & Memmert, D. (2025). An integrated dataset of spatiotemporal and event data in elite soccer. figshare. https://doi.org/10.6084/m9.figshare.28196177.v1
- If Rondo loads the data with `floodlight` (as the paper's Usage Notes suggest), credit floodlight in the README too.

**Rondo's own limits**
- Physical numbers come only from this tracking data (and Gradient's, if used). Rondo never simulates GPS or force-plate data.

**Request etiquette:** download each file once from figshare, record checksums, and cache.

## Wikidata (identity and birth dates only)

**Read from:**
- "Wikidata:Licensing" (wikidata.org);
- "Wikidata Query Service/User Manual", the Query limits section (mediawiki.org);
- the Wikimedia Foundation User-Agent Policy (foundation.wikimedia.org).

**Licence**
- Structured data is CC0 (public domain dedication). Attribution isn't required; Rondo credits Wikidata anyway.
- Text on other Wikidata pages is CC BY-SA, but Rondo uses only structured data.

**What Rondo uses it for:** person ids, names, and birth dates, to link players and apply the minors rule. Never as a source of match events.

**Query service limits** (from the User Manual; "subject to change")
- Each query has a 60-second deadline.
- A client (User-Agent plus IP) gets 60 seconds of processing time per 60 seconds.
- A client may send at most 30 error queries per minute.
- At most 5 parallel queries per IP.
- Clients over these limits get HTTP 429 and must wait for the `Retry-After` header. Clients that ignore 429s can be banned.

**User-Agent policy**
- Every request must send a descriptive User-Agent with contact information, in the form `<client>/<version> (<contact>) <library>/<version>`.
- Generic agents (`python-requests`, `curl`) and browser User-Agents may be blocked. Automated clients are asked to include "bot".

**How Rondo complies (Phase 3)**
- User-Agent: `RondoBot/<version> (https://github.com/Moulik04) <library>/<version>`.
- One query at a time, with players batched through `VALUES` blocks so each query stays well under 60 seconds.
- Every response is cached on disk and never re-fetched without need.
- On 429 or 5xx, wait for `Retry-After` (or exponential backoff), and stop after repeated errors.

## Gradient Sports 2022 World Cup data (formerly PFF FC)

**Status: not read.** The terms ship with the files, which MJ requests himself through Gradient's form. This entry is written once MJ has placed the files in `data/raw/gradient_wc2022/`.

Until then, nothing derived from Gradient may reach published output. If the terms don't clearly allow publishing derived numbers, Rondo stops and asks MJ.
