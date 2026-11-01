export default function Header({ route, user, onSignOut }) {
  const current = (path) => (route === path ? 'page' : undefined);
  return (
    <header className="header">
      <div className="container">
        <a className="brand" href="#/">
          <span className="rx-mark" aria-hidden="true">
            Rx
          </span>
          RxGuard
        </a>
        <nav className="nav" aria-label="Main">
          <a href="#/check" aria-current={current('/check')}>
            Check
          </a>
          {user ? (
            <>
              <a href="#/profile" aria-current={current('/profile')}>
                Profile
              </a>
              <span className="muted nav-user">{user.full_name || user.username}</span>
              <button type="button" className="link" onClick={onSignOut}>
                Sign out
              </button>
            </>
          ) : (
            <a href="#/signin" aria-current={current('/signin')}>
              Sign in
            </a>
          )}
        </nav>
      </div>
    </header>
  );
}
