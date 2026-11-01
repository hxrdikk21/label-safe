import { motion, useReducedMotion } from 'motion/react';

// One illustrated scene per pipeline step. Colours follow the design tokens:
// ink = structure, orange/yellow/blue/mint = interaction types, red = contraindicated.
const INK = '#13233a';
const RULE = '#d5dee3';
const PAGE = '#f4f7f6';
const SLATE = '#5a6b7f';
const C = { ddi: '#ee7b30', food: '#f2c230', condition: '#2d6bd8', allergy: '#3aae7a', red: '#c8102e' };

const T = { fontFamily: 'Archivo, system-ui, sans-serif' };

function useEnter(still) {
  const reduce = useReducedMotion();
  const off = still || reduce;
  // Still (mobile frames, reduced motion) jumps straight to the final state.
  return (from, delay = 0, extra = {}) => {
    const animate = { opacity: 1, x: 0, y: 0, scale: 1, rotate: 0, ...extra };
    return off
      ? { initial: false, animate }
      : { initial: from, animate, transition: { delay, type: 'spring', stiffness: 220, damping: 24 } };
  };
}

function Capsule({ x, y, color }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <rect x="0" y="0" width="64" height="26" rx="13" fill="#fff" stroke={INK} strokeWidth="2.5" />
      <path d="M32 0 H51 A13 13 0 0 1 51 26 H32 Z" fill={color} stroke={INK} strokeWidth="2.5" />
    </g>
  );
}

function Lines({ x, y, w, n, gap = 14, highlight = {} }) {
  return Array.from({ length: n }, (_, i) => (
    <rect
      key={i}
      x={x}
      y={y + i * gap}
      width={i === n - 1 ? w * 0.6 : w}
      height="6"
      rx="3"
      fill={highlight[i] || RULE}
    />
  ));
}

function Intake({ e }) {
  const items = [
    { k: 'Warfarin', node: <Capsule x={0} y={0} color={INK} /> },
    { k: 'Ibuprofen', node: <Capsule x={0} y={0} color={C.ddi} /> },
    {
      k: 'Grapefruit',
      node: (
        <g transform="translate(32 13)">
          <circle r="20" fill={C.food} stroke={INK} strokeWidth="2.5" />
          {[0, 60, 120].map((a) => (
            <line key={a} x1="-17" y1="0" x2="17" y2="0" stroke={INK} strokeWidth="1.5" transform={`rotate(${a})`} />
          ))}
        </g>
      ),
    },
    {
      k: 'Asthma',
      node: (
        <g transform="translate(32 13)">
          <rect x="-22" y="-16" width="44" height="32" rx="6" fill={C.condition} />
          <path d="M-10 0 H-4 L0 -8 L4 8 L8 0 H12" fill="none" stroke="#fff" strokeWidth="2.5" />
        </g>
      ),
    },
  ];
  return (
    <g>
      {items.map((it, i) => (
        <motion.g key={it.k} {...e({ opacity: 0, y: -120 }, 0.1 + i * 0.12)}>
          <g transform={`translate(${44 + i * 104} 150)`}>
            {it.node}
            <text x="32" y="62" textAnchor="middle" fontSize="13" fill={INK} {...T}>
              {it.k}
            </text>
          </g>
        </motion.g>
      ))}
      <path d="M30 236 H450 V262 Q450 276 436 276 H44 Q30 276 30 262 Z" fill="#fff" stroke={INK} strokeWidth="2.5" />
      <text x="240" y="312" textAnchor="middle" fontSize="14" fill={SLATE} {...T}>
        Everything goes into one check
      </text>
    </g>
  );
}

