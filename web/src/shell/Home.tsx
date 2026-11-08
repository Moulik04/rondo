import { Link } from "react-router";
import { RondoMark } from "./RondoMark";
import { usePageTitle } from "./usePageTitle";

export function Home() {
  usePageTitle();
  return (
    <>
      <section className="hero">
        <div className="hero__text">
          <h1 className="hero__title">What each action is worth, and who plays alike.</h1>
          <p className="hero__lede">
            Rondo builds two tools for club analysts, coaches and scouts from the largest free
            datasets in men's European football. A model ships only when it beats simpler baselines
            on tests written down before it was run.
          </p>
          <p className="status">Being built in public. No results are published yet.</p>
        </div>
        <RondoMark />
      </section>

      <div className="halves">
        <section className="half" aria-labelledby="home-value">
          <h2 id="home-value">Value</h2>
          <p>
            How much each pass, carry and shot changes a team's chance of scoring. Player ratings,
            next-morning match reports and a coach app.
          </p>
          <Link className="go" to="/value">
            Open Value
          </Link>
        </section>
        <section className="half" aria-labelledby="home-scout">
          <h2 id="home-scout">Scout</h2>
          <p>
            Find players who play like a player you name, by style and, where tracking data exists,
            physical output. Compare them and keep a shortlist.
          </p>
          <Link className="go" to="/scout">
            Open Scout
          </Link>
        </section>
      </div>
    </>
  );
}
