import { Link, NavLink, Outlet } from "react-router";
import { Footer } from "./Footer";
import { SITE_TITLE } from "./credits";
import { ThemeToggle } from "./ThemeToggle";

export function Layout() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <div className="wrap site-header__inner">
          <Link to="/" className="site-title">
            {SITE_TITLE}
          </Link>
          <nav aria-label="Sections" className="site-nav">
            <NavLink to="/value">Value</NavLink>
            <NavLink to="/scout">Scout</NavLink>
            <ThemeToggle />
          </nav>
        </div>
      </header>
      <main id="main" className="wrap site-main">
        <Outlet />
      </main>
      <Footer />
    </>
  );
}
