import { FINDING_TONES, FINDING_TYPES } from '../data/catalog';

const title = (s) => s.replace(/\b\w/g, (c) => c.toUpperCase());
const TONE_COLOR = { ddi: '#ee7b30', food: '#f2c230', condition: '#2d6bd8', allergy: '#3aae7a' };
const NODE = {
  med: { fill: '#13233a', text: '#ffffff' },
  food: { fill: '#f2c230', text: '#13233a' },
  condition: { fill: '#2d6bd8', text: '#ffffff' },
  allergy: { fill: '#3aae7a', text: '#13233a' },
};
const WIDTH = { CONTRAINDICATED: 6, MAJOR: 4.5, MODERATE: 3 };

// Findings only name the medicine(s); the food/condition/allergy end is found in the finding text.
function endpoints(f, nodes) {
  const text = `${f.clinical_explanation} ${f.actionable_warning}`.toLowerCase();
  const meds = f.subject_medications.map((r) => `med:${r}`).filter((id) => nodes.has(id));
  if (f.finding_type === 'DRUG_DRUG_INTERACTION') return meds.length === 2 ? meds : null;
  const kind = { DRUG_FOOD_INTERACTION: 'food', CONTRAINDICATION: 'condition', ALLERGY_EXCIPIENT: 'allergy' }[
    f.finding_type
  ];
  const candidates = [...nodes.values()].filter((n) => n.kind === kind);
  const other =
    candidates.find((n) => (n.code && text.includes(`(${n.code.toLowerCase()})`)) || text.includes(n.label.toLowerCase())) ||
    candidates[0];
  return meds[0] && other ? [meds[0], other.id] : null;
}

export default function InteractionMap({ meds, foods, conditions, allergies, findings, selectedId, onSelect }) {
  const list = [
    ...meds.map((m) => ({ id: `med:${m.concept.rxcui}`, label: title(m.concept.canonical_name), kind: 'med' })),
    ...foods.map((f) => ({ id: `food:${f}`, label: f, kind: 'food' })),
    ...conditions.map((c) => ({ id: `condition:${c.name}`, label: c.name, code: c.icd10, kind: 'condition' })),
    ...allergies.map((a) => ({ id: `allergy:${a}`, label: a, kind: 'allergy' })),
  ];
  if (!list.length) return null;

  // Two columns: medicines left, everything else right. Drug-drug links arc on the left.
  const left = list.filter((n) => n.kind === 'med');
  const right = list.filter((n) => n.kind !== 'med');
  const rowH = 48;
  const rows = Math.max(left.length, right.length, 2);
  const height = rows * rowH + 24;
  list.forEach((n) => {
    n.w = Math.max(80, n.label.length * 7.6 + 28);
  });
  // Size the drawing to its contents so labels stay readable on narrow screens.
  const arcRoom = 30 + Math.max(left.length - 1, 0) * rowH * 0.3;
  const leftW = Math.max(0, ...left.map((n) => n.w));
  const rightW = Math.max(0, ...right.map((n) => n.w));
  const leftX = arcRoom + leftW / 2;
  const rightX = arcRoom + leftW + 120 + rightW / 2;
  const width = right.length ? rightX + rightW / 2 + 8 : leftX + leftW / 2 + 8;
  const place = (col, x) =>
    col.forEach((n, i) => {
      n.x = x;
      n.y = 12 + rowH / 2 + i * rowH + ((rows - col.length) * rowH) / 2;
    });
  place(left, leftX);
  place(right, rightX);
  const nodes = new Map(list.map((n) => [n.id, n]));

  const edges = (findings || [])
    .map((f) => ({ f, ends: endpoints(f, nodes) }))
    .filter((e) => e.ends);

  let caption = 'Press Check to draw the risks between them.';
  if (findings) {
    caption = edges.length
      ? `${edges.length} link${edges.length === 1 ? '' : 's'}. Select one to see its evidence.`
      : 'No links: nothing was flagged in the checked sources. That does not mean it is safe.';
  }

  return (
    <section className="sheet map" aria-labelledby="map-title">
      <div className="panel-head">
        <h2 id="map-title">Interaction map</h2>
        <span className="hint">{caption}</span>
      </div>
      <svg
        className="map-svg"
        viewBox={`0 0 ${width} ${height}`}
        style={{ maxWidth: width * 1.25 }}
        role="group"
        aria-label="Interaction map"
      >
        {edges.map(({ f, ends: [a, b] }) => {
          const from = nodes.get(a);
          const to = nodes.get(b);
          const tone = FINDING_TONES[f.finding_type] || 'ddi';
          const selected = selectedId === f.finding_id;
          const dim = selectedId && !selected;
          const label = `${FINDING_TYPES[f.finding_type]}: ${from.label} and ${to.label}, ${f.severity.toLowerCase()}`;
          let d;
          let mid;
          if (from.kind === 'med' && to.kind === 'med') {
            const bulge = 40 + Math.abs(to.y - from.y) * 0.35;
            const x0 = from.x - from.w / 2;
            d = `M${x0} ${from.y} C${x0 - bulge} ${from.y} ${x0 - bulge} ${to.y} ${to.x - to.w / 2} ${to.y}`;
            mid = { x: x0 - bulge * 0.75, y: (from.y + to.y) / 2 };
          } else {
            const x1 = from.x + from.w / 2;
            const x2 = to.x - to.w / 2;
            d = `M${x1} ${from.y} L${x2} ${to.y}`;
            mid = { x: (x1 + x2) / 2, y: (from.y + to.y) / 2 };
          }
          return (
            <g
              key={f.finding_id}
              className="map-edge"
              role="button"
              tabIndex={0}
              aria-label={label}
              aria-pressed={selected}
              onClick={() => onSelect(f)}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect(f))}
              opacity={dim ? 0.25 : 1}
            >
              <path d={d} fill="none" stroke="transparent" strokeWidth="18" />
              <path
                d={d}
                fill="none"
                stroke={TONE_COLOR[tone]}
                strokeWidth={(WIDTH[f.severity] || 2) + (selected ? 2 : 0)}
                strokeLinecap="round"
              />
              {f.severity === 'CONTRAINDICATED' && (
                <g transform={`translate(${mid.x} ${mid.y})`}>
                  <circle r="11" fill="#c8102e" />
                  <path d="M-4.5 -4.5 L4.5 4.5 M4.5 -4.5 L-4.5 4.5" stroke="#fff" strokeWidth="2.5" />
                </g>
              )}
            </g>
          );
        })}
        {list.map((n) => (
          <g key={n.id} transform={`translate(${n.x - n.w / 2} ${n.y - 16})`}>
            <rect width={n.w} height="32" rx={n.kind === 'med' ? 16 : 6} fill={NODE[n.kind].fill} />
            <text
              x={n.w / 2}
              y="21"
              textAnchor="middle"
              fontSize="14"
              fontWeight="700"
              fill={NODE[n.kind].text}
              fontFamily="Archivo, system-ui, sans-serif"
            >
              {n.label}
            </text>
          </g>
        ))}
      </svg>
      <div className="map-legend hint">
        <span>
          <i style={{ background: TONE_COLOR.ddi }} /> Drug–drug
        </span>
        <span>
          <i style={{ background: TONE_COLOR.food }} /> Drug–food
        </span>
        <span>
          <i style={{ background: TONE_COLOR.condition }} /> Condition
        </span>
        <span>
          <i style={{ background: TONE_COLOR.allergy }} /> Allergy
        </span>
        <span>Thicker line, higher severity</span>
      </div>
    </section>
  );
}
