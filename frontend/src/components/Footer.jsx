import Logo from './Logo';

const external = { target: '_blank', rel: 'noreferrer' };

export default function Footer() {
  return (
    <footer className="footer">
      <div className="container footer-grid">
        <div className="footer-brand">
          <a className="brand" href="#/">
            <Logo />
            LabelSafe
          </a>
          <p>
            Checks your medicines against food, conditions and allergies, and explains every risk with quotes from
            official FDA labels.
          </p>
        </div>

        <nav aria-label="Footer">
          <h2 className="footer-title">LabelSafe</h2>
          <ul>
            <li>
              <a href="#/check">Check interactions</a>
            </li>
            <li>
              <a href="#/profile">Your profile</a>
            </li>
            <li>
              <a href="https://github.com/hxrdikk21/label-safe" {...external}>
                Source on GitHub
              </a>
            </li>
          </ul>
        </nav>

        <nav aria-label="Legal">
          <h2 className="footer-title">Legal</h2>
          <ul>
            <li>
              <a href="#/privacy">Privacy Policy</a>
            </li>
            <li>
              <a href="#/terms">Terms of Use</a>
            </li>
            <li>
              <a href="mailto:hardiksachdeva.cs@gmail.com">Contact</a>
            </li>
          </ul>
        </nav>

        <div>
          <h2 className="footer-title">Data sources</h2>
          <ul>
            <li>
              <a href="https://dailymed.nlm.nih.gov" {...external}>
                DailyMed
              </a>{' '}
              and{' '}
              <a href="https://open.fda.gov" {...external}>
                openFDA
              </a>{' '}
              drug labels
            </li>
            <li>
              <a href="https://ddinter.scbdd.com" {...external}>
                DDInter
              </a>{' '}
              (CC BY-NC-SA 4.0, non-commercial)
            </li>
          </ul>
        </div>
      </div>

      <div className="container footer-bottom">
        <p>
          LabelSafe is a research prototype, not a medical device and not medical advice. Always check with a
          pharmacist or clinician.
        </p>
        <p>© 2026 Hardik Sachdeva</p>
      </div>
    </footer>
  );
}
