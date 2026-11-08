import { CREDITS, DISCLAIMER, STATSBOMB_LOGO } from "./credits";

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="wrap">
        <p className="site-footer__disclaimer">{DISCLAIMER}</p>
        <a
          className="site-footer__logo"
          href="https://github.com/statsbomb/open-data"
          rel="noopener noreferrer"
          aria-label="Data: StatsBomb open data"
        >
          <img
            className="logo-light"
            src={STATSBOMB_LOGO.light}
            alt="Hudl StatsBomb"
            width="158"
            height="24"
          />
          <img
            className="logo-dark"
            src={STATSBOMB_LOGO.dark}
            alt="Hudl StatsBomb"
            width="158"
            height="24"
          />
        </a>
        <h2 className="site-footer__heading">Data credits</h2>
        <ul className="site-footer__credits">
          {CREDITS.map((c) => (
            <li key={c.key}>
              <a href={c.href} rel="noopener noreferrer">
                {c.text}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </footer>
  );
}
