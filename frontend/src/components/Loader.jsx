// Interaction-dots loader; its .loader* styles live in index.html, shared with the boot loader.
// overlay: covers the whole page (page changes); otherwise fills the content area (lazy page code).
export default function Loader({ overlay = false, done = false }) {
  const className = ['loader', overlay && 'loader-overlay', done && 'is-done'].filter(Boolean).join(' ');
  return (
    <div className={className} role="status" aria-label="Loading">
      <span className="loader-dots" aria-hidden="true">
        <i />
        <i />
        <i />
        <i />
      </span>
    </div>
  );
}
