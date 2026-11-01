import { motion, useReducedMotion } from 'motion/react';
import Sticker from './Sticker';

// Hero graphic: a line-drawn bottle with a prescription label; warning stickers press on once on load.
const STICKERS = [
  { tone: 'ddi', text: 'Do not take with ibuprofen', rotate: -3 },
  { tone: 'condition', text: 'Ask before use with ulcers', rotate: 2 },
];

export default function RxLabel() {
  const reduce = useReducedMotion();
  return (
    <figure className="bottle" aria-label="A prescription label for warfarin with two warning stickers">
      <svg className="bottle-svg" viewBox="0 0 420 520" aria-hidden="true">
        <rect x="70" y="18" width="280" height="70" rx="10" fill="#13233a" />
        <g stroke="#ffffff" strokeWidth="2" opacity="0.35">
          {Array.from({ length: 13 }, (_, i) => (
            <line key={i} x1={92 + i * 20} y1="30" x2={92 + i * 20} y2="76" />
          ))}
        </g>
        <rect x="84" y="88" width="252" height="18" fill="#13233a" opacity="0.85" />
        <path
          d="M64 120 Q64 106 78 106 H342 Q356 106 356 120 V478 Q356 502 332 502 H88 Q64 502 64 478 Z"
          fill="#e9eff1"
          stroke="#13233a"
          strokeWidth="3"
        />
        <path d="M86 130 V470" stroke="#ffffff" strokeWidth="10" strokeLinecap="round" opacity="0.8" />
      </svg>

      <div className="rx-label">
        <div className="rx-label-head num">
          <span>Rx 0042-117</span>
          <span>Qty 30</span>
        </div>
        <p className="rx-label-drug condensed">Warfarin sodium 5 mg</p>
        <p className="rx-label-sig">Take 1 tablet by mouth once daily in the evening.</p>
        <div className="rx-label-rule" />
        <div className="rx-label-meta num">
          <span>Refills: 2</span>
          <span>Use by 10/2027</span>
        </div>
      </div>

      <div className="rx-stickers">
        {STICKERS.map((s, i) => (
          <motion.span
            key={s.text}
            initial={reduce ? false : { opacity: 0, scale: 1.25, rotate: s.rotate - 10, y: -16 }}
            animate={{ opacity: 1, scale: 1, rotate: s.rotate, y: 0 }}
            transition={{ delay: 0.5 + i * 0.35, type: 'spring', stiffness: 380, damping: 22 }}
            style={{ display: 'inline-block' }}
          >
            <Sticker tone={s.tone}>{s.text}</Sticker>
          </motion.span>
        ))}
      </div>
    </figure>
  );
}
