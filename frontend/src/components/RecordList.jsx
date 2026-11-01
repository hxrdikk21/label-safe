import { useId, useState } from 'react';
import { Plus, X } from 'lucide-react';

// A list of profile records (hospitals, doctors, visits, prescriptions) with an inline add form.
// `fields`: [{ name, label, required?, type?: 'date' | 'textarea', options? }].
// `summary(record)` returns { title, detail } for each row.
export default function RecordList({ title, hint, fields, values, onChange, summary, addLabel }) {
  const id = useId();
  const blank = Object.fromEntries(fields.map((f) => [f.name, f.options ? f.options[0] : '']));
  const [draft, setDraft] = useState(null);

  const save = (e) => {
    e.preventDefault();
    // Empty optional fields are sent as null, which the API stores as "not given".
    const record = Object.fromEntries(fields.map((f) => [f.name, draft[f.name].trim() || null]));
    onChange([...values, record]);
    setDraft(null);
  };

  return (
    <section className="sheet records" aria-labelledby={`${id}-title`}>
      <div className="records-head">
        <h2 id={`${id}-title`}>{title}</h2>
        {!draft && (
          <button type="button" className="btn btn-ghost btn-small" onClick={() => setDraft(blank)}>
            <Plus size={16} aria-hidden="true" /> {addLabel}
          </button>
        )}
      </div>
      {hint && <p className="hint">{hint}</p>}

      {values.length > 0 ? (
        <ul className="record-rows">
          {values.map((r, i) => {
            const { title: rowTitle, detail } = summary(r);
            return (
              <li key={i}>
                <span>
                  <strong>{rowTitle}</strong>
                  {detail && <span className="hint"> {detail}</span>}
                </span>
                <button
                  type="button"
                  className="icon-btn"
                  aria-label={`Remove ${rowTitle}`}
                  onClick={() => onChange(values.filter((_, j) => j !== i))}
                >
                  <X size={16} aria-hidden="true" />
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        !draft && <p className="muted">None added.</p>
      )}

      {draft && (
        <form className="record-form" onSubmit={save}>
          {fields.map((f) => {
            const inputId = `${id}-${f.name}`;
            const props = {
              id: inputId,
              className: 'input',
              required: f.required,
              value: draft[f.name],
              onChange: (e) => setDraft({ ...draft, [f.name]: e.target.value }),
            };
            return (
              <div className={`field${f.type === 'textarea' ? ' field-wide' : ''}`} key={f.name}>
                <label htmlFor={inputId}>
                  {f.label}
                  {!f.required && <span className="hint"> (optional)</span>}
                </label>
                {f.type === 'textarea' ? (
                  <textarea rows={3} {...props} />
                ) : f.options ? (
                  <select {...props}>
                    {f.options.map((o) => (
                      <option key={o} value={o}>
                        {o.charAt(0) + o.slice(1).toLowerCase()}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input type={f.type || 'text'} {...props} />
                )}
              </div>
            );
          })}
          <div className="form-actions field-wide">
            <button className="btn btn-primary">Add</button>
            <button type="button" className="btn btn-ghost" onClick={() => setDraft(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
