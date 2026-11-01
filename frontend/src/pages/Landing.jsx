import { useEffect, useState } from 'react';
import CountUp from '../components/bits/CountUp';
import PipelineStory from '../components/PipelineStory';
import RxLabel from '../components/RxLabel';
import Sticker from '../components/Sticker';
import Logo from '../components/Logo';
import SeverityBadge from '../components/SeverityBadge';
import { statsApi } from '../services/api';

const RISKS = [
  { tone: 'ddi', name: 'Drug–drug', title: 'Medicines that clash', example: 'Warfarin with ibuprofen' },
  { tone: 'food', name: 'Drug–food', title: 'Food and drink', example: 'Atorvastatin with grapefruit' },
  { tone: 'condition', name: 'Condition', title: 'Health conditions', example: 'Propranolol with asthma' },
  { tone: 'allergy', name: 'Allergy', title: 'Allergies', example: 'Amoxicillin with a penicillin allergy' },
];

export default function Landing() {
  // Live counts from GET /stats; the row stays hidden if the API is unreachable.
  const [stats, setStats] = useState(null);
  useEffect(() => {
    statsApi.get().then(setStats).catch(() => {});
  }, []);
  return (
    <>
      <section className="band">
        <div className="container hero-grid">
          <div className="hero-copy">
            <h1 className="display hero-title">Know before you mix your medicines.</h1>
            <p className="lede">
              One check across your medicines, food, health conditions and allergies. Every risk comes with what to do
              about it, explained from the official drug labels.
            </p>
            <div className="hero-actions">
              <a className="btn btn-primary" href="#/check">
                Start a check
              </a>
              {/* A button, not href="#how": the hash is the router. */}
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => document.getElementById('how')?.scrollIntoView({ behavior: 'smooth' })}
              >
                See how it works
              </button>
            </div>
          </div>
          <RxLabel />
        </div>
      </section>

      <section className="band story" id="how" aria-labelledby="how-title">
        <div className="container band-inner">
          <h2 id="how-title">What happens when you press Check</h2>
          <p className="lede" style={{ marginTop: 12, marginBottom: 40 }}>
            Two parts work in order: fixed rules find the risks, then an assistant explains them using only text from
            drug labels.
          </p>
          <PipelineStory />
        </div>
      </section>

      <section className="band" aria-labelledby="rule-title">
        <div className="container band-inner">
          <h2 id="rule-title">Rules decide. The AI only explains.</h2>
          <div className="guarantee">
            <div className="sheet g-card">
              <h3>Finding, from the rulebook</h3>
              <div className="chips">
                <Sticker tone="ddi">Drug–drug</Sticker>
                <SeverityBadge severity="CONTRAINDICATED" />
              </div>
              <p className="condensed" style={{ fontSize: 22, lineHeight: '26px' }}>
                Warfarin + ibuprofen
              </p>
              <p className="muted">Severe bleeding risk. Avoid using them together.</p>
            </div>
            <svg className="g-arrows" viewBox="0 0 180 120" aria-hidden="true">
              <path d="M10 40 H160" stroke="#13233a" strokeWidth="3" />
              <path d="M150 30 L162 40 L150 50" fill="none" stroke="#13233a" strokeWidth="3" />
              <text x="85" y="26" textAnchor="middle" fontSize="13" fill="#13233a" fontFamily="Archivo">
                explained by
              </text>
              <path d="M170 86 H20" stroke="#5a6b7f" strokeWidth="3" strokeDasharray="6 5" />
              <path d="M30 76 L18 86 L30 96" fill="none" stroke="#5a6b7f" strokeWidth="3" />
              <path d="M80 72 L104 100 M104 72 L80 100" stroke="#c8102e" strokeWidth="4" strokeLinecap="round" />
              <text x="92" y="116" textAnchor="middle" fontSize="13" fill="#c8102e" fontFamily="Archivo">
                can’t change it
              </text>
            </svg>
            <div className="sheet g-card">
              <h3>Explanation, from drug labels</h3>
              <p>
                Ibuprofen can increase the anticoagulant effect of warfarin and raise the risk of serious bleeding{' '}
                <span className="tag num">P-1</span>.
              </p>
              <p className="hint">Every sentence points to a label passage.</p>
            </div>
          </div>
          <p className="lede" style={{ marginTop: 32 }}>
            An explanation can never change, soften or hide a finding. If the labels don’t cover your question, LabelSafe
            says the evidence is insufficient rather than reassuring you.
          </p>
        </div>
      </section>

      <section className="band" aria-labelledby="risks-title">
        <div className="container band-inner">
          <h2 id="risks-title">Four kinds of risk, one form</h2>
          <div className="risks">
            {RISKS.map((r) => (
              <div className="risk" key={r.name}>
                <Sticker tone={r.tone}>{r.name}</Sticker>
                <h3>{r.title}</h3>
                <p className="risk-example muted">For example: {r.example}.</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="container band-inner">
        {stats && (
          <div className="stats">
            <span className="stat">
              <CountUp to={stats.medicines} className="stat-n num" /> medicines to search
            </span>
            <span className="stat">
              <CountUp to={stats.medicines_with_rules} className="stat-n num" /> of them covered by rules
            </span>
            <span className="stat">
              <CountUp to={stats.rules} className="stat-n num" /> interaction rules
            </span>
            <span className="stat">
              <CountUp to={stats.label_passages} className="stat-n num" /> FDA label passages
            </span>
          </div>
        )}
        <div className="pad">
          <Logo size={56} />
          <div style={{ flex: 1, minWidth: 220 }}>
            <h2>Check your list now</h2>
            <p className="muted">No account needed. Take the result to your pharmacist or doctor.</p>
          </div>
          <a className="btn btn-primary" href="#/check">
            Start a check
          </a>
        </div>
      </section>
    </>
  );
}
