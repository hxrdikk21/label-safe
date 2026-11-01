const CONTACT = 'hardiksachdeva.cs@gmail.com';

export default function Terms() {
  return (
    <div className="container page">
      <div className="page-head">
        <h1>Terms of Use</h1>
        <p className="muted">Last updated 1 November 2026</p>
      </div>
      <article className="sheet legal">
        <p>
          By using LabelSafe you agree to these terms. LabelSafe is a personal research and educational project by
          Hardik Sachdeva.
        </p>

        <h2>Not medical advice</h2>
        <p>
          LabelSafe is <strong>not</strong> a medical device and does not give medical advice, diagnosis or treatment.
          Results can be incomplete or wrong, and &ldquo;nothing found&rdquo; never means a combination is safe. Never
          start, stop or change a medicine because of LabelSafe. Always ask a doctor or pharmacist. In an emergency,
          call your local emergency number.
        </p>

        <h2>Your account</h2>
        <p>
          Keep your password private, and turn on two-factor authentication if you can. You are responsible for what
          happens under your account. You must be at least 18, or have a parent or guardian&apos;s permission.
        </p>

        <h2>Acceptable use</h2>
        <ul>
          <li>Don&apos;t try to break, overload or get around the site&apos;s security or rate limits.</li>
          <li>Don&apos;t scrape the site or use it to build a competing database.</li>
          <li>Don&apos;t enter other people&apos;s health information without their permission.</li>
        </ul>
        <p>Accounts that break these rules may be suspended.</p>

        <h2>Data sources and licences</h2>
        <p>
          Drug labels come from DailyMed and openFDA (U.S. National Library of Medicine and FDA). Some interaction data
          comes from DDInter, licensed CC BY-NC-SA 4.0, so LabelSafe may only be used for non-commercial purposes.
        </p>

        <h2>No warranty</h2>
        <p>
          LabelSafe is provided &ldquo;as is&rdquo;, without warranties of any kind, and may change or go offline at any
          time. To the extent the law allows, Hardik Sachdeva is not liable for any harm arising from its use.
        </p>

        <h2>Changes and contact</h2>
        <p>
          These terms may be updated; the date at the top shows the latest version. Questions:{' '}
          <a href={`mailto:${CONTACT}`}>{CONTACT}</a>. See also the <a href="#/privacy">Privacy Policy</a>.
        </p>
      </article>
    </div>
  );
}
