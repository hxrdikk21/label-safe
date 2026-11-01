import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import Header from './components/Header';
import Footer from './components/Footer';
import CookieNotice from './components/CookieNotice';
import Landing from './pages/Landing';
import NotFound from './pages/NotFound';
import Loader from './components/Loader';

// Only the landing page ships in the first bundle; the rest load when opened.
const Check = lazy(() => import('./pages/Check'));
const Profile = lazy(() => import('./pages/Profile'));
const SignIn = lazy(() => import('./pages/SignIn'));
const Privacy = lazy(() => import('./pages/Privacy'));
const Terms = lazy(() => import('./pages/Terms'));
import { useRoute, navigate } from './router';

const TITLES = {
  '/': 'LabelSafe — medication interaction checker',
  '/check': 'Check interactions · LabelSafe',
  '/signin': 'Sign in · LabelSafe',
  '/profile': 'Your profile · LabelSafe',
  '/privacy': 'Privacy Policy · LabelSafe',
  '/terms': 'Terms of Use · LabelSafe',
};
import { authApi, getStoredToken, getStoredUser, removeStoredToken, setStoredUser } from './services/api';

export default function App() {
  const route = useRoute();
  const [user, setUser] = useState(getStoredUser());

  useEffect(() => {
    if (!getStoredToken()) return;
    authApi
      .me()
      .then((me) => {
        setStoredUser(me);
        setUser(me);
      })
      .catch(() => {
        // Expired or invalid token: fall back to signed-out.
        removeStoredToken();
        setUser(null);
      });
  }, []);

  // Page-change loader: on for 450 ms, then a 250 ms fade. The first render is covered by the boot loader.
  const [transition, setTransition] = useState(null); // null | 'on' | 'done'
  const firstRoute = useRef(true);
  useEffect(() => {
    if (firstRoute.current) {
      firstRoute.current = false;
      return undefined;
    }
    setTransition('on');
    const fade = setTimeout(() => setTransition('done'), 450);
    const hide = setTimeout(() => setTransition(null), 700);
    return () => {
      clearTimeout(fade);
      clearTimeout(hide);
    };
  }, [route]);

  useEffect(() => {
    window.scrollTo(0, 0);
    document.title = TITLES[route] ?? 'Page not found · LabelSafe';
  }, [route]);

  const signOut = async () => {
    await authApi.logout().catch(() => {});
    removeStoredToken();
    setUser(null);
    navigate('/');
  };

  const signedIn = (me) => {
    setUser(me);
    navigate('/check');
  };

  let page = <NotFound />;
  if (route === '/') page = <Landing />;
  else if (route === '/check') page = <Check user={user} />;
  else if (route === '/signin') page = <SignIn onSignedIn={signedIn} />;
  else if (route === '/profile') page = <Profile user={user} />;
  else if (route === '/privacy') page = <Privacy />;
  else if (route === '/terms') page = <Terms />;

  return (
    <div className="app">
      <Header route={route} user={user} onSignOut={signOut} />
      <main>
        <Suspense fallback={<Loader />}>{page}</Suspense>
      </main>
      {transition && <Loader overlay done={transition === 'done'} />}
      <Footer />
      <CookieNotice />
    </div>
  );
}
