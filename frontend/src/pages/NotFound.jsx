import Logo from '../components/Logo';

export default function NotFound() {
  return (
    <div className="container page not-found">
      <Logo size={56} />
      <h1>Page not found</h1>
      <p className="muted">This page doesn&apos;t exist or has moved. Your medicine checks are still one click away.</p>
      <div className="hero-actions">
        <a className="btn btn-primary" href="#/check">
          Start a check
        </a>
        <a className="btn btn-ghost" href="#/">
          Go home
        </a>
      </div>
    </div>
  );
}