function Rules({ e }) {
  return (
    <g>
      {[0, 1, 2].map((i) => (
        <rect key={i} x={40 + i * 6} y={70 + i * 6} width="150" height="190" rx="4" fill="#fff" stroke={INK} strokeWidth="2" />
      ))}
      <text x="127" y="104" textAnchor="middle" fontSize="13" fontWeight="700" fill={INK} {...T}>
        Rulebook
      </text>
      <Lines x={70} y={120} w={110} n={8} highlight={{ 2: C.ddi }} />
      <motion.g {...e({ opacity: 0, x: 40 }, 0.1)}>
        <Capsule x={290} y={88} color={INK} />
        <text x="306" y="78" fontSize="13" fill={INK} {...T}>
          Warfarin
        </text>
        <Capsule x={290} y={150} color={C.ddi} />
        <text x="306" y="198" fontSize="13" fill={INK} {...T}>
          Ibuprofen
        </text>
      </motion.g>
      <motion.path
        d="M286 128 C240 128 230 154 190 154"
        fill="none"
        stroke={INK}
        strokeWidth="2"
        strokeDasharray="5 5"
        {...e({ opacity: 0 }, 0.35)}
      />
      <motion.g {...e({ opacity: 0, y: 30, scale: 0.9 }, 0.6)}>
        <rect x="236" y="234" width="210" height="72" rx="4" fill="#fff" stroke={INK} strokeWidth="2" />
        <rect x="250" y="248" width="82" height="22" rx="5" fill={C.ddi} />
        <text x="291" y="263" textAnchor="middle" fontSize="12" fontWeight="800" fill={INK} {...T}>
          Drug–drug
        </text>
        <rect x="340" y="248" width="94" height="22" rx="4" fill={C.red} />
        <text x="387" y="263" textAnchor="middle" fontSize="11" fontWeight="700" fill="#fff" {...T}>
          Contraindicated
        </text>
        <text x="250" y="292" fontSize="12" fill={SLATE} {...T}>
          Rule DDI-001: bleeding risk
        </text>
      </motion.g>
    </g>
  );
}

function Search({ e }) {
  const pages = [
    { x: 44, r: -6, hl: { 1: '#cfe0fb', 4: '#fbe9b0' } },
    { x: 172, r: 0, hl: { 3: '#cfe0fb' } },
    { x: 300, r: 6, hl: { 0: '#fbe9b0', 5: '#cfe0fb' } },
  ];
  return (
    <g>
      {pages.map((p, i) => (
        <motion.g key={i} {...e({ opacity: 0, y: 40, rotate: 0 }, i * 0.12, { rotate: p.r })} style={{ originX: 0.5, originY: 1 }}>
          <g transform={`translate(${p.x} 60)`}>
            <rect width="136" height="190" rx="4" fill="#fff" stroke={INK} strokeWidth="2" />
            <rect x="14" y="16" width="70" height="8" rx="2" fill={INK} />
            <Lines x={14} y={40} w={108} n={9} gap={15} highlight={p.hl} />
          </g>
        </motion.g>
      ))}
      <g transform="translate(64 290)">
        <rect width="18" height="10" rx="3" fill="#cfe0fb" />
        <text x="26" y="10" fontSize="13" fill={INK} {...T}>
          Matches by meaning
        </text>
        <rect x="190" width="18" height="10" rx="3" fill="#fbe9b0" />
        <text x="216" y="10" fontSize="13" fill={INK} {...T}>
          Matches exact words
        </text>
      </g>
    </g>
  );
}

function Rerank({ e }) {
  const scores = [0.92, 0.88, 0.81, 0.74, 0.69, 0.41, 0.33, 0.2];
  return (
    <g>
      <text x="40" y="48" fontSize="13" fill={SLATE} {...T}>
        Relevance to your question
      </text>
      {scores.map((s, i) => {
        const kept = i < 5;
        return (
          <motion.g key={i} {...e({ opacity: 0, x: -30 }, i * 0.07, { opacity: kept ? 1 : 0.3 })}>
            <rect x="40" y={64 + i * 30} width="300" height="20" rx="3" fill={PAGE} stroke={RULE} />
            <rect x="40" y={64 + i * 30} width={300 * s} height="20" rx="3" fill={kept ? INK : RULE} />
            <text x="352" y={79 + i * 30} fontSize="13" fill={kept ? INK : SLATE} {...T}>
              {kept ? 'kept' : 'dropped'}
            </text>
          </motion.g>
        );
      })}
      <line x1="34" y1="212" x2="420" y2="212" stroke={C.ddi} strokeWidth="2" strokeDasharray="6 4" />
      <text x="420" y="206" textAnchor="end" fontSize="12" fill={INK} {...T}>
        top 5
      </text>
    </g>
  );
}

