import { useState } from 'react';
import { authApi, setStoredToken, setStoredUser } from '../services/api';

export default function SignIn({ onSignedIn }) {
  const [mode, setMode] = useState('signin');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [code, setCode] = useState('');
  const [needsCode, setNeedsCode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const finish = async (tokens) => {
    setStoredToken(tokens.access_token);
    localStorage.setItem('rxguard_refresh_token', tokens.refresh_token);
    const me = await authApi.me();
    setStoredUser(me);
    onSignedIn(me);
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === 'register') {
        await authApi.register({
          username,
          password,
          email: email || null,
          full_name: fullName || null,
        });
      }
      const tokens = await authApi.login({ username, password, totp_code: needsCode ? code : null });
      if (tokens.requires_2fa) {
        setNeedsCode(true);
        return;
      }
      await finish(tokens);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const switchMode = () => {
    setMode(mode === 'signin' ? 'register' : 'signin');
    setError(null);
    setNeedsCode(false);
  };

  return (
    <div className="container page auth">
      <form className="sheet form auth-card" onSubmit={submit}>
        <h1>{mode === 'signin' ? 'Sign in' : 'Create an account'}</h1>
        <p className="muted">An account saves your conditions and allergies so every check starts with them.</p>

        <div className="field">
          <label htmlFor="username">Username</label>
          <input
            id="username"
            className="input"
            autoComplete="username"
            required
            minLength={3}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        {mode === 'register' && (
          <div className="field">
            <label htmlFor="full-name">Full name (optional)</label>
            <input
              id="full-name"
              className="input"
              autoComplete="name"
              maxLength={128}
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </div>
        )}
        {mode === 'register' && (
          <div className="field">
            <label htmlFor="email">Email (optional)</label>
            <input
              id="email"
              type="email"
              className="input"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
        )}
        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            className="input"
            autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {mode === 'register' && (
            <span className="hint">
              At least 8 characters, with an upper- and lower-case letter, a number and a symbol.
            </span>
          )}
        </div>
        {needsCode && (
          <div className="field">
            <label htmlFor="code">Authenticator code</label>
            <input
              id="code"
              className="input mono"
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </div>
        )}

        {error && <p className="error">{error}</p>}
        <button className="btn btn-primary" disabled={busy}>
          {busy ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Create account'}
        </button>
        <p className="hint">
          {mode === 'signin' ? 'New to RxGuard?' : 'Already have an account?'}{' '}
          <button type="button" className="link text-link" onClick={switchMode}>
            {mode === 'signin' ? 'Create an account' : 'Sign in'}
          </button>
        </p>
      </form>
    </div>
  );
}
