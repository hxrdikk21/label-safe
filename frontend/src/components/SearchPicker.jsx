import { useEffect, useId, useState } from 'react';
import { Search, X } from 'lucide-react';

// Live-search combobox with chips, used by every input on the Check page.
// `search(q)` resolves to items { key, label, detail?, code?, has_rules? }; `values` are picked items.
// `allowFree` lets Enter add typed text that matched nothing (its has_rules stays unknown).
export default function SearchPicker({ label, hint, placeholder, values, onChange, search, allowFree = false, tone }) {
  const id = useId();
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [error, setError] = useState(null);
  const [allAdded, setAllAdded] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    let current = true; // a slower, older response must not replace newer results
    const timer = setTimeout(() => {
      search(query.trim())
        .then((res) => {
          if (!current) return;
          const fresh = res.filter((h) => !values.some((v) => v.key === h.key));
          setAllAdded(res.length > 0 && fresh.length === 0);
          setHits(fresh);
          setActive(0);
          setError(null);
        })
        .catch((err) => current && setError(err.message));
    }, 150);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [query, open, values, search]);

  const add = (item) => {
    onChange([...values, item]);
    setQuery('');
    setOpen(false); // an open list would cover the controls below it; typing reopens it
  };

  const addTyped = () => {
    const text = query.trim();
    const key = text.toLowerCase();
    if (!allowFree || !text || values.some((v) => v.key === key)) return;
    add({ key, label: text, value: text });
  };

  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, hits.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (open && hits[active]) add(hits[active]);
      else addTyped();
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  const listId = `${id}-list`;
  return (
    <div className="field picker">
      <label htmlFor={id}>{label}</label>
      {hint && <span className="hint">{hint}</span>}
      {values.length > 0 && (
        <div className="chips">
          {values.map((v) => (
            <span
              className={`chip${tone ? ` tone-${tone}` : ''}${v.has_rules === false ? ' chip-unruled' : ''}`}
              key={v.key}
            >
              {v.label}
              {v.code && <span className="num chip-code">{v.code}</span>}
              <button
                type="button"
                aria-label={`Remove ${v.label}`}
                onClick={() => onChange(values.filter((x) => x.key !== v.key))}
              >
                <X size={14} aria-hidden="true" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="combo">
        <Search size={16} className="combo-icon" aria-hidden="true" />
        <input
          id={id}
          className="input combo-input"
          role="combobox"
          aria-expanded={open && hits.length > 0}
          aria-controls={listId}
          aria-activedescendant={open && hits[active] ? `${listId}-${active}` : undefined}
          autoComplete="off"
          placeholder={placeholder}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={onKeyDown}
        />
        {open && hits.length > 0 && (
          <ul className="combo-list sheet" id={listId} role="listbox">
            {hits.map((h, i) => (
              <li
                key={h.key}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                className={i === active ? 'is-active' : undefined}
                onMouseDown={(e) => {
                  e.preventDefault();
                  add(h);
                }}
                onMouseEnter={() => setActive(i)}
              >
                <span>
                  <strong>{h.label}</strong>
                  {h.code && <span className="hint num"> {h.code}</span>}
                  {h.detail && <span className="hint"> ({h.detail})</span>}
                </span>
                <span className={`tag${h.has_rules ? ' tag-rules' : ''}`}>
                  {h.has_rules ? 'Has rules' : 'No rules yet'}
                </span>
              </li>
            ))}
          </ul>
        )}
        {open && query.trim() && hits.length === 0 && (
          <p className="combo-list sheet combo-empty" role="status">
            {allAdded
              ? 'Already in your list.'
              : `No match for “${query.trim()}”.${allowFree ? ' Press Enter to add it anyway.' : ''}`}
          </p>
        )}
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
