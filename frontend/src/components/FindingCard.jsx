import { useEffect, useRef } from 'react';
import SeverityBadge from './SeverityBadge';
import CitedText from './CitedText';
import Sticker from './Sticker';
import { FINDING_TONES, FINDING_TYPES } from '../data/catalog';

// Generated rules (see safety/build_rules.py) have not been clinically reviewed.
const SOURCE = { ddinter: 'DDInter', fda_label: 'FDA label text' };

// `explanation`: undefined while loading, null when no label text was found, else { text, sources, mode }.
export default function FindingCard({ finding, names, selected, onShowEvidence, explanation }) {
  const ref = useRef(null);
  const meds = finding.subject_medications.map((id) => names[id] || id).join(' + ');

  // Selecting a link on the interaction map brings its card into view.
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [selected]);

  return (
    <article ref={ref} className={`finding sheet${selected ? ' is-selected' : ''}`}>
      <div className="finding-head">
        <Sticker tone={FINDING_TONES[finding.finding_type] || 'ddi'}>
          {FINDING_TYPES[finding.finding_type] || finding.finding_type}
        </Sticker>
        <SeverityBadge severity={finding.severity} />
      </div>
      {SOURCE[finding.rule_source] && (
        <p className="tag tag-unreviewed">Unreviewed · from {SOURCE[finding.rule_source]}</p>
      )}
      <h3 className="condensed">{meds}</h3>
      <p>{finding.clinical_explanation}</p>
      <p className="finding-action">
        <strong>What to do:</strong> {finding.actionable_warning}
      </p>
      <div className="finding-evidence" aria-live="polite">
        <p className="finding-evidence-head">From the FDA labels</p>
        {explanation === undefined && <p className="hint">Reading the labels…</p>}
        {explanation === null && <p className="hint">No FDA label text found for this finding.</p>}
        {explanation?.text && (
          <>
            {explanation.mode === 'offline' && <p className="hint">Quoted directly from the label.</p>}
            <div className="explanation-text">
              <CitedText
                text={explanation.text}
                sources={explanation.sources}
                markGeneral={explanation.mode === 'gemini'}
              />
            </div>
          </>
        )}
        {explanation && !explanation.text && <p className="hint">No FDA label text found for this finding.</p>}
      </div>
      <div className="finding-foot">
        {finding.rule_id && <span className="hint num">Rule {finding.rule_id}</span>}
        <button type="button" className="link text-link" onClick={onShowEvidence}>
          Show evidence trail
        </button>
      </div>
    </article>
  );
}
