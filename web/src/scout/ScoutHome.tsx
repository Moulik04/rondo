import { usePageTitle } from "../shell/usePageTitle";

export function ScoutHome() {
  usePageTitle("Scout");
  return (
    <section className="section-page">
      <h1>Scout</h1>
      <p className="section-page__lede">
        Find players who play like a player you name, by style and, where tracking data exists,
        physical output.
      </p>
      <div className="empty">
        <p>No results yet.</p>
        <p>
          This section opens once the similarity model passes its pre-registered tests. Planned
          pages: find similar players, player cards, compare, a shortlist and physical data.
        </p>
      </div>
    </section>
  );
}
