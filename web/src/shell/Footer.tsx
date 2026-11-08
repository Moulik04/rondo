import { CREDITS, DISCLAIMER } from "./credits";

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="wrap">
        <p className="site-footer__disclaimer">{DISCLAIMER}</p>
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
