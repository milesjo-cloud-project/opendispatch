// The OpenDispatch logo. Its own file so the public pages can use it without the whole app.
export default function Gear() {
  const teeth = Array.from({ length: 8 }, (_, i) => (
    <rect key={i} x="21" y="2" width="6" height="9" rx="1" transform={`rotate(${i * 45} 24 24)`} />
  ));
  return (
    <svg className="gear" viewBox="0 0 48 48" aria-hidden="true">
      {teeth}
      <circle cx="24" cy="24" r="14" />
      <circle cx="24" cy="24" r="5.5" className="gear-hole" />
    </svg>
  );
}
