import { useEffect, useState } from 'react';
import { ExternalLink, X } from 'lucide-react';
import { evidenceApi } from '../services/api';
import { FINDING_TYPES } from '../data/catalog';

const COLUMNS = ['MEDICATION', 'INGREDIENT', 'FINDING', 'RULE', 'PASSAGE', 'SOURCE'];
const COLUMN_LABEL = {
  MEDICATION: 'Medicines',
  INGREDIENT: 'Ingredients',
  FINDING: 'Finding',
  RULE: 'Rule',
  PASSAGE: 'Label passages',
  SOURCE: 'Source',
};
const SOURCE_NAME = { curated: 'curated rulebook', ddinter: 'DDInter', fda_label: 'FDA label text' };
const COL_W = 132;
const ROW_H = 54;
const title = (s) => s.replace(/\b\w/g, (c) => c.toUpperCase());

// The provenance subgraph for one finding (GET /evidence/subgraph/{id}), laid out left to right.
export default function EvidenceGraph({ finding, names, onClose }) {
  const [loaded, setLoaded] = useState(null);
  const [error, setError] = useState(null);
  const [pickedId, setPickedId] = useState(null);

  useEffect(() => {
    let live = true;
    evidenceApi
      .subgraph(finding.finding_id)
      .then((g) => live && (setLoaded(g), setError(null)))
      .catch((err) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, [finding.finding_id]);

  const label = (n) => {
    if (n.type === 'MEDICATION') return names[n.id] || title(n.label);
    if (n.type === 'FINDING') return FINDING_TYPES[finding.finding_type] || 'Finding';
    if (n.type === 'PASSAGE') return title(n.label.toLowerCase());
    return n.type === 'INGREDIENT' ? title(n.label) : n.label;
  };
  // A graph loaded for the previously selected finding is not shown for this one.
  const graph = loaded?.finding_id === finding.finding_id ? loaded : null;
  const fit = (text) => (text.length > 16 ? `${text.slice(0, 15)}…` : text);

  let body = <p className="hint">Loading the evidence trail…</p>;
  if (error) body = <p className="error">{error}</p>;
  if (graph) {
    const cols = COLUMNS.filter((c) => graph.nodes.some((n) => n.type === c));
    const width = cols.length * COL_W;
    const pos = {};
    let height = 140;
    cols.forEach((c, ci) => {
      const inCol = graph.nodes.filter((n) => n.type === c);
      height = Math.max(height, 64 + inCol.length * ROW_H);
      inCol.forEach((n, i) => {
        pos[n.id] = { x: COL_W * ci + COL_W / 2, y: 60 + i * ROW_H, node: n };
      });
    });
    const passages = graph.nodes.filter((n) => n.type === 'PASSAGE');
    const picked = passages.find((p) => p.id === pickedId) || passages[0];
    const sourceOf = (p) => {
      const edge = graph.edges.find((e) => e.source === p.id && e.relationship === 'EXTRACTED_FROM');
      return graph.nodes.find((n) => n.id === edge?.target);
    };
    const rule = graph.nodes.find((n) => n.type === 'RULE');
    const ruleText = rule
      ? `rule ${rule.label} (${SOURCE_NAME[rule.properties.source] || rule.properties.source}${
          rule.properties.reviewed ? '' : ', not clinically reviewed'
        })`
      : `rule ${finding.rule_id || 'n/a'}`;

    body = (
      <>
        <div className="graph-scroll">
          <svg
            className="map-svg"
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label="Evidence trail for this finding"
          >
            {cols.map((c, ci) => (
              <text key={c} x={COL_W * ci + COL_W / 2} y="22" textAnchor="middle" fontSize="12" fill="#5a6b7f">
                {COLUMN_LABEL[c]}
              </text>
            ))}
            {graph.edges.map((e, i) => {
              const a = pos[e.source];
              const b = pos[e.target];
              if (!a || !b) return null;
              return (
                <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#13233a" strokeWidth="1.5" />
              );
            })}
            {Object.values(pos).map(({ x, y, node }) => {
              const full = label(node);
              const text = fit(full);
              const w = COL_W - 24;
              const isFinding = node.type === 'FINDING';
              const isPassage = node.type === 'PASSAGE';
              const isPicked = isPassage && picked?.id === node.id;
              const unreviewed = node.type === 'RULE' && !node.properties.reviewed;
              return (
                <g
                  key={node.id}
                  transform={`translate(${x - w / 2} ${y - 15})`}
                  className={isPassage ? 'graph-node-click' : undefined}
                  role={isPassage ? 'button' : undefined}
                  tabIndex={isPassage ? 0 : undefined}
                  aria-label={isPassage ? `Show passage: ${full}` : undefined}
                  aria-pressed={isPassage ? isPicked : undefined}
                  onClick={isPassage ? () => setPickedId(node.id) : undefined}
                  onKeyDown={
                    isPassage
                      ? (e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            setPickedId(node.id);
                          }
                        }
                      : undefined
                  }
                >
                  <title>{full}</title>
                  <rect
                    width={w}
                    height="30"
                    rx="4"
                    fill={isFinding ? '#c8102e' : isPicked ? '#13233a' : '#ffffff'}
                    stroke={isFinding ? '#c8102e' : '#13233a'}
                    strokeWidth="1.5"
                    strokeDasharray={unreviewed ? '4 3' : undefined}
                  />
                  <text
                    x={w / 2}
                    y="20"
                    textAnchor="middle"
                    fontSize="12"
                    fontWeight="700"
                    fill={isFinding || isPicked ? '#ffffff' : '#13233a'}
                  >
                    {text}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
        {picked ? (
          <div className="passage">
            <p className="passage-head">
              <strong>
                {title(picked.properties.drug || '')} label · {picked.label.toLowerCase()}
              </strong>
              {sourceOf(picked)?.properties.url && (
                <a className="text-link" href={sourceOf(picked).properties.url} target="_blank" rel="noreferrer">
                  Open on DailyMed <ExternalLink size={14} aria-hidden="true" />
                </a>
              )}
            </p>
            <p className="passage-text">{picked.properties.content}</p>
            {passages.length > 1 && <p className="hint">Select another passage in the graph to read it.</p>}
            <p className="hint">This finding comes from {ruleText}.</p>
          </div>
        ) : (
          <p className="hint">
            No FDA label text is loaded for these medicines yet, so this finding rests on {ruleText} alone.
          </p>
        )}
      </>
    );
  }

  return (
    <section className="sheet panel" aria-labelledby="evidence-title">
      <div className="panel-head">
        <h2 id="evidence-title">Evidence trail</h2>
        <button type="button" className="icon-btn" aria-label="Close evidence trail" onClick={onClose}>
          <X size={18} aria-hidden="true" />
        </button>
      </div>
      {body}
    </section>
  );
}
