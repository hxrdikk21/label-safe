import { useState } from 'react';
import { ExternalLink } from 'lucide-react';

const CITATION = /\s*\[([A-Za-z0-9_-]+)\]/g;

// One block: sentences citing a label get numbered markers; with `markGeneral` the rest are shown as
// general information.
function Sentences({ text, number, markGeneral, onCite }) {
  return text.split(/(?<=[.!?])\s+/).map((sentence, i) => {
    const ids = [...sentence.matchAll(CITATION)].map((m) => m[1]).filter((id) => number[id]);
    return (
      <span key={i} className={!ids.length && markGeneral ? 'general' : undefined}>
        {sentence.replace(CITATION, '')}
        {[...new Set(ids)].map((id) => (
          <button type="button" key={id} className="cite" aria-label={`Source ${number[id]}`} onClick={() => onCite(id)}>
            {number[id]}
          </button>
        ))}{' '}
      </span>
    );
  });
}

// Answer text with [passage_id] citations: paragraphs, "- " lists, numbered markers, and the cited
// label passages (drug, section, quote, DailyMed link) listed underneath.
export default function CitedText({ text, sources, markGeneral = false }) {
  const [open, setOpen] = useState(null);
  const number = Object.fromEntries(sources.map((s, i) => [s.passage_id, i + 1]));

  // Consecutive bullet lines become one list; everything else is a paragraph.
  const body = [];
  text
    .split(/\n+/)
    .filter((b) => b.trim())
    .forEach((block) => {
      const bullet = /^\s*[-*•]\s+/.test(block);
      const content = (
        <Sentences
          text={block.replace(/^\s*[-*•]\s+/, '').replace(/\*\*/g, '')}
          number={number}
          markGeneral={markGeneral}
          onCite={setOpen}
        />
      );
      if (bullet && Array.isArray(body[body.length - 1])) body[body.length - 1].push(content);
      else body.push(bullet ? [content] : content);
    });

  return (
    <>
      {body.map((b, i) =>
        Array.isArray(b) ? (
          <ul key={i}>
            {b.map((item, j) => (
              <li key={j}>{item}</li>
            ))}
          </ul>
        ) : (
          <p key={i}>{b}</p>
        ),
      )}
      {sources.length > 0 && (
        <details className="sources" open={open !== null} onToggle={(e) => !e.target.open && setOpen(null)}>
          <summary>
            {sources.length} FDA label source{sources.length === 1 ? '' : 's'}
          </summary>
          <ol>
            {sources.map((s) => (
              <li key={s.passage_id} className={open === s.passage_id ? 'is-open' : undefined}>
                <strong>
                  {s.drug} label · {s.section.toLowerCase()}
                </strong>
                <span className="source-quote">{s.quote}</span>
                <a className="text-link" href={s.url} target="_blank" rel="noreferrer">
                  Open on DailyMed <ExternalLink size={13} aria-hidden="true" />
                </a>
              </li>
            ))}
          </ol>
        </details>
      )}
    </>
  );
}
