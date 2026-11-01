import { useEffect, useState } from 'react';
import Header from './components/Header';
import Footer from './components/Footer';
import Landing from './pages/Landing';
import Check from './pages/Check';
import Profile from './pages/Profile';
import SignIn from './pages/SignIn';
import { useRoute, navigate } from './router';
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

  useEffect(() => {
    window.scrollTo(0, 0);
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

  let page = <Landing />;
  if (route === '/check') page = <Check user={user} />;
  else if (route === '/signin') page = <SignIn onSignedIn={signedIn} />;
  else if (route === '/profile') page = <Profile user={user} />;

  return (
    <div className="app">
      <Header route={route} user={user} onSignOut={signOut} />
      <main>{page}</main>
      <Footer />
    </div>
  );
}
