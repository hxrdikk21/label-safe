import { useState } from 'react';

const KEY = 'labelsafe_storage_notice';

// localStorage can throw (private mode, blocked site data): then the notice just shows again next visit.
const seen = () => {
  try {
    return localStorage.getItem(KEY) === '1';
  } catch {
    return false;
  }
};

export default function CookieNotice() {
  const [open, setOpen] = useState(() => !seen());
  if (!open) return null;

  const dismiss = () => {
    try {
      localStorage.setItem(KEY, '1');
    } catch {
      // Not stored; dismiss for this visit only.
    }
    setOpen(false);
  };

  return (
    <div className="cookie-notice sheet" role="region" aria-label="Storage notice">
      <p>
        LabelSafe uses no tracking cookies. Your browser only stores what&apos;s needed to keep you signed in.{' '}
        <a href="#/privacy">Privacy Policy</a>
      </p>
      <button type="button" className="btn btn-primary btn-small" onClick={dismiss}>
        Got it
      </button>
    </div>
  );
}
