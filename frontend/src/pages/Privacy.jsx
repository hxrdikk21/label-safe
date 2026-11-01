const CONTACT = 'hardiksachdeva.cs@gmail.com';

export default function Privacy() {
  return (
    <div className="container page">
      <div className="page-head">
        <h1>Privacy Policy</h1>
        <p className="muted">Last updated 1 November 2026</p>
      </div>
      <article className="sheet legal">
        <p>
          LabelSafe is a personal research project by Hardik Sachdeva. This page explains what the site stores, why,
          and how to have it removed. The short version: only what is needed to run the checks you ask for, no ads, no
          tracking.
        </p>

        <h2>What we store</h2>
        <ul>
          <li>
            <strong>Without an account:</strong> nothing. The medicines, foods, conditions and allergies you enter are
            sent to the server to run the check and are not saved.
          </li>
          <li>
            <strong>With an account:</strong> your username, an Argon2id hash of your password (never the password
            itself), and optionally your name and email. If you fill in your profile, we store the medicines,
            conditions, allergies, care team and history you add so future checks can start from them.
          </li>
          <li>
            <strong>Security logs:</strong> failed sign-in attempts and request counts per IP address, kept briefly to
            stop brute-force and spam.
          </li>
        </ul>

        <h2>Cookies and browser storage</h2>
        <p>
          LabelSafe sets no tracking or advertising cookies and uses no analytics. Your browser&apos;s local storage
          keeps your sign-in token (so you stay signed in) and whether you have dismissed the storage notice. Both are
          strictly necessary and stay on your device until you sign out or clear site data.
        </p>

        <h2>Who else sees your data</h2>
        <ul>
          <li>
            <strong>Google Gemini:</strong> when an explanation is written, the finding and the matching FDA label
            passages are sent to Google&apos;s Gemini API. Your name, email and account details are never included.
          </li>
          <li>
            <strong>Hosting:</strong> the server and database that run the site.
          </li>
        </ul>
        <p>Your data is never sold or shared for marketing.</p>

        <h2>Your choices</h2>
        <p>
          You can edit or clear your profile at any time on the Profile page. To delete your account and everything
          linked to it, or to get a copy of your data, email <a href={`mailto:${CONTACT}`}>{CONTACT}</a>. Requests are
          handled within 30 days.
        </p>

        <h2>Health information</h2>
        <p>
          LabelSafe is a research prototype, not a healthcare provider, and is not covered by HIPAA. Please don&apos;t
          enter information you aren&apos;t comfortable storing on a personal project.
        </p>

        <h2>Changes</h2>
        <p>
          If this policy changes, the date at the top changes too. Questions: <a href={`mailto:${CONTACT}`}>{CONTACT}</a>.
        </p>
      </article>
    </div>
  );
}
