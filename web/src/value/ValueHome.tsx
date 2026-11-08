import { usePageTitle } from "../shell/usePageTitle";

export function ValueHome() {
  usePageTitle("Value");
  return (
    <section className="section-page">
      <h1>Value</h1>
      <p className="section-page__lede">
        How much each pass, carry and shot changes a team's chance of scoring, turned into player
        ratings, next-morning match reports and a coach app.
      </p>
      <div className="empty">
        <p>No results yet.</p>
        <p>
          This section opens once the possession-value model passes its pre-registered tests.
          Planned pages: a league value table, team and player pages, match reports and a model lab.
        </p>
      </div>
    </section>
  );
}
