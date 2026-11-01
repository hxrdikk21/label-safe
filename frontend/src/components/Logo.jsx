// LabelSafe logo: a shield (safety) protecting a capsule (medicine). Same paths as public/favicon.svg.
export default function Logo({ size = 30 }) {
  return (
    <svg className="logo" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <path d="M16 2 28 6.5V15c0 7.4-5.1 12.6-12 15C9.1 27.6 4 22.4 4 15V6.5Z" fill="#13233a" />
      <g transform="rotate(-45 16 16)">
        <rect x="12.4" y="7.6" width="7.2" height="16.8" rx="3.6" fill="#fff" />
        <path d="M12.4 16h7.2v4.8a3.6 3.6 0 0 1-7.2 0Z" fill="#ee7b30" />
      </g>
    </svg>
  );
}
