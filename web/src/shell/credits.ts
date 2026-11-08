/**
 * Disclaimer and data credits, copied exactly from docs/DATA_TERMS.md.
 * tests/core/test_public_text.py fails the build if these drift from that file.
 */

export const SITE_TITLE = "Rondo · European football analytics";

export const DISCLAIMER =
  "Independent project by Moulik Jain. Not affiliated with any data provider, league, federation or club.";

/** StatsBomb's terms require its logo wherever analysis of its data is published. */
export const STATSBOMB_LOGO = {
  light: "/brand/statsbomb/hudl-statsbomb-logo-default.png",
  dark: "/brand/statsbomb/hudl-statsbomb-logo-reversed.png",
};

export interface Credit {
  key: string;
  text: string;
  href: string;
}

export const CREDITS: Credit[] = [
  {
    key: "statsbomb",
    text: "Event and 360 data: StatsBomb open data.",
    href: "https://github.com/statsbomb/open-data",
  },
  {
    key: "wyscout",
    text: "Event data: Wyscout open data (Pappalardo et al., 2019, Scientific Data 6:236), CC BY 4.0, converted and aggregated by Rondo.",
    href: "https://doi.org/10.6084/m9.figshare.c.4415000.v5",
  },
  {
    key: "dfl",
    text: "Tracking and event data: DFL open data (Bassek, Rein, Weber & Memmert, 2025, Scientific Data 12:195), CC BY 4.0, converted and aggregated by Rondo.",
    href: "https://doi.org/10.6084/m9.figshare.28196177.v1",
  },
  {
    key: "wikidata",
    text: "Player identity and birth dates used for the minors rule: Wikidata (CC0).",
    href: "https://www.wikidata.org",
  },
  {
    key: "ccby",
    text: "Licence for the CC BY 4.0 datasets above.",
    href: "https://creativecommons.org/licenses/by/4.0/",
  },
];

/** Page title: the site title alone on the home page, "<page> | <site title>" elsewhere. */
export function pageTitle(page?: string): string {
  return page ? `${page} | ${SITE_TITLE}` : SITE_TITLE;
}
