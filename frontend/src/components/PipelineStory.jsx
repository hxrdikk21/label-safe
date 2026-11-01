import { useEffect, useRef, useState } from 'react';
import { useInView } from 'motion/react';
import StageSvg from './pipeline/StageSvg';

const STEPS = [
  {
    title: 'You list what you take',
    text: 'Your medicines, plus any foods, health conditions and allergies, all in one form.',
    tech: 'One request to the safety API.',
  },
  {
    title: 'Rules decide the risk',
    text: 'Every combination is checked against about 50,000 interaction rules from a reviewed rulebook, the DDInter database and FDA labels. This is the only step that decides whether something is dangerous.',
    tech: 'Deterministic safety engine. No AI involved.',
  },
  {
    title: 'We find the label text',
    text: 'RxGuard searches the official FDA labels of your medicines for passages about the risk, matching both meaning and exact words.',
    tech: 'pgvector and keyword search, fused with reciprocal rank fusion.',
  },
  {
    title: 'Keep the five best passages',
    text: 'A second model reads each passage next to your question and keeps only the five that answer it best.',
    tech: 'Cross-encoder reranking.',
  },
  {
    title: 'Enough evidence? If not, we say so',
    text: 'If the passages do not clearly cover the question, RxGuard tries one rephrased search. If that still falls short, it tells you instead of guessing.',
    tech: 'Corrective RAG gate.',
  },
  {
    title: 'Explain every finding, with citations',
    text: 'Each finding is explained from its own label passages. Sentences taken from a label are numbered and link to it; anything else is marked as general information.',
    tech: 'Grounded generation, then a citation check.',
  },
];

function Step({ index, step, active, onActive }) {
  const ref = useRef(null);
  // Active when the step crosses the middle of the viewport, next to the sticky stage.
  const inView = useInView(ref, { margin: '-45% 0px -45% 0px' });
  useEffect(() => {
    if (inView) onActive(index);
  }, [inView, index, onActive]);
  return (
    <li ref={ref} className={`step${active ? ' is-active' : ''}`}>
      <span className="step-n num" aria-hidden="true">
        {index + 1}
      </span>
      <h3>{step.title}</h3>
      <p>{step.text}</p>
      <p className="step-tech hint">{step.tech}</p>
      <div className="step-frame sheet" aria-hidden="true">
        <StageSvg step={index} still title={step.title} />
      </div>
    </li>
  );
}

export default function PipelineStory() {
  const [active, setActive] = useState(0);
  return (
    <div className="story-grid">
      <div className="story-stage sheet" aria-hidden="true">
        <StageSvg step={active} title={STEPS[active].title} />
        <p className="stage-caption">
          Step {active + 1} of {STEPS.length}: {STEPS[active].title}
        </p>
      </div>
      <ol className="steps">
        {STEPS.map((s, i) => (
          <Step key={s.title} index={i} step={s} active={i === active} onActive={setActive} />
        ))}
      </ol>
    </div>
  );
}
