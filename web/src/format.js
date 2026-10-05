// Date and number formatting shared by the screens.

export const dateKey = (date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
export const startOfWeek = (date) => {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d;
};
export const localInput = (value) => {
  if (!value) return "";
  const d = new Date(value);
  return `${dateKey(d)}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};
export const clock = (value) =>
  value ? new Date(value).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "Time not set";

export const formatBytes = (value) =>
  value < 1_048_576 ? `${Math.round(value / 1024)} KB` : `${(value / 1_048_576).toFixed(1)} MB`;

export const initials = (name) =>
  name
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
