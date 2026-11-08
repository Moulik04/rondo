import { Link } from "react-router";
import { usePageTitle } from "./usePageTitle";

export function NotFound() {
  usePageTitle("Page not found");
  return (
    <section className="section-page">
      <h1>This page doesn't exist</h1>
      <p>
        Check the address, or <Link to="/">go to the home page</Link>.
      </p>
    </section>
  );
}
