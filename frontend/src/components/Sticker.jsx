// An auxiliary-label sticker; `tone` is the interaction type colour (ddi, food, condition, allergy).
export default function Sticker({ tone, children, className = '', style }) {
  return (
    <span className={`sticker tone-${tone} ${className}`} style={style}>
      {children}
    </span>
  );
}
