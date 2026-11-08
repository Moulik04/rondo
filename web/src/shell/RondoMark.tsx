/**
 * The site's one moment of motion: a rondo. Five players on a circle keep the ball
 * from two defenders in bibs; five passes trace a star once on load, then it rests.
 */

const ATTACKERS: [number, number][] = [
  [120, 32],
  [203.7, 92.8],
  [171.7, 191.2],
  [68.3, 191.2],
  [36.3, 92.8],
];
// Inside the star's inner pentagon, so every pass goes around them.
const DEFENDERS: [number, number][] = [
  [109, 113],
  [131, 127],
];
// Passer -> receiver, by attacker index, in order.
const PASSES: [number, number][] = [
  [0, 2],
  [2, 4],
  [4, 1],
  [1, 3],
  [3, 0],
];

export function RondoMark() {
  return (
    <svg
      className="rondo-mark"
      viewBox="0 0 240 240"
      role="img"
      aria-label="A rondo: five players on a circle keep the ball away from two defenders in the middle."
    >
      <circle className="rondo-mark__ring" cx="120" cy="120" r="88" />
      {PASSES.map(([from, to], i) => {
        const [x1, y1] = ATTACKERS[from];
        const [x2, y2] = ATTACKERS[to];
        return (
          <line
            key={i}
            className="rondo-mark__pass"
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            pathLength={1}
            style={{ animationDelay: `${0.4 + i * 0.75}s` }}
          />
        );
      })}
      {DEFENDERS.map(([cx, cy], i) => (
        <circle key={i} className="rondo-mark__defender" cx={cx} cy={cy} r="10" />
      ))}
      {ATTACKERS.map(([cx, cy], i) => (
        <circle key={i} className="rondo-mark__attacker" cx={cx} cy={cy} r="11" />
      ))}
      <circle className="rondo-mark__ball" cx="120" cy="49" r="5" />
    </svg>
  );
}
