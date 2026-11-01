import { useSyncExternalStore } from 'react';

// Hash routes (#/, #/check, #/signin): no router dependency and no SPA fallback needed on the server.
const subscribe = (onChange) => {
  window.addEventListener('hashchange', onChange);
  return () => window.removeEventListener('hashchange', onChange);
};

const current = () => window.location.hash.replace(/^#/, '') || '/';

export const useRoute = () => useSyncExternalStore(subscribe, current);

export const navigate = (path) => {
  window.location.hash = path;
};