function Gate({ e }) {
  const reduce = useReducedMotion();
  return (
    <g>
      <path d="M100 250 A140 140 0 0 1 380 250" fill="none" stroke={RULE} strokeWidth="26" />
      <path d="M100 250 A140 140 0 0 1 170 129" fill="none" stroke="#f3c6cd" strokeWidth="26" />
      <path d="M310 129 A140 140 0 0 1 380 250" fill="none" stroke="#cfe0fb" strokeWidth="26" />
      <text x="96" y="282" fontSize="13" fill={INK} {...T}>
        Say so
      </text>
      <text x="240" y="282" textAnchor="middle" fontSize="13" fill={INK} {...T}>
        Try once more
      </text>
      <text x="384" y="282" textAnchor="end" fontSize="13" fill={INK} {...T}>
        Explain
      </text>
      {/* Needle drawn from its pivot at (0,0); rotating about the bottom of its own box. */}
      <g transform="translate(240 250)">
        <motion.g
          initial={reduce ? false : { rotate: -80 }}
          animate={{ rotate: 55 }}
          transition={{ type: 'spring', stiffness: 60, damping: 12, delay: 0.2 }}
          style={{ originX: 0.5, originY: 1 }}
        >
          <line x1="0" y1="0" x2="0" y2="-110" stroke={INK} strokeWidth="5" strokeLinecap="round" />
        </motion.g>
      </g>
      <circle cx="240" cy="250" r="12" fill={INK} />
      <motion.g {...e({ opacity: 0, scale: 0.8 }, 0.8)}>
        <rect x="124" y="300" width="232" height="34" rx="4" fill="none" stroke={C.red} strokeWidth="2.5" transform="rotate(-4 240 317)" />
        <text x="240" y="322" textAnchor="middle" fontSize="13" fontWeight="800" fill={C.red} transform="rotate(-4 240 317)" {...T}>
          Otherwise: not enough evidence
        </text>
      </motion.g>
    </g>
  );
}

function Explain({ e }) {
  return (
    <g>
      <motion.g {...e({ opacity: 0, x: -20 }, 0)}>
        <rect x="30" y="60" width="250" height="210" rx="4" fill="#fff" stroke={INK} strokeWidth="2" />
        <text x="46" y="88" fontSize="13" fontWeight="700" fill={INK} {...T}>
          Explanation
        </text>
        {[0, 1, 2].map((i) => (
          <g key={i}>
            <Lines x={46} y={106 + i * 52} w={150} n={2} gap={14} />
            <rect x="206" y={112 + i * 52} width="58" height="20" rx="4" fill={INK} />
            <text x="235" y={126 + i * 52} textAnchor="middle" fontSize="11" fontWeight="700" fill="#fff" {...T}>
              [P-{i + 1}]
            </text>
          </g>
        ))}
      </motion.g>
      {[0, 1, 2].map((i) => (
        <motion.g key={i} {...e({ opacity: 0, x: 30 }, 0.25 + i * 0.15)}>
          <path
            d={`M264 ${122 + i * 52} C300 ${122 + i * 52} 300 ${88 + i * 70} 330 ${88 + i * 70}`}
            fill="none"
            stroke={INK}
            strokeWidth="1.5"
            strokeDasharray="4 4"
          />
          <rect x="330" y={66 + i * 70} width="120" height="48" rx="4" fill={PAGE} stroke={INK} strokeWidth="1.5" />
          <text x="342" y={86 + i * 70} fontSize="11" fontWeight="700" fill={INK} {...T}>
            Label passage P-{i + 1}
          </text>
          <Lines x={342} y={94 + i * 70} w={92} n={1} />
        </motion.g>
      ))}
      <text x="30" y="306" fontSize="13" fill={SLATE} {...T}>
        A sentence with no citation is removed.
      </text>
    </g>
  );
}

const SCENES = [Intake, Rules, Search, Rerank, Gate, Explain];

export default function StageSvg({ step, still = false, title }) {
  const e = useEnter(still);
  const Scene = SCENES[step];
  return (
    <svg className="stage-svg" viewBox="0 0 480 340" role="img" aria-label={title}>
      <Scene key={step} e={e} />
    </svg>
  );
}
