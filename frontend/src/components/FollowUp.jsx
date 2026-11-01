import { useEffect, useRef, useState } from 'react';
import { Send } from 'lucide-react';
import CitedText from './CitedText';
import { chatApi } from '../services/api';

const SUGGESTIONS = ['Why is this risky?', 'What should I ask my pharmacist?', 'Is there a safer alternative?'];
// One assistant reply: offline notice, the cited text, and the key for grey "general information" sentences.
function Reply({ reply }) {
  const general = reply.mode === 'gemini';
  return (
    <div className="turn-a">
      {reply.mode === 'offline' && (
        <p className="hint">The assistant is offline, so this reply quotes the drug labels directly.</p>
      )}
      <CitedText text={reply.reply_narrative} sources={reply.sources} markGeneral={general} />
      {general && reply.unverified_claim_count > 0 && (
        <p className="hint key">Numbered sentences come from FDA labels; grey ones are general information.</p>
      )}
    </div>
  );
}

// The chat about one finished check. The parent remounts this (via `key`) on every new check, which clears it.
export default function FollowUp({ medications, foods = [], userContext }) {
  const [thread, setThread] = useState([]);
  const [text, setText] = useState('');
  const [pending, setPending] = useState(null);
  const [error, setError] = useState(null);
  const end = useRef(null);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [thread, pending]);

  const ask = async (raw) => {
    const query = raw.trim();
    if (query.length < 2 || pending) return;
    setPending(query);
    setText('');
    setError(null);
    try {
      // Earlier turns go along so Gemini sees the conversation and follow-ups like "why?" keep their topic.
      const history = thread.slice(-6).map((t) => ({ query: t.query, reply: t.reply.reply_narrative }));
      const reply = await chatApi.send({ query, medications, food_items: foods, user_context: userContext, history });
      setThread((t) => [...t, { query, reply }]);
    } catch (err) {
      setError(err.message);
      setText(query); // keep the message so it can be sent again
    } finally {
      setPending(null);
    }
  };

  return (
    <section className="sheet panel chat" aria-labelledby="followup-title">
      <h2 id="followup-title">Ask about this result</h2>
      <p className="hint">Chat about the medicines you just checked. Answers cite the FDA labels where they can.</p>

      <div className="chat-log" aria-live="polite">
        {thread.map(({ query, reply }) => (
          <div className="turn" key={reply.response_id}>
            <p className="turn-q">{query}</p>
            <Reply reply={reply} />
          </div>
        ))}
        {pending && (
          <div className="turn">
            <p className="turn-q">{pending}</p>
            <p className="turn-a hint">Thinking…</p>
          </div>
        )}
        <span ref={end} />
      </div>

      {thread.length === 0 && !pending && (
        <div className="chips">
          {SUGGESTIONS.map((s) => (
            <button type="button" className="chip chip-suggest" key={s} onClick={() => ask(s)}>
              {s}
            </button>
          ))}
        </div>
      )}

      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault();
          ask(text);
        }}
      >
        <input
          className="input"
          aria-label="Your message"
          placeholder="Ask anything about this check"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button className="btn btn-primary" disabled={Boolean(pending) || text.trim().length < 2}>
          <Send size={16} aria-hidden="true" />
          Send
        </button>
      </form>
      {error && <p className="error">{error}</p>}
    </section>
  );
}
