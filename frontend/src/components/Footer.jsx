export default function Footer() {
  return (
    <footer className="footer">
      <div className="container">
        <span>
          RxGuard is a research prototype, not a medical device and not medical advice. Always check with a
          pharmacist or clinician.
        </span>
        <span>
          Interaction data includes{' '}
          <a href="https://ddinter.scbdd.com" target="_blank" rel="noreferrer">
            DDInter
          </a>{' '}
          (CC BY-NC-SA 4.0), used for non-commercial research. Drug labels from{' '}
          <a href="https://dailymed.nlm.nih.gov" target="_blank" rel="noreferrer">
            DailyMed
          </a>
          .
        </span>
      </div>
    </footer>
  );
}
